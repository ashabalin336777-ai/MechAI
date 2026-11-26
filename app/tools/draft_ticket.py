"""Инструмент draft_ticket: черновик заявки ТОиР с проверками ticket_guard. Ничего не отправляет.

Черновик и одноразовый confirm_token создаются здесь. Токен уходит в интерфейс механика (событие
ticket_draft), модели он не передаётся. Отправка — только по подтверждению механика (create_ticket).
"""

import secrets
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.guards import check_ticket_draft
from app.agent.verdict import Verdict
from app.clients.toir_client import Reference, TicketRequest
from app.db.agent_store import DraftRecord
from app.tools.runtime import Runtime, content_hash, token_digest

NAME = "draft_ticket"
DESCRIPTION = (
    "Сформировать черновик заявки на дефектовку в ТОиР. Нужны вывод, операции и ссылки на "
    "руководство, полученные через search_manual в этом диалоге. Приоритет — по правилам, "
    "передавай тот, что вернул "
    "get_diagnosis. Черновик не отправляется: механик проверит и подтвердит сам."
)


class Args(BaseModel):
    vehicle_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    conclusion: str = Field(min_length=10, max_length=1500)
    urgency: Literal["low", "medium", "high"]
    operations: list[str] = Field(min_length=1)
    spare_parts: list[str] = Field(default_factory=list)
    references: list[Reference] = Field(min_length=1)


def run(rt: Runtime, args: Args) -> dict:
    turn = rt.turn
    if args.vehicle_id != turn.vehicle_id or args.session_id != turn.session_id:
        return {
            "ok": False,
            "error": "Заявка формируется только для машины и проверки этого диалога.",
        }
    vehicle = rt.deps.vehicles.get(args.vehicle_id)
    if vehicle is None:
        return {"ok": False, "error": "Машина не найдена."}
    verdict = Verdict.model_validate(turn.diagnosis["verdict"]) if turn.diagnosis else None
    check = check_ticket_draft(
        verdict=verdict,
        references=args.references,
        retrieved=turn.retrieved,
        engine_manuals=rt.engine_manuals(vehicle.engine_model),
        urgency=args.urgency,
    )
    if not check.ok or verdict is None:
        return {
            "ok": False,
            "problems": check.problems,
            "message": "Заявка не сформирована. Сначала устраните причины из списка.",
        }
    anomaly_type = turn.diagnosis["ml"]["anomaly_type"]
    if anomaly_type is None:
        return {"ok": False, "problems": ["у проверки нет типа неисправности"]}

    conclusion = args.conclusion
    if verdict.code == "needs_confirmation":
        confidence = turn.diagnosis["ml"]["confidence"]
        conclusion = (
            f"Требуется подтверждение диагноза: низкая уверенность ML "
            f"({'нет данных' if confidence is None else f'{confidence:.2f}'}). {conclusion}"
        )
    payload = TicketRequest(
        vehicle_id=args.vehicle_id,
        session_id=args.session_id,
        anomaly_type=anomaly_type,
        conclusion=conclusion,
        urgency=verdict.urgency or args.urgency,
        operations=args.operations,
        spare_parts=args.spare_parts,
        references=args.references,
    ).model_dump(mode="json")

    draft_id = f"DR-{secrets.token_hex(5)}"
    draft_hash = content_hash(payload)
    token = secrets.token_urlsafe(24)
    rt.deps.store.save_draft(
        DraftRecord(
            draft_id=draft_id,
            vehicle_id=args.vehicle_id,
            session_id=args.session_id,
            payload=payload,
            draft_hash=draft_hash,
            token_hash=token_digest(token),
            verdict_code=verdict.code,
        )
    )
    turn.events.append(
        (
            "ticket_draft",
            {
                "draft_id": draft_id,
                "draft_hash": draft_hash,
                "confirm_token": token,
                "ticket": payload,
            },
        )
    )
    return {
        "ok": True,
        "draft_id": draft_id,
        "message": "Черновик показан механику. Заявка уйдёт только после его подтверждения.",
    }
