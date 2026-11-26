"""POST /admin/eval (202), GET /admin/eval/status и /runs: 404, Bearer, 409, статусы, секреты.

Здесь хранилище в памяти с тем же контрактом, что PgEvalRunStore. Настоящий SQL проверяется
в tests/test_eval_runs_db.py (нужен TEST_DATABASE_URL).
"""

import threading
import time
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api import admin_eval
from app.api.admin_eval import EvalJob
from app.config import Settings
from app.db.eval_runs import EvalCase, EvalResult, EvalRunRecord
from app.main import create_app
from app.rag.embeddings import EmbeddingError

TOKEN = "admin-token-for-tests-42"
DB_URL = "postgresql://user:secret@db.example:5432/mechai"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
RESULT = EvalResult(
    report_md="# отчёт\n",
    passed=2,
    total=3,
    cases=[EvalCase(id="Q01", passed=True), EvalCase(id="Q02", passed=False, note="нет hit")],
)


class MemoryEvalRunStore:
    def __init__(self) -> None:
        self.rows: dict[int, EvalRunRecord] = {}
        self.fail_create = False
        self._lock = threading.Lock()

    def create_run(self, suite: str, commit_sha: str | None) -> int | None:
        if self.fail_create:
            raise psycopg.OperationalError("connection refused")
        with self._lock:
            if any(row.status == "running" for row in self.rows.values()):
                return None
            run_id = len(self.rows) + 1
            self.rows[run_id] = EvalRunRecord(
                id=run_id,
                suite=suite,
                commit_sha=commit_sha,
                status="running",
                started_at=datetime.now(UTC),
                finished_at=None,
                passed=None,
                total=None,
                error_message=None,
            )
            return run_id

    def finish_run(self, run_id: int, result: EvalResult) -> None:
        self.rows[run_id] = self.rows[run_id].model_copy(
            update={
                "status": "done",
                "finished_at": datetime.now(UTC),
                "passed": result.passed,
                "total": result.total,
                "report_md": result.report_md,
                "report_json": result.summary(),
            }
        )

    def fail_run(self, run_id: int, message: str) -> None:
        self.rows[run_id] = self.rows[run_id].model_copy(
            update={"status": "error", "finished_at": datetime.now(UTC), "error_message": message}
        )

    def get_run(self, run_id: int) -> EvalRunRecord | None:
        return self.rows.get(run_id)

    def latest_run(self) -> EvalRunRecord | None:
        return self.rows[max(self.rows)] if self.rows else None

    def list_runs(self, limit: int) -> list[EvalRunRecord]:
        newest = sorted(self.rows, reverse=True)[:limit]
        return [self.rows[run_id].model_copy(update={"report_md": None}) for run_id in newest]


def _client(token: str = TOKEN, database_url: str = DB_URL) -> TestClient:
    app = create_app(
        Settings(
            admin_token=token,
            database_url=database_url,
            mount_mocks=False,
            commit_sha="6dc4c25",
        )
    )
    store = MemoryEvalRunStore()
    app.state.eval_store = store
    app.state.eval_job = EvalJob(store)
    return TestClient(app)


def _store(client: TestClient) -> MemoryEvalRunStore:
    return client.app.state.eval_store


def _wait_done(client: TestClient, timeout_s: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        body = client.get("/admin/eval/status", headers=AUTH).json()
        if body["status"] != "running" or time.monotonic() > deadline:
            return body
        time.sleep(0.01)


def test_endpoints_are_absent_without_admin_token() -> None:
    client = _client(token="")
    assert client.post("/admin/eval").status_code == 404
    assert client.get("/admin/eval/status").status_code == 404
    assert client.get("/admin/eval/runs").status_code == 404


@pytest.mark.parametrize(
    "header",
    [None, "", "Basic " + TOKEN, "Bearer wrong-token", "Bearer " + TOKEN[:-1]],
)
def test_wrong_or_missing_bearer_is_rejected(header: str | None) -> None:
    client = _client()
    headers = {} if header is None else {"Authorization": header}
    response = client.post("/admin/eval", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Неверный токен"
    assert client.get("/admin/eval/status", headers=headers).status_code == 401
    assert client.get("/admin/eval/runs", headers=headers).status_code == 401


def test_missing_database_is_reported_in_russian() -> None:
    response = _client(database_url="").post("/admin/eval", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["detail"] == "База данных не настроена"


def test_post_returns_202_with_run_id_and_status_keeps_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_eval, "run_eval_result", lambda settings: RESULT)
    client = _client()
    response = client.post("/admin/eval", headers=AUTH)
    assert response.status_code == 202
    assert response.json() == {"status": "started", "suite": "rag", "run_id": 1}
    body = _wait_done(client)
    assert body["id"] == 1
    assert body["status"] == "done"
    assert body["suite"] == "rag"
    assert body["commit_sha"] == "6dc4c25"
    assert body["passed"] == 2 and body["total"] == 3
    assert body["report_md"] == "# отчёт\n"
    assert body["report_json"]["cases"][1] == {"id": "Q02", "passed": False, "note": "нет hit"}
    assert body["error_message"] is None
    assert body["started_at"] and body["finished_at"]


def test_status_by_run_id_and_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_eval, "run_eval_result", lambda settings: RESULT)
    client = _client()
    client.post("/admin/eval", headers=AUTH)
    _wait_done(client)
    client.post("/admin/eval", headers=AUTH)
    _wait_done(client)
    latest = client.get("/admin/eval/status", headers=AUTH).json()
    first = client.get("/admin/eval/status?run_id=1", headers=AUTH).json()
    assert latest["id"] == 2
    assert first["id"] == 1


def test_status_when_nothing_ran_is_404() -> None:
    client = _client()
    response = client.get("/admin/eval/status", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["detail"] == "Прогонов ещё не было"


def test_unknown_run_id_is_404() -> None:
    response = _client().get("/admin/eval/status?run_id=999", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["detail"] == "Прогон не найден"


def test_runs_list_has_no_report_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_eval, "run_eval_result", lambda settings: RESULT)
    client = _client()
    client.post("/admin/eval", headers=AUTH)
    _wait_done(client)
    client.post("/admin/eval", headers=AUTH)
    _wait_done(client)
    runs = client.get("/admin/eval/runs?limit=10", headers=AUTH).json()["runs"]
    assert [run["id"] for run in runs] == [2, 1]
    assert all("report_md" not in run for run in runs)
    assert runs[0]["passed"] == 2 and runs[0]["status"] == "done"


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=abc"])
def test_runs_limit_is_validated(query: str) -> None:
    assert _client().get(f"/admin/eval/runs?{query}", headers=AUTH).status_code == 422


def test_model_outage_is_visible_in_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(settings: Settings) -> EvalResult:
        raise EmbeddingError("эмбеддинги недоступны: APIConnectionError")

    monkeypatch.setattr(admin_eval, "run_eval_result", failing)
    client = _client()
    assert client.post("/admin/eval", headers=AUTH).status_code == 202
    body = _wait_done(client)
    assert body["status"] == "error"
    assert body["report_md"] is None
    assert body["error_message"].startswith("Модели недоступны")


def test_database_outage_during_run_is_visible_in_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(settings: Settings) -> EvalResult:
        raise psycopg.OperationalError(f"could not connect to {DB_URL}")

    monkeypatch.setattr(admin_eval, "run_eval_result", failing)
    client = _client()
    client.post("/admin/eval", headers=AUTH)
    body = _wait_done(client)
    assert body["status"] == "error"
    assert body["error_message"] == "База данных недоступна"


def test_unexpected_error_hides_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(settings: Settings) -> EvalResult:
        raise RuntimeError(f"сбой с строкой {DB_URL}")

    monkeypatch.setattr(admin_eval, "run_eval_result", failing)
    client = _client()
    client.post("/admin/eval", headers=AUTH)
    body = _wait_done(client)
    assert body["status"] == "error"
    assert body["error_message"] == "Ошибка прогона: RuntimeError"
    assert DB_URL not in str(body)
    assert DB_URL not in client.get("/admin/eval/runs", headers=AUTH).text


def test_second_start_while_running_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()

    def slow(settings: Settings) -> EvalResult:
        gate.wait(5)
        return RESULT

    monkeypatch.setattr(admin_eval, "run_eval_result", slow)
    client = _client()
    try:
        assert client.post("/admin/eval", headers=AUTH).status_code == 202
        assert client.get("/admin/eval/status", headers=AUTH).json()["status"] == "running"
        second = client.post("/admin/eval", headers=AUTH)
        assert second.status_code == 409
        assert second.json()["detail"] == "Прогон уже идёт"
    finally:
        gate.set()
    assert _wait_done(client)["status"] == "done"


def test_database_error_on_start_is_503() -> None:
    client = _client()
    _store(client).fail_create = True
    response = client.post("/admin/eval", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["detail"] == "База данных недоступна"


def test_agent_suite_stores_agent_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_eval, "load_scenarios", lambda path: [])
    monkeypatch.setattr(
        admin_eval,
        "run_agent_result",
        lambda *args, **kwargs: EvalResult(report_md="# агент\n", passed=0, total=0),
    )
    client = _client()
    response = client.post("/admin/eval?suite=agent", headers=AUTH)
    assert response.json() == {"status": "started", "suite": "agent", "run_id": 1}
    body = _wait_done(client)
    assert body["status"] == "done"
    assert body["suite"] == "agent"
    assert body["report_md"] == "# агент\n"


def test_unknown_suite_is_422() -> None:
    response = _client().post("/admin/eval?suite=unknown", headers=AUTH)
    assert response.status_code == 422


def test_run_timestamps_are_utc_iso() -> None:
    store = MemoryEvalRunStore()
    run_id = store.create_run("rag", None)
    assert run_id == 1
    record = store.get_run(1)
    assert record is not None and record.started_at.tzinfo is not None


def test_admin_json_declares_utf8_on_success_and_errors() -> None:
    client = _client()
    utf8 = "application/json; charset=utf-8"

    listed = client.get("/admin/eval/runs", headers=AUTH)
    assert listed.status_code == 200
    assert listed.headers["content-type"] == utf8

    rejected = client.get("/admin/eval/status", headers={"Authorization": "Bearer wrong"})
    assert rejected.status_code == 401
    assert rejected.headers["content-type"] == utf8
    assert rejected.json()["detail"] == "Неверный токен"

    missing = client.get("/admin/eval/status", headers=AUTH)
    assert missing.status_code == 404
    assert missing.headers["content-type"] == utf8
