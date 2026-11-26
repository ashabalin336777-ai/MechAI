"""Инструмент get_history: прошлые проверки ТС и наши заявки (ТЗ §6.2, B1)."""

from pydantic import BaseModel, Field

from app.tools.runtime import Runtime

NAME = "get_history"
DESCRIPTION = (
    "История машины: прошлые проверки (оценка, уверенность, тип неисправности) и заявки, "
    "созданные в системе. Вызывай, когда спрашивают о прошлом машины или перед новой заявкой, "
    "чтобы не дублировать существующую."
)


class Args(BaseModel):
    vehicle_id: str = Field(min_length=1)
    until_session_id: str | None = Field(
        default=None, description="Только проверки до этой (не включая)"
    )


def run(rt: Runtime, args: Args) -> dict:
    if args.vehicle_id != rt.turn.vehicle_id:
        return {"ok": False, "error": "История выбирается только для машины этого диалога."}
    sessions = rt.deps.vehicles.history(args.vehicle_id, args.until_session_id)
    if not sessions and rt.deps.vehicles.get(args.vehicle_id) is None:
        return {"ok": False, "error": "Машина не найдена."}
    checks = [
        {
            "session_id": s.session_id,
            "checked_at": s.checked_at.date().isoformat(),
            "status": s.status,
            "anomaly_type": s.anomaly_type,
            "anomaly_score": s.anomaly_score,
            "confidence": s.confidence,
            "signal_quality": s.signal_quality,
        }
        for s in sessions
    ]
    tickets = [
        {
            "ticket_id": t.ticket_id,
            "session_id": t.session_id,
            "created_at": t.created_at.date().isoformat(),
            "anomaly_type": t.payload.get("anomaly_type"),
        }
        for t in rt.deps.store.list_tickets(args.vehicle_id)
    ]
    scores = [c["anomaly_score"] for c in checks if c["anomaly_score"] is not None]
    return {
        "ok": True,
        "checks": checks,
        "scores_trend": scores,
        "tickets": tickets,
    }
