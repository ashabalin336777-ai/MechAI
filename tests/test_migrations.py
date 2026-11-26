"""Миграции против настоящего PostgreSQL с pgvector. Запускаются, если задан TEST_DATABASE_URL.

Пример (PowerShell):
    $env:TEST_DATABASE_URL="postgresql://mechai:...@127.0.0.1:5433/mechai"
    $env:TEST_DATABASE_ALLOW_RESET="1"; pytest tests/test_migrations.py
"""

import os

import psycopg
import pytest

from app.db.database import apply_migrations, list_migrations

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="нужен TEST_DATABASE_URL (PostgreSQL с pgvector)"
)
# Фикстура очищает схему public. Без явного разрешения не запускаем: нельзя затереть чужую БД.
ALLOW_RESET = os.environ.get("TEST_DATABASE_ALLOW_RESET") == "1"

EXPECTED_TABLES = {
    "tenants",
    "users",
    "manuals",
    "chunks",
    "diagnoses",
    "tickets",
    "recommendations",
    "agent_runs",
    "agent_steps",
    "schema_migrations",
}


@pytest.fixture(scope="module")
def migrated() -> str:
    """Чистая схема перед прогоном: все таблицы приложения удаляются, затем миграции."""
    if not ALLOW_RESET:
        pytest.skip("задайте TEST_DATABASE_ALLOW_RESET=1: тест очищает схему public тестовой БД")
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    return TEST_DATABASE_URL


def test_first_run_applies_all_migrations(migrated: str) -> None:
    status = apply_migrations(migrated)
    assert status.state == "ok"
    assert status.migrations_applied == len(list_migrations())


def test_second_run_is_idempotent(migrated: str) -> None:
    status = apply_migrations(migrated)
    assert status.state == "ok"
    assert status.migrations_applied == 0


def test_schema_has_all_tables_and_demo_tenant(migrated: str) -> None:
    with psycopg.connect(migrated) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ).fetchall()
        }
        tenant = conn.execute("SELECT name FROM tenants WHERE id = 'demo'").fetchone()
    assert EXPECTED_TABLES <= names
    assert tenant == ("Демо-автопарк",)


def test_embedding_is_vector_1024(migrated: str) -> None:
    with psycopg.connect(migrated) as conn:
        dims = conn.execute(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
        ).fetchone()
    assert dims == (1024,)


def test_extensions_enabled(migrated: str) -> None:
    with psycopg.connect(migrated) as conn:
        names = {row[0] for row in conn.execute("SELECT extname FROM pg_extension").fetchall()}
    assert {"vector", "pg_trgm"} <= names


def test_unreachable_database_is_unavailable_not_exception() -> None:
    status = apply_migrations("postgresql://user:secret@127.0.0.1:1/db")
    assert status.state == "unavailable"
