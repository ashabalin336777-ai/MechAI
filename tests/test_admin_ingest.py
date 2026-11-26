"""Временный POST /admin/ingest и GET /admin/ingest/status: Bearer, 409, 503, статус, секреты."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.api import admin_ingest
from app.config import Settings
from app.main import create_app
from app.rag.ingest import IngestJob

TOKEN = "admin-token-for-ingest-tests-7"
DB_URL = "postgresql://user:secret-pass@db.example:5432/mechai?sslmode=require"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _no_real_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Статус не ходит в сеть: по умолчанию в БД пусто. Тесты БД подменяют функцию сами."""
    monkeypatch.setattr(admin_ingest, "manuals_in_db", lambda url: [])


def _client(token: str, database_url: str = "") -> TestClient:
    settings = Settings(admin_token=token, database_url=database_url, mount_mocks=False)
    return TestClient(create_app(settings))


def _wait_done(client: TestClient) -> dict:
    deadline = time.monotonic() + 5
    body = client.get("/admin/ingest/status", headers=HEADERS).json()
    while body["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
        body = client.get("/admin/ingest/status", headers=HEADERS).json()
    return body


def test_endpoints_are_absent_without_admin_token() -> None:
    client = _client(token="")
    assert client.post("/admin/ingest").status_code == 404
    assert client.get("/admin/ingest/status").status_code == 404


def test_wrong_or_missing_bearer_is_rejected() -> None:
    client = _client(TOKEN)
    assert (
        client.post("/admin/ingest", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )
    assert client.get("/admin/ingest/status", headers={"Authorization": TOKEN}).status_code == 401
    assert client.get("/admin/ingest/status").status_code == 401


def test_missing_database_is_reported_in_russian() -> None:
    response = _client(TOKEN).post("/admin/ingest", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"] == "База данных не настроена"


def test_start_returns_202_then_status_shows_report() -> None:
    client = _client(TOKEN, database_url=DB_URL)
    client.app.state.ingest_job = IngestJob(runner=lambda settings: "# отчёт\n")
    assert client.post("/admin/ingest", headers=HEADERS).status_code == 202

    body = _wait_done(client)
    assert body["state"] == "done"
    assert body["error"] is None
    assert body["report"] == "# отчёт\n"


def test_second_start_while_running_is_conflict() -> None:
    client = _client(TOKEN, database_url=DB_URL)
    release = threading.Event()
    client.app.state.ingest_job = IngestJob(runner=lambda settings: release.wait(5) and "")
    assert client.post("/admin/ingest", headers=HEADERS).status_code == 202
    second = client.post("/admin/ingest", headers=HEADERS)
    release.set()
    assert second.status_code == 409
    assert second.json()["detail"] == "Индексация уже идёт"


def test_runner_error_is_visible_and_secrets_are_removed() -> None:
    def failing(settings: Settings) -> str:
        raise RuntimeError(f"сбой: {settings.database_url} и ключ {settings.neuraldeep_api_key}")

    settings = Settings(
        admin_token=TOKEN,
        database_url=DB_URL,
        neuraldeep_api_key="sk-test-key-123456",
        mount_mocks=False,
    )
    client = TestClient(create_app(settings))
    client.app.state.ingest_job = IngestJob(runner=failing)
    client.post("/admin/ingest", headers=HEADERS)

    body = _wait_done(client)
    assert body["state"] == "error"
    assert body["error"].startswith("RuntimeError: сбой:")
    assert "secret-pass" not in body["error"]
    assert "sk-test-key-123456" not in body["error"]


def test_status_lists_chunker_version_and_chunks_per_manual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"id": "yamz236_re", "chunker_version": 1, "chunks": 169},
        {"id": "yamz536_rk", "chunker_version": 3, "chunks": 602},
    ]
    monkeypatch.setattr(admin_ingest, "manuals_in_db", lambda url: rows)
    body = _client(TOKEN, database_url=DB_URL).get("/admin/ingest/status", headers=HEADERS).json()
    assert body["manuals"] == rows
    assert body["manuals_error"] is None
    assert body["chunker_version_expected"] == 3


def test_status_without_database_has_no_manuals_and_no_secrets() -> None:
    body = _client(TOKEN).get("/admin/ingest/status", headers=HEADERS).json()
    assert body["manuals"] is None
    assert body["state"] == "idle"


def test_status_reports_database_error_without_connection_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    def unavailable(url: str) -> list[dict]:
        raise psycopg.OperationalError("нет соединения")

    monkeypatch.setattr(admin_ingest, "manuals_in_db", unavailable)
    body = _client(TOKEN, database_url=DB_URL).get("/admin/ingest/status", headers=HEADERS).json()
    assert body["manuals"] is None
    assert body["manuals_error"] == "База данных недоступна"
    assert "secret-pass" not in str(body)
