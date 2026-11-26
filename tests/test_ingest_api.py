"""Временный эндпоинт индексации: токен, 404 без токена, 409 при параллельном запуске, статус."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.rag.ingest import IngestJob

TOKEN = "test-ingest-token-123"
DB_URL = "postgresql://user:secret@db.example:5432/mechai"


def _client(token: str, database_url: str = DB_URL) -> TestClient:
    app = create_app(Settings(ingest_token=token, database_url=database_url, mount_mocks=False))
    return TestClient(app)


def test_endpoint_is_absent_without_token_configured() -> None:
    client = _client(token="")
    assert client.post("/admin/ingest").status_code == 404
    assert client.get("/admin/ingest/status").status_code == 404


def test_wrong_token_is_rejected() -> None:
    client = _client(TOKEN)
    response = client.post("/admin/ingest", headers={"X-Ingest-Token": "wrong"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Неверный токен"
    assert client.get("/admin/ingest/status").status_code == 401


def test_missing_database_is_reported_in_russian() -> None:
    client = _client(TOKEN, database_url="")
    response = client.post("/admin/ingest", headers={"X-Ingest-Token": TOKEN})
    assert response.status_code == 503
    assert response.json()["detail"] == "База данных не настроена"


def test_start_then_status_with_fake_runner() -> None:
    client = _client(TOKEN)
    client.app.state.ingest_job = IngestJob(runner=lambda settings: "# отчёт\n")
    headers = {"X-Ingest-Token": TOKEN}

    started = client.post("/admin/ingest", headers=headers)
    assert started.status_code == 202

    deadline = time.monotonic() + 5
    body = client.get("/admin/ingest/status", headers=headers).json()
    while body["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
        body = client.get("/admin/ingest/status", headers=headers).json()
    assert body == {"state": "done", "error": None, "report": "# отчёт\n"}


def test_second_start_while_running_is_conflict() -> None:
    client = _client(TOKEN)
    release = threading.Event()
    client.app.state.ingest_job = IngestJob(runner=lambda settings: release.wait(5) and "")
    headers = {"X-Ingest-Token": TOKEN}

    assert client.post("/admin/ingest", headers=headers).status_code == 202
    second = client.post("/admin/ingest", headers=headers)
    release.set()
    assert second.status_code == 409


def test_runner_error_is_visible_in_status_without_secrets() -> None:
    def failing(settings: Settings) -> str:
        raise RuntimeError("сбой эмбеддингов")

    client = _client(TOKEN)
    client.app.state.ingest_job = IngestJob(runner=failing)
    headers = {"X-Ingest-Token": TOKEN}
    client.post("/admin/ingest", headers=headers)

    deadline = time.monotonic() + 5
    body = client.get("/admin/ingest/status", headers=headers).json()
    while body["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
        body = client.get("/admin/ingest/status", headers=headers).json()
    assert body["state"] == "error"
    assert "RuntimeError" in body["error"]
    assert "secret" not in body["error"]


@pytest.mark.parametrize("header", ["X-Ingest-Token", "x-ingest-token"])
def test_header_name_is_case_insensitive(header: str) -> None:
    client = _client(TOKEN)
    response = client.get("/admin/ingest/status", headers={header: TOKEN})
    assert response.status_code == 200
