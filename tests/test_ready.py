"""/ready: без БД стенд отвечает готовностью; при сбое БД — 503; /health не падает."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.helpers import VEHICLES_PATH

UNREACHABLE_DB = "postgresql://user:secret@127.0.0.1:1/db"


def test_ready_without_database_is_200(app_with_stubs: FastAPI) -> None:
    response = TestClient(app_with_stubs).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "not_configured"}


def test_ready_with_unreachable_database_is_503(app_with_stubs: FastAPI) -> None:
    app_with_stubs.state.settings = Settings(
        vehicles_path=VEHICLES_PATH, database_url=UNREACHABLE_DB
    )
    response = TestClient(app_with_stubs).get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}


def test_ready_reports_failed_migrations_as_503(app_with_stubs: FastAPI) -> None:
    app_with_stubs.state.settings = Settings(
        vehicles_path=VEHICLES_PATH, database_url=UNREACHABLE_DB
    )
    app_with_stubs.state.migration_failed = True
    response = TestClient(app_with_stubs).get("/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "migration_failed"


def test_health_with_unreachable_database_is_200_degraded(app_with_stubs: FastAPI) -> None:
    app_with_stubs.state.settings = Settings(
        vehicles_path=VEHICLES_PATH, database_url=UNREACHABLE_DB
    )
    response = TestClient(app_with_stubs).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"]["database"] == "unavailable"


def test_lifespan_without_database_starts_and_serves() -> None:
    app = create_app(Settings(vehicles_path=VEHICLES_PATH))
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
