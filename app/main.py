"""Точка входа FastAPI: страницы, healthcheck, клиенты заглушек, парк ТС, запасной режим."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.health import router as health_router
from app.api.pages import router as pages_router
from app.clients.ml_client import MlClient
from app.clients.toir_client import ToirClient
from app.config import Settings, get_settings
from app.data.vehicles import VehicleStore
from app.mocks import mount_mocks
from app.paths import STATIC_DIR


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Цифровой механик", version="0.2.0")
    app.state.settings = settings
    app.state.ml_client = MlClient(settings.mock_ml_url)
    app.state.toir_client = ToirClient(settings.mock_toir_url)
    app.state.vehicles = VehicleStore.load(settings.vehicles_path)
    if settings.mount_mocks:
        mount_mocks(app)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(health_router)
    app.include_router(pages_router)
    return app


app = create_app()
