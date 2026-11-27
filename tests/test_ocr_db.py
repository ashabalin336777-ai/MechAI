"""OCR в PostgreSQL: повторная запись страницы не дублирует чанки, текст не затрагивается.

Запускаются, если задан TEST_DATABASE_URL (PostgreSQL с pgvector). Схему не очищают: тестовое
руководство создаётся и удаляется само. Пример (PowerShell):
    $env:TEST_DATABASE_URL="postgresql://mechai:...@127.0.0.1:5433/mechai"
    pytest tests/test_ocr_db.py
"""

import os
from collections.abc import Iterator

import psycopg
import pytest

from app.db.database import apply_migrations
from app.rag.chunking import ChunkDraft
from app.rag.embeddings import EMBED_DIM, vector_literal
from app.rag.manifest import ManualEntry
from app.rag.ocr import TENANT_ID, PgOcrStore

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="нужен TEST_DATABASE_URL")

MANUAL_ID = "ocr_db_test"
PAGE = 280
ENTRY = ManualEntry(
    id=MANUAL_ID,
    designation="OCR тест",
    title="OCR тест",
    year=2026,
    file="ocr_db_test.pdf",
    sha256="0" * 64,
    pages=300,
    engine_models=["ЯМЗ-236М2"],
)


def _cleanup() -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute(
            "DELETE FROM chunks WHERE tenant_id = %s AND manual_id = %s", (TENANT_ID, MANUAL_ID)
        )
        conn.execute("DELETE FROM manuals WHERE tenant_id = %s AND id = %s", (TENANT_ID, MANUAL_ID))


@pytest.fixture
def store() -> Iterator[PgOcrStore]:
    apply_migrations(TEST_DATABASE_URL)
    _cleanup()
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute(
            "INSERT INTO manuals (tenant_id, id, designation, title, year, file_name, sha256, "
            "pages, engine_models, chunker_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                TENANT_ID,
                ENTRY.id,
                ENTRY.designation,
                ENTRY.title,
                ENTRY.year,
                ENTRY.file,
                ENTRY.sha256,
                ENTRY.pages,
                ENTRY.engine_models,
                3,
            ),
        )
    try:
        yield PgOcrStore(TEST_DATABASE_URL)
    finally:
        _cleanup()


def _chunks(text: str) -> list[ChunkDraft]:
    return [ChunkDraft(pdf_page=PAGE, section=None, text=text, source="ocr")]


def _vectors(count: int) -> list[list[float]]:
    return [[0.0] * EMBED_DIM for _ in range(count)]


def _count(source: str) -> int:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        return conn.execute(
            "SELECT count(*) FROM chunks WHERE tenant_id = %s AND manual_id = %s "
            "AND pdf_page = %s AND source = %s",
            (TENANT_ID, MANUAL_ID, PAGE, source),
        ).fetchone()[0]


def test_replacing_ocr_page_twice_keeps_one_set(store: PgOcrStore) -> None:
    store.replace_page(ENTRY, PAGE, _chunks("Таблица 6.12, 147 (200)"), _vectors(1))
    store.replace_page(ENTRY, PAGE, _chunks("Таблица 6.12, 147 (200)"), _vectors(1))

    assert _count("ocr") == 1
    assert store.ocr_pages(MANUAL_ID) == {PAGE}
    assert store.manual_exists(MANUAL_ID) is True
    assert store.manual_exists("no_such_manual") is False


def test_ocr_replace_keeps_text_chunks_of_same_page(store: PgOcrStore) -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute(
            "INSERT INTO chunks (tenant_id, manual_id, engine_models, pdf_page, section, text, "
            "embedding) VALUES (%s, %s, %s, %s, NULL, %s, %s::vector)",
            (
                TENANT_ID,
                MANUAL_ID,
                ENTRY.engine_models,
                PAGE,
                "текст слоя",
                vector_literal([0.0] * EMBED_DIM),
            ),
        )
    store.replace_page(ENTRY, PAGE, _chunks("распознано"), _vectors(1))
    store.replace_page(ENTRY, PAGE, _chunks("распознано"), _vectors(1))

    assert _count("text") == 1
    assert _count("ocr") == 1
