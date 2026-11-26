"""Инструмент get_diagnosis: результат Mock ML и вердикт по правилам ТЗ §7 (ТЗ §6.2)."""

from pydantic import BaseModel, Field

from app.agent.verdict import Verdict, VerdictInput, compute_verdict
from app.clients.errors import ClientError
from app.data.vehicles import Vehicle
from app.tools.runtime import Runtime

NAME = "get_diagnosis"
DESCRIPTION = (
    "Получить результат проверки ML по машине и проверке этого диалога и вердикт по правилам: "
    "норма, отклонение, требует подтверждения или сбой записи. Вызывай первым, когда механик нажал "
    "«Получить результат диагностики» или спрашивает о состоянии машины."
)


class Args(BaseModel):
    vehicle_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


def run(rt: Runtime, args: Args) -> dict:
    turn = rt.turn
    if args.vehicle_id != turn.vehicle_id or args.session_id != turn.session_id:
        return {
            "ok": False,
            "error": "Диагностика выбирается только для машины и проверки этого диалога.",
        }
    vehicle = rt.deps.vehicles.get(args.vehicle_id)
    if vehicle is None:
        return {"ok": False, "error": "Машина не найдена."}
    try:
        ml = rt.deps.ml.diagnose(args.vehicle_id, args.session_id)
    except ClientError as exc:
        return {"ok": False, "error": exc.user_message}

    verdict = compute_verdict(
        VerdictInput(
            status=ml.status,
            anomaly_type=ml.anomaly_type,
            anomaly_title=ml.anomaly_title,
            anomaly_score=ml.anomaly_score,
            confidence=ml.confidence,
            signal_quality=ml.signal_quality,
            fuel=vehicle.fuel,
            previous_score=previous_score(vehicle, args.session_id),
        ),
        rt.deps.thresholds,
    )
    turn.diagnosis = {
        "ml": ml.model_dump(mode="json"),
        "verdict": verdict.model_dump(mode="json"),
        "engine_model": vehicle.engine_model,
        "fuel": vehicle.fuel,
    }
    _record(rt, verdict)
    turn.events.append(("verdict", _card(vehicle, turn.diagnosis, verdict)))
    return {
        "ok": True,
        "status": ml.status,
        "anomaly_type": ml.anomaly_type,
        "anomaly_title": ml.anomaly_title,
        "anomaly_score": ml.anomaly_score,
        "confidence": ml.confidence,
        "signal_quality": ml.signal_quality,
        "description": ml.description,
        "engine_model": vehicle.engine_model,
        "verdict": verdict.model_dump(mode="json"),
    }


def previous_score(vehicle: Vehicle, session_id: str) -> float | None:
    """Оценка предыдущей проверки с оценкой (для правила роста score из §7.2)."""
    earlier = []
    for session in vehicle.sessions:
        if session.session_id == session_id:
            break
        earlier.append(session)
    scored = [s for s in earlier if s.anomaly_score is not None]
    return scored[-1].anomaly_score if scored else None


def _record(rt: Runtime, verdict: Verdict) -> None:
    turn = rt.turn
    ml = turn.diagnosis["ml"] if turn.diagnosis else {}
    rt.deps.store.save_diagnosis(turn.vehicle_id, turn.session_id, ml, verdict.code)
    if verdict.code == "check_failed":
        rt.deps.store.save_recommendation(
            turn.vehicle_id,
            turn.session_id,
            "repeat_recording",
            "Повторите запись: сбой проверки или плохое качество сигнала.",
        )
    if verdict.code == "needs_confirmation":
        rt.deps.store.save_recommendation(
            turn.vehicle_id,
            turn.session_id,
            "low_confidence",
            "Диагноз не подтверждён: нужна повторная запись и дефектовка узла.",
        )


def _card(vehicle: Vehicle, diagnosis: dict, verdict: Verdict) -> dict:
    """Карточка вердикта «светофор» для интерфейса: 1 строка, уверенность, запись, приоритет."""
    ml = diagnosis["ml"]
    return {
        "light": verdict.light,
        "headline": verdict.headline,
        "confidence": ml["confidence"],
        "recording_ok": verdict.recording_ok,
        "signal_quality": ml["signal_quality"],
        "urgency": verdict.urgency,
        "reasons": verdict.reasons,
        "vehicle_id": vehicle.vehicle_id,
        "session_id": ml["session_id"],
    }
