"""GET /health: без авторизации. Статусы сервисов в теле, ответ всегда 200 (деградация без 500).

Живость процесса — здесь. Готовность к трафику — в /ready (503 при сбое БД).
"""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.db.database import DatabaseState, check_database

router = APIRouter()


class ServicesHealth(BaseModel):
    app: Literal["ok"]
    mock_ml: Literal["ok", "unavailable"]
    mock_toir: Literal["ok", "unavailable"]
    database: DatabaseState


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    git_sha: str
    services: ServicesHealth


def current_database_state(request: Request) -> DatabaseState:
    """иивая проверка БД. Если миграции упали при старте, это важнее доступности."""
    state = request.app.state
    if state.migration_failed:
        return "migration_failed"
    return check_database(state.settings.database_url)


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    state = request.app.state
    ml_ok = state.ml_client.health()
    toir_ok = state.toir_client.health()
    services = ServicesHealth(
        app="ok",
        mock_ml="ok" if ml_ok else "unavailable",
        mock_toir="ok" if toir_ok else "unavailable",
        database=current_database_state(request),
    )
    all_ok = ml_ok and toir_ok and services.database in ("ok", "not_configured")
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        git_sha=state.settings.git_sha or "unknown",
        services=services,
    )
