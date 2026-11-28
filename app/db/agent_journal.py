"""Чтение журнала агента для страницы /admin/logs: agent_runs и agent_steps, только SELECT.

Сессия открывается с default_transaction_read_only, поэтому даже ошибка в запросе не запишет
данные. Ходы фильтруются по tenant_id; шаги берём только для хода, который прошёл фильтр.

₽ шага: берём стоимость, записанную при вызове. Старые шаги (до миграции 0012) считаем по
токенам и прайсу app/obs/prices.py; если цены нет, получаем None, а не ноль.
"""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from pydantic import BaseModel

from app.obs.journal import TENANT_ID
from app.obs.prices import cost_rub, stt_cost_rub

CONNECT_TIMEOUT_S = 5
READ_ONLY_OPTIONS = "-c default_transaction_read_only=on"
# Модель хода — первый вызов модели или распознавания в ходе (шаги llm и stt).
_RUN_MODEL = (
    "(SELECT s.model FROM agent_steps s WHERE s.run_id = agent_runs.id "
    "AND s.kind IN ('llm', 'stt') AND s.model IS NOT NULL ORDER BY s.n LIMIT 1)"
)
_RUN_COLUMNS = (
    "id, started_at, vehicle_id, session_id, status, total_ms, prompt_tokens, completion_tokens, "
    f"tok_per_s, cost_rub, lang, input_mode, {_RUN_MODEL} AS model"
)
_STEP_COLUMNS = (
    "n, kind, name, ms, ttft_ms, prompt_tokens, completion_tokens, tok_per_s, model, error, "
    "error_class, error_message, input, output, cost_rub"
)
# Шаги, по которым в сводке видно модель и ₽ (ответ модели, распознавание, эмбеддинги, реранк).
_PRICED_KINDS = ("llm", "stt", "embed", "rerank")


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
    model: str | None = None


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
    cost_rub: Decimal | None = None


class ModelCost(BaseModel):
    model: str
    calls: int
    cost_rub: Decimal | None  # сумма по шагам с ценой; None, если ни один шаг не оценён


class PeriodSummary(BaseModel):
    """Сводка за период: ходы (без «идёт»), токены, ₽ и разбивка ₽ по моделям."""

    runs: int
    prompt_tokens: int
    completion_tokens: int
    cost_rub: Decimal | None  # сумма по ходам с ценой; None, если таких нет
    priced_runs: int
    models: list[ModelCost]


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

    def period_summary(self, since: datetime | None) -> PeriodSummary:
        """Сводка по ходам, начатым не раньше since (None — за всё время). Ходы «идёт» не берём."""
        since_clause = " AND started_at >= %s" if since is not None else ""
        since_args: list[Any] = [] if since is None else [since]
        with self._connect() as conn:
            totals = conn.execute(
                "SELECT count(*), coalesce(sum(prompt_tokens), 0), "
                "coalesce(sum(completion_tokens), 0), sum(cost_rub), count(cost_rub) "
                f"FROM agent_runs WHERE tenant_id = %s AND status <> 'running'{since_clause}",
                [TENANT_ID, *since_args],
            ).fetchone()
            steps = conn.execute(
                "SELECT s.kind, s.model, s.prompt_tokens, s.completion_tokens, s.cost_rub, "
                "s.output FROM agent_steps s JOIN agent_runs r ON r.id = s.run_id "
                "WHERE s.model IS NOT NULL AND s.kind = ANY(%s) "
                "AND r.tenant_id = %s AND r.status <> 'running'"
                + (" AND r.started_at >= %s" if since is not None else ""),
                [list(_PRICED_KINDS), TENANT_ID, *since_args],
            ).fetchall()
        assert totals is not None
        return _period(totals, steps)


def _period(totals: tuple[Any, ...], steps: list[tuple[Any, ...]]) -> PeriodSummary:
    runs, prompt, completion, cost_sum, priced = totals
    calls: dict[str, int] = defaultdict(int)
    model_cost: dict[str, Decimal] = {}
    for kind, model, prompt_tokens, completion_tokens, stored, output in steps:
        calls[model] += 1
        cost = _step_cost(kind, model, prompt_tokens, completion_tokens, stored, output)
        if cost is not None:
            model_cost[model] = model_cost.get(model, Decimal(0)) + cost
    models = [
        ModelCost(model=model, calls=count, cost_rub=model_cost.get(model))
        for model, count in sorted(calls.items())
    ]
    return PeriodSummary(
        runs=int(runs),
        prompt_tokens=int(prompt),
        completion_tokens=int(completion),
        cost_rub=cost_sum,
        priced_runs=int(priced),
        models=models,
    )


def _step_cost(
    kind: str,
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    stored: Decimal | None,
    output: dict[str, Any] | None,
) -> Decimal | None:
    if stored is not None:
        return stored
    if kind in ("llm", "embed") and model and prompt_tokens is not None:
        return cost_rub(model, prompt_tokens, completion_tokens or 0)
    if kind == "stt":
        duration = (output or {}).get("duration_s")
        if isinstance(duration, (int, float)):
            return stt_cost_rub(float(duration))
    return None


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
        model=row[12],
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
        cost_rub=_step_cost(row[1], row[8], row[5], row[6], row[14], row[13]),
    )
