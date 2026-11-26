"""PostgreSQL: проверка доступности и применение SQL-миграций при старте.

Пароль и DATABASE_URL в логи и ответы не попадают: в журнал пишем только класс ошибки.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import psycopg

logger = logging.getLogger("app.db")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
CONNECT_TIMEOUT_S = 3
MIGRATION_LOCK_KEY = 0x4D454348  # «MECH», чтобы несколько реплик не мигрировали одновременно

DatabaseState = Literal["not_configured", "ok", "unavailable", "migration_failed"]


@dataclass(frozen=True)
class DatabaseStatus:
    state: DatabaseState
    migrations_applied: int = 0


def check_database(database_url: str) -> DatabaseState:
    """SELECT 1 с коротким таймаутом. Пустой URL — «не настроена», это не ошибка."""
    if not database_url:
        return "not_configured"
    try:
        with psycopg.connect(database_url, connect_timeout=CONNECT_TIMEOUT_S) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as exc:
        logger.warning("БД недоступна: %s", type(exc).__name__)
        return "unavailable"
    return "ok"


def list_migrations() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def apply_migrations(database_url: str) -> DatabaseStatus:
    """Применяет недостающие миграции по порядку имён. Каждая — в своей транзакции. Идемпотентно."""
    if not database_url:
        return DatabaseStatus("not_configured")
    try:
        conn = psycopg.connect(database_url, connect_timeout=CONNECT_TIMEOUT_S, autocommit=True)
    except psycopg.Error as exc:
        logger.warning("БД недоступна при миграциях: %s", type(exc).__name__)
        return DatabaseStatus("unavailable")
    applied = 0
    try:
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()}
        for path in list_migrations():
            if path.name in done:
                continue
            sql = path.read_text(encoding="utf-8")
            with conn.transaction():
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied += 1
            logger.info("миграция применена: %s", path.name)
    except psycopg.Error as exc:
        logger.error("миграция не применена: %s", type(exc).__name__)
        return DatabaseStatus("migration_failed", applied)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
        conn.close()
    return DatabaseStatus("ok", applied)
