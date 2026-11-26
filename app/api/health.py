"""GET /health: без авторизации. Сервисы проверяются, ответ всегда 200 (деградация без 500)."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class ServicesHealth(BaseModel):
    app: Literal["ok"]
    mock_ml: Literal["ok", "unavailable"]
    mock_toir: Literal["ok", "unavailable"]
    database: Literal["not_configured", "not_checked"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    services: ServicesHealth


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    state = request.app.state
    ml_ok = state.ml_client.health()
    toir_ok = state.toir_client.health()
    database = "not_configured" if not state.settings.database_url else "not_checked"
    services = ServicesHealth(
        app="ok",
        mock_ml="ok" if ml_ok else "unavailable",
        mock_toir="ok" if toir_ok else "unavailable",
        database=database,
    )
    all_ok = ml_ok and toir_ok
    return HealthResponse(status="ok" if all_ok else "degraded", services=services)
