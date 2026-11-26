"""POST /admin/eval (202) и GET /admin/eval/status: 404, Bearer, 409, статусы ошибок."""

import threading
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api import admin_eval
from app.config import Settings
from app.main import create_app
from app.rag.embeddings import EmbeddingError

TOKEN = "admin-token-for-tests-42"
DB_URL = "postgresql://user:secret@db.example:5432/mechai"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _client(token: str, database_url: str = DB_URL) -> TestClient:
    return TestClient(
        create_app(Settings(admin_token=token, database_url=database_url, mount_mocks=False))
    )


def _wait_done(client: TestClient, timeout_s: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        body = client.get("/admin/eval/status", headers=AUTH).json()
        if body["state"] != "running" or time.monotonic() > deadline:
            return body
        time.sleep(0.01)


def test_endpoints_are_absent_without_admin_token() -> None:
    client = _client(token="")
    assert client.post("/admin/eval").status_code == 404
    assert client.get("/admin/eval/status").status_code == 404


@pytest.mark.parametrize(
    "header",
    [None, "", "Basic " + TOKEN, "Bearer wrong-token", "Bearer " + TOKEN[:-1]],
)
def test_wrong_or_missing_bearer_is_rejected(header: str | None) -> None:
    client = _client(TOKEN)
    headers = {} if header is None else {"Authorization": header}
    response = client.post("/admin/eval", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Неверный токен"
    status = client.get("/admin/eval/status", headers=headers)
    assert status.status_code == 401


def test_missing_database_is_reported_in_russian() -> None:
    response = _client(TOKEN, database_url="").post("/admin/eval", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["detail"] == "База данных не настроена"


def test_post_returns_202_and_status_keeps_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_eval, "run_eval_report", lambda settings: "# отчёт\n")
    client = _client(TOKEN)
    response = client.post("/admin/eval", headers=AUTH)
    assert response.status_code == 202
    assert response.json() == {"status": "started", "suite": "rag"}
    body = _wait_done(client)
    assert body["state"] == "done"
    assert body["suite"] == "rag"
    assert body["report"] == "# отчёт\n"
    assert body["error"] is None
    assert body["started_at"] and body["finished_at"]


def test_model_outage_is_visible_in_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(settings: Settings) -> str:
        raise EmbeddingError("эмбеддинги недоступны: APIConnectionError")

    monkeypatch.setattr(admin_eval, "run_eval_report", failing)
    client = _client(TOKEN)
    assert client.post("/admin/eval", headers=AUTH).status_code == 202
    body = _wait_done(client)
    assert body["state"] == "error"
    assert body["report"] is None
    assert body["error"].startswith("Модели недоступны")


def test_database_outage_is_visible_in_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(settings: Settings) -> str:
        raise psycopg.OperationalError(f"could not connect to {DB_URL}")

    monkeypatch.setattr(admin_eval, "run_eval_report", failing)
    client = _client(TOKEN)
    client.post("/admin/eval", headers=AUTH)
    body = _wait_done(client)
    assert body["state"] == "error"
    assert body["error"] == "База данных недоступна"


def test_unexpected_error_hides_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(settings: Settings) -> str:
        raise RuntimeError(f"сбой с строкой {DB_URL}")

    monkeypatch.setattr(admin_eval, "run_eval_report", failing)
    client = _client(TOKEN)
    client.post("/admin/eval", headers=AUTH)
    body = _wait_done(client)
    assert body["state"] == "error"
    assert body["error"] == "Ошибка прогона: RuntimeError"
    assert DB_URL not in str(body)


def test_second_start_while_running_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()

    def slow(settings: Settings) -> str:
        gate.wait(5)
        return "# отчёт\n"

    monkeypatch.setattr(admin_eval, "run_eval_report", slow)
    client = _client(TOKEN)
    try:
        assert client.post("/admin/eval", headers=AUTH).status_code == 202
        assert client.get("/admin/eval/status", headers=AUTH).json()["state"] == "running"
        second = client.post("/admin/eval", headers=AUTH)
        assert second.status_code == 409
        assert second.json()["detail"] == "Прогон уже идёт"
    finally:
        gate.set()
    assert _wait_done(client)["state"] == "done"


def test_agent_suite_returns_report_through_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_eval, "load_scenarios", lambda path: [])
    monkeypatch.setattr(admin_eval, "run_agent_report", lambda *args, **kwargs: "# агент\n")
    client = _client(TOKEN)
    response = client.post("/admin/eval?suite=agent", headers=AUTH)
    assert response.status_code == 202
    assert response.json() == {"status": "started", "suite": "agent"}
    body = _wait_done(client)
    assert body["state"] == "done"
    assert body["suite"] == "agent"
    assert body["report"] == "# агент\n"


def test_unknown_suite_is_422() -> None:
    response = _client(TOKEN).post("/admin/eval?suite=unknown", headers=AUTH)
    assert response.status_code == 422


def test_status_before_any_run_is_idle() -> None:
    body = _client(TOKEN).get("/admin/eval/status", headers=AUTH).json()
    assert body == {
        "state": "idle",
        "suite": None,
        "started_at": None,
        "finished_at": None,
        "error": None,
        "report": None,
    }
