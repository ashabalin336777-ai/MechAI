"""Чтение журнала агента для страницы /admin/logs: agent_runs и agent_steps, только SELECT.

Сессия открывается с default_transaction_read_only, поэтому даже ошибка в запросе не запишет
данные. Ходы фильтруются по tenant_id; шаги берём только для хода, который прошёл фильтр.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from pydantic import BaseModel

from app.obs.journal import TENANT_ID

CONNECT_TIMEOUT_S = 5
READ_ONLY_OPTIONS = "-c default_transaction_read_only=on"

_RUN_COLUMNS = (
    "id, started_at, vehicle_id, session_id, status, total_ms, prompt_tokens, completion_tokens, "
    "tok_per_s, cost_rub, lang, input_mode"
)
_STEP_COLUMNS = (
    "n, kind, name, ms, ttft_ms, prompt_tokens, completion_tokens, tok_per_s, model, error, "
    "error_class, error_message, input, output"
)


class AgentRunRow(BaseModel):
    id: int
    started_at: datetime
    vehicle_id: str | None
    session_id: str | None
    status: str
    total_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    tok_per_s: Decimal | None
    cost_rub: Decimal | None
    lang: str = "ru"
    input_mode: str = "text"


class AgentStepRow(BaseModel):
    n: int
    kind: str
    name: str
    ms: int | None
    ttft_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    tok_per_s: Decimal | None
    model: str | None
    error: str | None
    error_class: str | None
    error_message: str | None
    input: dict[str, Any] | None
    output: dict[str, Any] | None


class PgJournalReader:
    def __init__(self, database_url: str) -> None:
        self._url = database_url

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(
            self._url,
            connect_timeout=CONNECT_TIMEOUT_S,
            autocommit=True,
            options=READ_ONLY_OPTIONS,
        )

    def list_runs(self, status: str | None, limit: int) -> list[AgentRunRow]:
        """Последние ходы; status — ok, error, running или None (все)."""
        where = "tenant_id = %s"
        args: list[Any] = [TENANT_ID]
        if status is not None:
            where += " AND status = %s"
            args.append(status)
        args.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM agent_runs WHERE {where} ORDER BY id DESC LIMIT %s",
                args,
            ).fetchall()
        return [_run(row) for row in rows]

    def get_run(self, run_id: int) -> AgentRunRow | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM agent_runs WHERE tenant_id = %s AND id = %s",
                (TENANT_ID, run_id),
            ).fetchone()
        return None if row is None else _run(row)

    def list_steps(self, run_id: int) -> list[AgentStepRow]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_STEP_COLUMNS} FROM agent_steps WHERE run_id = %s ORDER BY n",
                (run_id,),
            ).fetchall()
        return [_step(row) for row in rows]


def _run(row: tuple[Any, ...]) -> AgentRunRow:
    return AgentRunRow(
        id=row[0],
        started_at=row[1],
        vehicle_id=row[2],
        session_id=row[3],
        status=row[4],
        total_ms=row[5],
        prompt_tokens=row[6],
        completion_tokens=row[7],
        tok_per_s=row[8],
        cost_rub=row[9],
        lang=row[10],
        input_mode=row[11],
    )


def _step(row: tuple[Any, ...]) -> AgentStepRow:
    return AgentStepRow(
        n=row[0],
        kind=row[1],
        name=row[2],
        ms=row[3],
        ttft_ms=row[4],
        prompt_tokens=row[5],
        completion_tokens=row[6],
        tok_per_s=row[7],
        model=row[8],
        error=row[9],
        error_class=row[10],
        error_message=row[11],
        input=row[12],
        output=row[13],
    )
