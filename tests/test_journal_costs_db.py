"""₽ в журнале PostgreSQL: цена шагов, модель хода, восстановление цены старых шагов, сводка.

Запускается, если задан TEST_DATABASE_URL. Тестовые строки помечены vehicle_id TEST-COST и
удаляются (шаги уходят каскадом). Сброс схемы не делаем.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.db.agent_journal import PgJournalReader
from app.db.database import apply_migrations
from app.obs.journal import PgJournal, RunSummary, StepRecord
from app.obs.prices import cost_rub

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="нужен TEST_DATABASE_URL")
TEST_VEHICLE = "TEST-COST"
QWEN = "qwen3.8-flash-next-ru-noreason"


def _cleanup() -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute("DELETE FROM agent_runs WHERE vehicle_id = %s", (TEST_VEHICLE,))


@pytest.fixture
def run_id() -> Iterator[int]:
    apply_migrations(TEST_DATABASE_URL)
    _cleanup()
    journal = PgJournal(TEST_DATABASE_URL)
    run = journal.start_run(vehicle_id=TEST_VEHICLE, session_id="S-COST-1", lang="ru")
    journal.add_step(
        StepRecord(
            run_id=run,
            n=1,
            kind="llm",
            name="chat",
            ms=900,
            model=QWEN,
            prompt_tokens=100,
            completion_tokens=20,
            cost_rub=cost_rub(QWEN, 100, 20),
        )
    )
    journal.add_step(
        StepRecord(
            run_id=run,
            n=2,
            kind="embed",
            name="bge-m3",
            ms=80,
            model="bge-m3",
            prompt_tokens=42,
            cost_rub=cost_rub("bge-m3", 42, 0),
        )
    )
    journal.add_step(
        StepRecord(run_id=run, n=3, kind="rerank", name="bge-reranker", ms=30, model="bge-reranker")
    )
    journal.finish_run(
        run,
        RunSummary(
            status="ok",
            total_ms=1000,
            prompt_tokens=100,
            completion_tokens=20,
            cost_rub=cost_rub(QWEN, 100, 20) + cost_rub("bge-m3", 42, 0),
        ),
    )
    yield run
    _cleanup()


def test_steps_keep_their_price_and_run_shows_its_model(run_id: int) -> None:
    reader = PgJournalReader(TEST_DATABASE_URL)

    run = next(row for row in reader.list_runs(None, 50) if row.id == run_id)
    steps = reader.list_steps(run_id)

    assert run.model == QWEN
    assert run.cost_rub == cost_rub(QWEN, 100, 20) + cost_rub("bge-m3", 42, 0)
    assert [step.kind for step in steps] == ["llm", "embed", "rerank"]
    assert steps[0].cost_rub == cost_rub(QWEN, 100, 20)
    assert steps[1].cost_rub == cost_rub("bge-m3", 42, 0)
    assert steps[2].cost_rub is None


def test_old_steps_without_price_get_it_from_tokens_and_prices(run_id: int) -> None:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO agent_steps (run_id, n, kind, name, model, prompt_tokens, "
            "completion_tokens) VALUES (%s, 10, 'llm', 'chat', %s, 100, 20)",
            (run_id, QWEN),
        )
        conn.execute(
            "INSERT INTO agent_steps (run_id, n, kind, name, model, output) "
            "VALUES (%s, 11, 'stt', 'whisper-1', 'whisper-1', %s)",
            (run_id, Jsonb({"duration_s": 30.0})),
        )

    old = {step.n: step for step in PgJournalReader(TEST_DATABASE_URL).list_steps(run_id)}

    assert old[10].cost_rub == cost_rub(QWEN, 100, 20)
    assert old[11].cost_rub == Decimal("0.5000")


def test_period_summary_counts_priced_runs_and_costs_by_model(run_id: int) -> None:
    reader = PgJournalReader(TEST_DATABASE_URL)

    summary = reader.period_summary(datetime.now(UTC) - timedelta(hours=1))

    assert summary.runs >= 1
    assert summary.priced_runs >= 1
    qwen = next(model for model in summary.models if model.model == QWEN)
    assert qwen.calls >= 1
    assert qwen.cost_rub is not None and qwen.cost_rub >= cost_rub(QWEN, 100, 20)
    rerank = next(model for model in summary.models if model.model == "bge-reranker")
    assert rerank.cost_rub is None


def test_period_summary_for_future_start_is_empty(run_id: int) -> None:
    reader = PgJournalReader(TEST_DATABASE_URL)

    summary = reader.period_summary(datetime(2100, 1, 1, tzinfo=UTC))

    assert summary.runs == 0
    assert summary.cost_rub is None
    assert summary.models == []
