"""GET /ready: готовность к трафику. Без DATABASE_URL стенд готов (БД не настроена — не ошибка).

200 — БД не настроена или отвечает, миграции применены.
503 — БД настроена, но недоступна или миграции упали.
Заглушки ML и ТОиР в готовность не входят: при их сбое чат показывает понятный текст.
"""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.health import current_database_state
from app.db.database import DatabaseState

router = APIRouter()


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: DatabaseState


@router.get("/ready", response_model=ReadyResponse)
def ready(request: Request) -> JSONResponse:
    database = current_database_state(request)
    is_ready = database in ("ok", "not_configured")
    body = ReadyResponse(status="ready" if is_ready else "not_ready", database=database)
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content=body.model_dump(),
    )
