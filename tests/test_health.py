"""Страницы и /health: без авторизации, без 500 при недоступных сервисах, режим MOUNT_MOCKS."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.clients.ml_client import MlClient
from app.config import Settings
from app.main import create_app
from tests.helpers import STUB_BASE, VEHICLES_PATH, FailingHttp


def test_health_reports_services_ok_with_stubs(app_with_stubs: FastAPI) -> None:
    response = TestClient(app_with_stubs).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["services"] == {
        "app": "ok",
        "mock_ml": "ok",
        "mock_toir": "ok",
        "database": "not_configured",
    }


def test_health_is_degraded_not_500_when_ml_down(app_with_stubs: FastAPI) -> None:
    app_with_stubs.state.ml_client = MlClient(STUB_BASE, http=FailingHttp())  # type: ignore[arg-type]
    response = TestClient(app_with_stubs).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"]["mock_ml"] == "unavailable"
    assert body["services"]["mock_toir"] == "ok"


def test_index_is_russian_stub(app_with_stubs: FastAPI) -> None:
    response = TestClient(app_with_stubs).get("/")
    assert response.status_code == 200
    assert "Цифровой механик" in response.text
    assert 'lang="ru"' in response.text


def test_database_status_when_url_is_set(app_with_stubs: FastAPI) -> None:
    app_with_stubs.state.settings = Settings(
        vehicles_path=VEHICLES_PATH, database_url="postgresql://user:pass@host/db"
    )
    body = TestClient(app_with_stubs).get("/health").json()
    assert body["services"]["database"] == "not_checked"


def test_mount_mocks_serves_stubs_under_app() -> None:
    app = create_app(Settings(vehicles_path=VEHICLES_PATH, mount_mocks=True))
    client = TestClient(app)
    assert client.get("/mock/ml/health").json()["service"] == "mock-ml"
    assert client.get("/mock/toir/health").json()["service"] == "mock-toir"
