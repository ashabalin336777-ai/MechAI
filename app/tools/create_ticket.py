"""Отправка заявки в ТОиР по подтверждению механика (ТЗ §6.2, §6.4 п.3).

Одноразовый confirm_token сверяется с хэшем. Повтор подтверждения не создаёт вторую заявку:
после успеха черновик помечен номером заявки и возвращается тот же ticket_id.
Модель этот инструмент не вызывает сама: токена у неё нет, поэтому вызов отклоняется.
"""

import hmac

from pydantic import BaseModel, Field

from app.clients.errors import ClientError, NotFound, Unavailable, ValidationFailed
from app.clients.toir_client import TicketRequest, ToirClient
from app.db.agent_store import AgentStore
from app.tools.runtime import Runtime, content_hash, token_digest

NAME = "create_ticket"
DESCRIPTION = (
    "Отправить черновик заявки в ТОиР. Вызывается только интерфейсом после подтверждения "
    "механиком. "
    "Сам не вызывай и не придумывай токен."
)


class Args(BaseModel):
    draft_id: str = Field(min_length=1)
    confirm_token: str = Field(min_length=1)


class ConfirmResult(BaseModel):
    ticket_id: str
    created: bool


class ConfirmError(Exception):
    """Подтверждение отклонено. status — код HTTP для интерфейса, message — текст механику."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


_STATUS_BY_ERROR: dict[type[ClientError], int] = {
    NotFound: 404,
    ValidationFailed: 422,
    Unavailable: 503,
}


def confirm_draft(store: AgentStore, toir: ToirClient, draft_id: str, token: str) -> ConfirmResult:
    draft = store.get_draft(draft_id)
    if draft is None:
        raise ConfirmError(404, "Черновик не найден. Сформируйте заявку заново.")
    if not hmac.compare_digest(token_digest(token), draft.token_hash):
        raise ConfirmError(403, "Подтверждение не совпадает с черновиком.")
    if draft.ticket_id:
        return ConfirmResult(ticket_id=draft.ticket_id, created=False)
    if content_hash(draft.payload) != draft.draft_hash:
        raise ConfirmError(409, "Состав заявки изменился после формирования черновика.")
    if not store.claim_draft(draft_id):
        again = store.get_draft(draft_id)
        if again is not None and again.ticket_id:
            return ConfirmResult(ticket_id=again.ticket_id, created=False)
        raise ConfirmError(409, "Заявка уже отправляется. Обновите страницу.")
    try:
        response = toir.create_ticket(TicketRequest.model_validate(draft.payload))
    except ClientError as exc:
        store.release_draft(draft_id)
        status = _STATUS_BY_ERROR.get(type(exc), 503)
        raise ConfirmError(status, exc.user_message) from exc
    store.complete_draft(draft_id, response.ticket_id)
    return ConfirmResult(ticket_id=response.ticket_id, created=True)


def run(rt: Runtime, args: Args) -> dict:
    """Вызов моделью: без правильного токена отказ, заявку не создаём."""
    try:
        result = confirm_draft(rt.deps.store, rt.deps.toir, args.draft_id, args.confirm_token)
    except ConfirmError as exc:
        return {"ok": False, "error": exc.message}
    return {"ok": True, "ticket_id": result.ticket_id, "created": result.created}
