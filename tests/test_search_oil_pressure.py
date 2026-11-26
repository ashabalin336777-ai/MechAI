"""Поиск по давлению масла ЯМЗ-236М2 (F02): стр. 19 РЭ и стр. 267 РК должны быть в топ-3.

Проверяется этап полнотекста PostgreSQL ('russian') на текстах реальных страниц руководств из
data/manuals. Эмбеддинги и реранкер Neuraldeep здесь не вызываются (тесты без сети): финальную
выдачу после реранкера проверяем на стенде через eval. Запрос строит тот же код, что в инструменте.

Нужны TEST_DATABASE_URL и TEST_DATABASE_ALLOW_RESET=1 (PostgreSQL с pgvector),
иначе тест пропускается.
"""

import os
from pathlib import Path

import psycopg
import pymupdf
import pytest

from app.db.database import apply_migrations
from app.rag.chunking import split_lines
from app.rag.embeddings import EMBED_DIM
from app.rag.search import TENANT_ID, _fulltext_candidates
from app.tools.search_manual import _build_query

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
ALLOW_RESET = os.environ.get("TEST_DATABASE_ALLOW_RESET") == "1"
needs_db = pytest.mark.skipif(
    not (TEST_DATABASE_URL and ALLOW_RESET),
    reason="нужны TEST_DATABASE_URL и TEST_DATABASE_ALLOW_RESET=1 (PostgreSQL с pgvector)",
)

MANUALS_DIR = Path(__file__).resolve().parents[1] / "data" / "manuals"
ENGINE = "ЯМЗ-236М2"
RE_DESIGNATION = "236-3902150-Б РЭ"
RK_DESIGNATION = "236.01.01 РК"
MANUAL_FILES = [
    ("yamz236_re", RE_DESIGNATION, "yamz-236_re_2010.pdf"),
    ("yamz236_rk", RK_DESIGNATION, "yamz-236_rk_2014.pdf"),
]
F02_TARGETS = {(RE_DESIGNATION, 19), (RK_DESIGNATION, 267)}


def _page_chunks(path: Path) -> list[tuple[int, str]]:
    """Текст страниц без выравнивания таблиц: для прозы стр. 19 РЭ и 267 РК этого достаточно."""
    chunks: list[tuple[int, str]] = []
    with pymupdf.open(path) as document:
        for number, page in enumerate(document, start=1):
            lines = [" ".join(line.split()) for line in page.get_text("text").splitlines()]
            lines = [line for line in lines if line]
            if len("\n".join(lines)) < 100:
                continue
            page_chunks, _ = split_lines(lines, None)
            chunks += [(number, text) for _, text in page_chunks]
    return chunks


@pytest.fixture
def database() -> psycopg.Connection:
    if not MANUALS_DIR.joinpath(MANUAL_FILES[0][2]).exists():
        pytest.skip("руководства ЯМЗ-236 не найдены в data/manuals")
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        apply_migrations(TEST_DATABASE_URL)
        _seed(conn)
        yield conn


def _seed(conn: psycopg.Connection) -> None:
    unit = "[1," + ",".join(["0"] * (EMBED_DIM - 1)) + "]"
    for manual_id, designation, file_name in MANUAL_FILES:
        conn.execute(
            "INSERT INTO manuals (tenant_id, id, designation, title, year, file_name, sha256, "
            "pages, engine_models) VALUES (%s, %s, %s, %s, 2010, %s, %s, 10, %s)",
            (TENANT_ID, manual_id, designation, designation, file_name, "a" * 64, [ENGINE]),
        )
        for page, text in _page_chunks(MANUALS_DIR / file_name):
            conn.execute(
                "INSERT INTO chunks (tenant_id, manual_id, engine_models, pdf_page, section, text, "
                "embedding) VALUES (%s, %s, %s, %s, NULL, %s, %s::vector)",
                (TENANT_ID, manual_id, [ENGINE], page, text, unit),
            )


def _top(conn: psycopg.Connection, query: str, limit: int) -> list[tuple[str, int]]:
    candidates = _fulltext_candidates(conn, TENANT_ID, ENGINE, query)
    return [(candidate.manual, candidate.pdf_page) for candidate in candidates[:limit]]


F02_DIAGNOSIS = {"ml": {"anomaly_title": "Низкое давление масла"}}


@needs_db
def test_f02_query_puts_re_page_19_or_rk_page_267_in_top_3(database: psycopg.Connection) -> None:
    query = _build_query("давление масла", F02_DIAGNOSIS)
    top = _top(database, query, 3)
    assert set(top) & F02_TARGETS, f"в топ-3 нет стр. 19 РЭ или 267 РК: {top}"


def test_f02_query_has_no_engine_name_and_has_norm_terms() -> None:
    query = _build_query("давление масла", F02_DIAGNOSIS)
    assert "ЯМЗ" not in query.upper()
    assert "Низкое давление масла" in query
    assert "номинальной частоте" in query
    assert "минимальной холостого хода" in query
