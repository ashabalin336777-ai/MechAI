"""Гибридный поиск: RRF без сети; фильтр по двигателю и порог — против настоящего PostgreSQL.

БД-тесты запускаются, если задан TEST_DATABASE_URL (см. tests/test_migrations.py).
Схема public очищается, поэтому нужен TEST_DATABASE_ALLOW_RESET=1.
"""

import os
from types import SimpleNamespace

import psycopg
import pytest

from app.db.database import apply_migrations
from app.rag.embeddings import EMBED_DIM
from app.rag.search import TENANT_ID, Candidate, reciprocal_rank_fusion, search

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
ALLOW_RESET = os.environ.get("TEST_DATABASE_ALLOW_RESET") == "1"
needs_db = pytest.mark.skipif(
    not (TEST_DATABASE_URL and ALLOW_RESET),
    reason="нужны TEST_DATABASE_URL и TEST_DATABASE_ALLOW_RESET=1 (PostgreSQL с pgvector)",
)


def _candidate(chunk_id: int) -> Candidate:
    return Candidate(
        id=chunk_id, manual_id="m", manual="М", pdf_page=1, section=None, text=str(chunk_id)
    )


def test_rrf_counts_each_chunk_once_and_prefers_chunks_found_by_both_lists() -> None:
    by_vector = [_candidate(1), _candidate(2), _candidate(3)]
    by_text = [_candidate(3), _candidate(4)]
    fused = reciprocal_rank_fusion([by_vector, by_text])
    ids = [candidate.id for candidate in fused]
    assert sorted(ids) == [1, 2, 3, 4]
    assert ids[0] == 3


def _unit_vector() -> list[float]:
    """Ненулевой вектор: у нулевого косинусное расстояние в pgvector не определено (NaN)."""
    return [1.0] + [0.0] * (EMBED_DIM - 1)


class _FixedEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_unit_vector() for _ in texts]


class _ScoreByOrder:
    """Реранкер-заглушка: оценка убывает с порядком кандидатов (0.9, 0.8, ...)."""

    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        return [(index, round(0.9 - 0.1 * index, 3)) for index in range(len(documents))]


@pytest.fixture
def database() -> psycopg.Connection:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        apply_migrations(TEST_DATABASE_URL)
        _seed(conn)
        yield conn


def _seed(conn: psycopg.Connection) -> None:
    manuals = [
        ("yamz236_rk", "236.01.01 РК", ["ЯМЗ-236М2"], "Момент затяжки крышек 25 Н·м для ЯМЗ."),
        (
            "zmz5234_rk",
            "ЗМЗ-5234.10 со сцеплением",
            ["ЗМЗ-5234.10"],
            "Момент затяжки крышек 40 Н·м для ЗМЗ.",
        ),
    ]
    unit = "[1," + ",".join(["0"] * (EMBED_DIM - 1)) + "]"
    for manual_id, designation, engines, text in manuals:
        conn.execute(
            "INSERT INTO manuals (tenant_id, id, designation, title, year, file_name, sha256, "
            "pages, engine_models) VALUES (%s, %s, %s, %s, 2014, 'f.pdf', %s, 10, %s)",
            (TENANT_ID, manual_id, designation, designation, "a" * 64, engines),
        )
        conn.execute(
            "INSERT INTO chunks (tenant_id, manual_id, engine_models, pdf_page, section, text, "
            "embedding) VALUES (%s, %s, %s, 3, NULL, %s, %s::vector)",
            (TENANT_ID, manual_id, engines, text, unit),
        )


@needs_db
def test_search_never_returns_fragments_of_another_engine(database: psycopg.Connection) -> None:
    fragments = search(
        database,
        "момент затяжки крышек",
        "ЯМЗ-236М2",
        _FixedEmbedder(),
        _ScoreByOrder(),
        top_k=5,
        min_score=0.0,
    )
    assert fragments
    assert all(fragment.manual_id == "yamz236_rk" for fragment in fragments)
    assert all("40 Н·м" not in fragment.text for fragment in fragments)


@needs_db
def test_search_for_zmz_returns_only_zmz(database: psycopg.Connection) -> None:
    fragments = search(
        database,
        "момент затяжки крышек",
        "ЗМЗ-5234.10",
        _FixedEmbedder(),
        _ScoreByOrder(),
        top_k=5,
        min_score=0.0,
    )
    assert fragments
    assert all(fragment.manual_id == "zmz5234_rk" for fragment in fragments)


@needs_db
def test_fragments_below_min_score_are_dropped(database: psycopg.Connection) -> None:
    fragments = search(
        database,
        "момент затяжки крышек",
        "ЯМЗ-236М2",
        _FixedEmbedder(),
        SimpleNamespace(rerank=lambda query, documents: [(0, 0.2)]),
        top_k=5,
        min_score=0.35,
    )
    assert fragments == []
