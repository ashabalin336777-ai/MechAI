"""Прогоны проверки в PostgreSQL: таблица eval_runs (миграция 0007).

Итог прогона (сводка и отчёт) пишется в строку при завершении, поэтому результат переживает
перезапуск сервиса. В таблицу попадают только текст отчёта и сводка; строка подключения,
ключи и токены сюда не пишутся, а текст ошибки уже очищен вызывающим кодом.
"""

from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

TENANT_ID = "demo"
CONNECT_TIMEOUT_S = 5
# Прогон, который «висит» дольше этого срока (процесс упал без записи итога), считаем прерванным.
STALE_AFTER = timedelta(minutes=30)
STALE_MESSAGE = "прогон прерван: сервис перезапущен до завершения"
ERROR_LIMIT = 300
# Блокировка на время проверки занятости: два одновременных POST не создадут два прогона.
EVAL_LOCK_KEY = 0x45564C  # «EVL»


class EvalCase(BaseModel):
    id: str
    passed: bool
    note: str = ""


class EvalResult(BaseModel):
    """Итог прогона: отчёт для человека и сводка для таблицы (report_json)."""

    report_md: str
    passed: int = Field(ge=0)
    total: int = Field(ge=0)
    cases: list[EvalCase] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return self.model_dump(exclude={"report_md"})


class EvalRunRecord(BaseModel):
    id: int
    suite: str
    commit_sha: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    passed: int | None
    total: int | None
    error_message: str | None
    report_md: str | None = None
    report_json: dict[str, Any] | None = None


_COLUMNS = (
    "id, suite, commit_sha, status, started_at, finished_at, passed, total, error_message, "
    "report_md, report_json"
)


class PgEvalRunStore:
    """Соединение открываем на каждый запрос: прогонов мало, пул не нужен (как в PgJournal)."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._url, connect_timeout=CONNECT_TIMEOUT_S, autocommit=True)

    def create_run(self, suite: str, commit_sha: str | None) -> int | None:
        """Создаёт строку running. None, если другой прогон ещё идёт.

        Залипшие running старше STALE_AFTER закрываются как error в той же транзакции.
        """
        with self._connect() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (EVAL_LOCK_KEY,))
            conn.execute(
                "UPDATE eval_runs SET status = 'error', finished_at = now(), error_message = %s "
                "WHERE tenant_id = %s AND status = 'running' AND started_at < now() - %s",
                (STALE_MESSAGE, TENANT_ID, STALE_AFTER),
            )
            busy = conn.execute(
                "SELECT 1 FROM eval_runs WHERE tenant_id = %s AND status = 'running' LIMIT 1",
                (TENANT_ID,),
            ).fetchone()
            if busy is not None:
                return None
            row = conn.execute(
                "INSERT INTO eval_runs (tenant_id, suite, commit_sha, status) "
                "VALUES (%s, %s, %s, 'running') RETURNING id",
                (TENANT_ID, suite, commit_sha),
            ).fetchone()
        assert row is not None
        return int(row[0])

    def finish_run(self, run_id: int, result: EvalResult) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE eval_runs SET status = 'done', finished_at = now(), passed = %s, "
                "total = %s, report_md = %s, report_json = %s "
                "WHERE tenant_id = %s AND id = %s",
                (
                    result.passed,
                    result.total,
                    result.report_md,
                    Jsonb(result.summary()),
                    TENANT_ID,
                    run_id,
                ),
            )

    def fail_run(self, run_id: int, message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE eval_runs SET status = 'error', finished_at = now(), error_message = %s "
                "WHERE tenant_id = %s AND id = %s",
                (message[:ERROR_LIMIT], TENANT_ID, run_id),
            )

    def get_run(self, run_id: int) -> EvalRunRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM eval_runs WHERE tenant_id = %s AND id = %s",
                (TENANT_ID, run_id),
            ).fetchone()
        return None if row is None else _record(row)

    def latest_run(self) -> EvalRunRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM eval_runs WHERE tenant_id = %s ORDER BY id DESC LIMIT 1",
                (TENANT_ID,),
            ).fetchone()
        return None if row is None else _record(row)

    def list_runs(self, limit: int) -> list[EvalRunRecord]:
        """Последние прогоны без report_md (текст отчёта читают отдельно по run_id)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, suite, commit_sha, status, started_at, finished_at, passed, total, "
                "error_message, NULL::text, report_json FROM eval_runs "
                "WHERE tenant_id = %s ORDER BY id DESC LIMIT %s",
                (TENANT_ID, limit),
            ).fetchall()
        return [_record(row) for row in rows]


def _record(row: tuple[Any, ...]) -> EvalRunRecord:
    return EvalRunRecord(
        id=row[0],
        suite=row[1],
        commit_sha=row[2],
        status=row[3],
        started_at=row[4],
        finished_at=row[5],
        passed=row[6],
        total=row[7],
        error_message=row[8],
        report_md=row[9],
        report_json=row[10],
    )
