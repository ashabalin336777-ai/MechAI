"""Подтверждение заявки механиком: POST /api/tickets/confirm (ТЗ §6.4 п.3, §5.2).

Создание заявки только здесь, по одноразовому confirm_token. Модель до этого не доходит.
Ответы: 201 — заявка создана сейчас; 200 — заявка уже была (повтор, вторую не создаём);
403 — токен не совпадает; 404 — черновика нет; 409 — состав изменился или отправка уже идёт;
422 — ТОиР отклонил данные; 503 — ТОиР или база недоступны. Текст ошибок понятен механику.
"""

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.tools.create_ticket import ConfirmError, confirm_draft

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


class ConfirmBody(BaseModel):
    draft_id: str = Field(min_length=1, max_length=64)
    confirm_token: str = Field(min_length=1, max_length=128)


class ConfirmResponse(BaseModel):
    ticket_id: str
    status: str


@router.post("/confirm", response_model=ConfirmResponse, status_code=201)
def confirm(body: ConfirmBody, request: Request, response: Response) -> ConfirmResponse:
    services = request.app.state.agent
    try:
        result = confirm_draft(
            services.deps.store, services.deps.toir, body.draft_id, body.confirm_token
        )
    except ConfirmError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="База данных недоступна, повторите.") from exc
    if not result.created:
        response.status_code = 200
    return ConfirmResponse(ticket_id=result.ticket_id, status="created")
