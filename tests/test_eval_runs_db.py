"""eval_runs против настоящего PostgreSQL: создание, статус, чтение после «перезапуска».

Запускаются, если задан TEST_DATABASE_URL. Фикстура очищает схему public, поэтому нужен
TEST_DATABASE_ALLOW_RESET=1 (как в tests/test_migrations.py):
    $env:TEST_DATABASE_URL="postgresql://mechai:...@127.0.0.1:5433/mechai"
    $env:TEST_DATABASE_ALLOW_RESET="1"; pytest tests/test_eval_runs_db.py
"""

import os

import psycopg
import pytest

from app.db.database import apply_migrations
from app.db.eval_runs import (
    ERROR_LIMIT,
    STALE_MESSAGE,
    EvalCase,
    EvalResult,
    PgEvalRunStore,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
ALLOW_RESET = os.environ.get("TEST_DATABASE_ALLOW_RESET") == "1"

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="нужен TEST_DATABASE_URL (PostgreSQL с pgvector)"
)

RESULT = EvalResult(
    report_md="# отчёт по руководствам\n",
    passed=1,
    total=2,
    cases=[EvalCase(id="Q01", passed=True, note="hit@5: да"), EvalCase(id="Q02", passed=False)],
)


@pytest.fixture()
def store() -> PgEvalRunStore:
    if not ALLOW_RESET:
        pytest.skip("задайте TEST_DATABASE_ALLOW_RESET=1: тест очищает схему public тестовой БД")
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    status = apply_migrations(TEST_DATABASE_URL)
    assert status.state == "ok"
    return PgEvalRunStore(TEST_DATABASE_URL)


def test_create_run_writes_running_row(store: PgEvalRunStore) -> None:
    run_id = store.create_run("rag", "6dc4c25")
    assert run_id is not None
    record = store.get_run(run_id)
    assert record is not None
    assert record.status == "running"
    assert record.suite == "rag"
    assert record.commit_sha == "6dc4c25"
    assert record.finished_at is None
    assert record.report_md is None


def test_second_run_is_refused_while_first_is_running(store: PgEvalRunStore) -> None:
    assert store.create_run("rag", None) is not None
    assert store.create_run("agent", None) is None


def test_finish_updates_status_summary_and_report(store: PgEvalRunStore) -> None:
    run_id = store.create_run("rag", None)
    assert run_id is not None
    store.finish_run(run_id, RESULT)
    record = store.get_run(run_id)
    assert record is not None
    assert record.status == "done"
    assert record.finished_at is not None
    assert (record.passed, record.total) == (1, 2)
    assert record.report_md == "# отчёт по руководствам\n"
    assert record.report_json == {
        "passed": 1,
        "total": 2,
        "cases": [
            {"id": "Q01", "passed": True, "note": "hit@5: да"},
            {"id": "Q02", "passed": False, "note": ""},
        ],
    }
    assert store.create_run("rag", None) is not None  # занятость снята


def test_fail_stores_truncated_message(store: PgEvalRunStore) -> None:
    run_id = store.create_run("agent", None)
    assert run_id is not None
    store.fail_run(run_id, "Ошибка прогона: " + "x" * 500)
    record = store.get_run(run_id)
    assert record is not None
    assert record.status == "error"
    assert record.error_message is not None
    assert len(record.error_message) == ERROR_LIMIT
    assert record.report_md is None


def test_result_survives_restart_with_new_store_and_connections(store: PgEvalRunStore) -> None:
    run_id = store.create_run("rag", "6dc4c25")
    assert run_id is not None
    store.finish_run(run_id, RESULT)
    restarted = PgEvalRunStore(TEST_DATABASE_URL)  # новый объект и новые соединения
    record = restarted.get_run(run_id)
    assert record is not None
    assert record.status == "done"
    assert record.report_md == "# отчёт по руководствам\n"
    latest = restarted.latest_run()
    assert latest is not None and latest.id == run_id


def test_list_runs_returns_newest_without_report_text(store: PgEvalRunStore) -> None:
    first = store.create_run("rag", None)
    assert first is not None
    store.finish_run(first, RESULT)
    second = store.create_run("agent", None)
    assert second is not None
    store.finish_run(second, RESULT)
    runs = store.list_runs(limit=10)
    assert [run.id for run in runs] == [second, first]
    assert all(run.report_md is None for run in runs)
    assert runs[0].report_json is not None
    assert len(store.list_runs(limit=1)) == 1


def test_stale_running_row_is_closed_and_does_not_block(store: PgEvalRunStore) -> None:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        row = conn.execute(
            "INSERT INTO eval_runs (suite, status, started_at) "
            "VALUES ('rag', 'running', now() - interval '2 hours') RETURNING id"
        ).fetchone()
    assert row is not None
    stale_id = int(row[0])
    new_id = store.create_run("rag", None)
    assert new_id is not None
    stale = store.get_run(stale_id)
    assert stale is not None
    assert stale.status == "error"
    assert stale.error_message == STALE_MESSAGE


def test_other_tenant_rows_are_invisible(store: PgEvalRunStore) -> None:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('other', 'Чужой парк')")
        conn.execute(
            "INSERT INTO eval_runs (tenant_id, suite, status) VALUES ('other', 'rag', 'done')"
        )
    assert store.latest_run() is None
    assert store.list_runs(limit=10) == []
