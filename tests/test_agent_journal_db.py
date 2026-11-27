"""Журнал агента в PostgreSQL: PgJournalReader читает ходы и шаги, сессия только для чтения.

Запускается, если задан TEST_DATABASE_URL. Тестовые строки помечены
vehicle_id TEST-LOGS и удаляются.
"""

import os
from collections.abc import Iterator

import psycopg
import pytest

from app.db.agent_journal import PgJournalReader
from app.db.database import apply_migrations
from app.obs.journal import PgJournal, RunSummary, StepRecord

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="нужен TEST_DATABASE_URL")
TEST_VEHICLE = "TEST-LOGS"


def _cleanup() -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute("DELETE FROM agent_runs WHERE vehicle_id = %s", (TEST_VEHICLE,))


@pytest.fixture
def run_id() -> Iterator[int]:
    apply_migrations(TEST_DATABASE_URL)
    _cleanup()
    journal = PgJournal(TEST_DATABASE_URL)
    run = journal.start_run(vehicle_id=TEST_VEHICLE, session_id="S-TEST-1", lang="ru")
    journal.add_step(
        StepRecord(run_id=run, n=1, kind="tool", name="get_vehicle", ms=5, output={"ok": True})
    )
    journal.add_step(
        StepRecord(
            run_id=run,
            n=2,
            kind="error",
            name="chat",
            error="timeout",
            error_class="TimeoutError",
            error_message="таймаут ответа модели",
        )
    )
    journal.finish_run(run, RunSummary(status="error", total_ms=120))
    try:
        yield run
    finally:
        _cleanup()


def test_list_runs_filters_by_status(run_id: int) -> None:
    reader = PgJournalReader(TEST_DATABASE_URL)
    errors = {row.id for row in reader.list_runs("error", 500)}
    oks = {row.id for row in reader.list_runs("ok", 500)}
    assert run_id in errors
    assert run_id not in oks


def test_get_run_and_steps_in_order(run_id: int) -> None:
    reader = PgJournalReader(TEST_DATABASE_URL)
    run = reader.get_run(run_id)
    assert run is not None
    assert run.vehicle_id == TEST_VEHICLE and run.status == "error" and run.total_ms == 120
    steps = reader.list_steps(run_id)
    assert [step.name for step in steps] == ["get_vehicle", "chat"]
    assert steps[0].output == {"ok": True}
    assert steps[1].error_class == "TimeoutError"
    assert steps[1].error_message == "таймаут ответа модели"


def test_reader_session_cannot_write(run_id: int) -> None:
    reader = PgJournalReader(TEST_DATABASE_URL)
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with reader._connect() as conn:
            conn.execute("DELETE FROM agent_runs WHERE id = %s", (run_id,))
