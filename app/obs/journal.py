"""Журнал агента: agent_runs и agent_steps (ТЗ §4.1, §14).

Голос, PIN, токены и заголовок Authorization сюда не пишем: в шаги попадают аргументы инструментов
и краткие результаты, которые вызывающий код уже очистил.
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb

TENANT_ID = "demo"
SNIPPET_LIMIT = 1500


@dataclass
class StepRecord:
    run_id: int
    n: int
    kind: str
    name: str
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    ms: int | None = None
    ttft_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tok_per_s: float | None = None
    model: str | None = None
    error: str | None = None
    error_class: str | None = None
    error_message: str | None = None
    cost_rub: Decimal | None = None


@dataclass
class RunSummary:
    status: str
    total_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tok_per_s: float | None = None
    cost_rub: Decimal | None = None


class Journal(Protocol):
    def start_run(
        self, *, vehicle_id: str | None, session_id: str | None, lang: str, input_mode: str = "text"
    ) -> int: ...

    def add_step(self, step: StepRecord) -> None: ...

    def finish_run(self, run_id: int, summary: RunSummary) -> None: ...


class NullJournal:
    """Журнал без БД (тесты, локальный запуск без DATABASE_URL)."""

    def __init__(self) -> None:
        self._next_run = 0

    def start_run(
        self, *, vehicle_id: str | None, session_id: str | None, lang: str, input_mode: str = "text"
    ) -> int:
        self._next_run += 1
        return self._next_run

    def add_step(self, step: StepRecord) -> None:
        return None

    def finish_run(self, run_id: int, summary: RunSummary) -> None:
        return None


@dataclass
class MemoryJournal(NullJournal):
    """Журнал в памяти: тесты проверяют цепочки инструментов и события guardrails."""

    steps: list[StepRecord] = field(default_factory=list)
    runs: dict[int, RunSummary] = field(default_factory=dict)
    input_modes: dict[int, str] = field(default_factory=dict)
    started: int = 0

    def start_run(
        self, *, vehicle_id: str | None, session_id: str | None, lang: str, input_mode: str = "text"
    ) -> int:
        self.started += 1
        self.input_modes[self.started] = input_mode
        return self.started

    def add_step(self, step: StepRecord) -> None:
        self.steps.append(step)

    def finish_run(self, run_id: int, summary: RunSummary) -> None:
        self.runs[run_id] = summary

    def chain(self, run_id: int) -> list[str]:
        """Цепочка инструментов хода, например ['get_diagnosis', 'search_manual']."""
        return [s.name for s in self.steps if s.run_id == run_id and s.kind == "tool"]


class PgJournal:
    """Пишет в PostgreSQL. Соединение открываем на запись: запись редкая, пул не нужен."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url

    def start_run(
        self, *, vehicle_id: str | None, session_id: str | None, lang: str, input_mode: str = "text"
    ) -> int:
        with psycopg.connect(self._url, connect_timeout=5, autocommit=True) as conn:
            row = conn.execute(
                "INSERT INTO agent_runs (tenant_id, vehicle_id, session_id, lang, input_mode) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (TENANT_ID, vehicle_id, session_id, lang, input_mode),
            ).fetchone()
        assert row is not None
        return int(row[0])

    def add_step(self, step: StepRecord) -> None:
        with psycopg.connect(self._url, connect_timeout=5, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO agent_steps (run_id, n, kind, name, input, output, ms, ttft_ms, "
                "prompt_tokens, completion_tokens, tok_per_s, model, error, error_class, "
                "error_message, cost_rub) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    step.run_id,
                    step.n,
                    step.kind,
                    step.name,
                    _json(step.input),
                    _json(step.output),
                    step.ms,
                    step.ttft_ms,
                    step.prompt_tokens,
                    step.completion_tokens,
                    step.tok_per_s,
                    step.model,
                    step.error,
                    step.error_class,
                    step.error_message,
                    step.cost_rub,
                ),
            )

    def finish_run(self, run_id: int, summary: RunSummary) -> None:
        with psycopg.connect(self._url, connect_timeout=5, autocommit=True) as conn:
            conn.execute(
                "UPDATE agent_runs SET status = %s, total_ms = %s, prompt_tokens = %s, "
                "completion_tokens = %s, tok_per_s = %s, cost_rub = %s WHERE id = %s",
                (
                    summary.status,
                    summary.total_ms,
                    summary.prompt_tokens,
                    summary.completion_tokens,
                    summary.tok_per_s,
                    summary.cost_rub,
                    run_id,
                ),
            )


def _json(value: dict[str, Any] | None) -> Jsonb | None:
    if value is None:
        return None
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > SNIPPET_LIMIT:
        return Jsonb({"truncated": text[:SNIPPET_LIMIT]})
    return Jsonb(json.loads(text))
