"""Точка входа FastAPI: страницы, health и ready, клиенты заглушек, парк ТС, агент, миграции."""

import logging
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.agent.runner import load_base_prompt
from app.agent.services import build_agent_services, use_postgres_checkpointer
from app.api.admin_eval import EvalJob
from app.api.admin_eval import router as admin_eval_router
from app.api.admin_json import use_admin_json_charset
from app.api.admin_logs import router as admin_logs_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.pages import router as pages_router
from app.api.ready import router as ready_router
from app.api.stt import router as stt_router
from app.api.tickets import router as tickets_router
from app.clients.ml_client import MlClient
from app.clients.stt_client import SttClient
from app.clients.toir_client import ToirClient
from app.config import Settings, get_settings
from app.data.vehicles import VehicleStore
from app.db.agent_journal import PgJournalReader
from app.db.database import apply_migrations
from app.db.eval_runs import PgEvalRunStore
from app.materials import ensure_runtime_materials
from app.mocks import mount_mocks
from app.paths import STATIC_DIR
from app.rag.manifest import Manifest, load_manifest

logger = logging.getLogger("app")
# PWA: браузеры ждут манифест с типом application/manifest+json.
mimetypes.add_type("application/manifest+json", ".webmanifest")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Миграции при старте. Если БД недоступна, приложение стартует, а /ready вернёт 503."""
    settings: Settings = app.state.settings
    if settings.database_url:
        result = apply_migrations(settings.database_url)
        app.state.migration_failed = result.state == "migration_failed"
        logger.info("миграции: состояние %s, применено %d", result.state, result.migrations_applied)
        if result.state == "ok":
            use_postgres_checkpointer(app.state.agent, settings.database_url)
    yield


def _load_vehicles(path: Path) -> VehicleStore:
    """Парк из файла. Нет файла или он не читается — пустой парк, приложение стартует."""
    try:
        return VehicleStore.load(path)
    except (OSError, ValueError, KeyError) as exc:
        logger.error("парк ТС не загружен из %s: %s", path, type(exc).__name__)
        return VehicleStore([])


def _load_manifest(settings: Settings) -> Manifest:
    path = settings.manuals_dir / "manifest.yaml"
    if not path.exists():
        logger.warning("манифест руководств не найден: %s", path)
        return Manifest(manuals=[])
    return load_manifest(path)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Цифровой механик", version="0.2.0", lifespan=lifespan)
    use_admin_json_charset(app)
    app.state.settings = settings
    app.state.migration_failed = False
    app.state.eval_store = PgEvalRunStore(settings.database_url)
    app.state.eval_job = EvalJob(app.state.eval_store)
    app.state.journal_reader = (
        PgJournalReader(settings.database_url) if settings.database_url else None
    )
    app.state.ml_client = MlClient(settings.mock_ml_url)
    app.state.toir_client = ToirClient(settings.mock_toir_url)
    app.state.stt_client = SttClient(
        settings.neuraldeep_api_key, settings.neuraldeep_base_url, settings.stt_model
    )
    app.state.materials = ensure_runtime_materials(
        settings.vehicles_path,
        settings.fault_types_path,
        settings.mock_data_base_url,
        settings.mock_archive_name,
    )
    app.state.vehicles = _load_vehicles(settings.vehicles_path)
    app.state.manifest = _load_manifest(settings)
    app.state.agent = build_agent_services(
        settings, app.state.vehicles, app.state.manifest, app.state.ml_client, app.state.toir_client
    )
    app.state.agent_prompt = load_base_prompt()
    if settings.mount_mocks:
        mount_mocks(app)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(health_router)
    app.include_router(ready_router)
    app.include_router(pages_router)
    app.include_router(admin_eval_router)
    app.include_router(admin_logs_router)
    app.include_router(chat_router)
    app.include_router(stt_router)
    app.include_router(tickets_router)
    return app


app = create_app()
