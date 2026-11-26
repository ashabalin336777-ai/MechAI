"""Данные для экранов: светофор ТС, статусы главного механика, история, график (ТЗ §7.3, §11).

Чистые функции поверх парка и правил вердикта: интерфейс не считает пороги и приоритеты сам.
"""

from pydantic import BaseModel

from app.agent.verdict import Thresholds, Verdict, VerdictInput, compute_verdict
from app.data.vehicles import SessionRecord, Vehicle
from app.tools.get_diagnosis import previous_score

STATUS_LABELS = {
    "quarantine": "Карантин",
    "attention": "Требует внимания",
    "normal": "Норма",
    "none": "Нет проверок",
}
STATUS_ORDER = {"quarantine": 0, "attention": 1, "normal": 2, "none": 3}
LIGHT_ICONS = {"green": "🟢", "yellow": "🟡", "orange": "🟠", "red": "🔴", "grey": "⚪"}
QUALITY_LABELS = {"good": "хорошее", "warning": "с помехами", "bad": "плохое"}
URGENCY_LABELS = {"high": "высокий", "medium": "средний", "low": "низкий"}


class FleetRow(BaseModel):
    vehicle_id: str
    garage_no: str
    title: str
    engine_model: str
    session_id: str | None
    checked_at: str | None
    status: str
    status_label: str
    light_icon: str
    headline: str
    reason: str | None
    score: float | None


class HistoryRow(BaseModel):
    session_id: str
    checked_at: str
    status_label: str
    light_icon: str
    headline: str
    score: float | None
    confidence: str


class Dashboard(BaseModel):
    rows: list[FleetRow]
    counts: dict[str, int]


def session_verdict(vehicle: Vehicle, session: SessionRecord, thresholds: Thresholds) -> Verdict:
    """Вердикт проверки тем же правилом, что и в агенте: оценка предыдущей проверки учитывается."""
    data = VerdictInput(
        status=session.status,
        anomaly_type=session.anomaly_type,
        anomaly_title=session.anomaly_title,
        anomaly_score=session.anomaly_score,
        confidence=session.confidence,
        signal_quality=session.signal_quality,
        fuel=vehicle.fuel,
        previous_score=previous_score(vehicle, session.session_id),
    )
    return compute_verdict(data, thresholds)


def status_of(verdict: Verdict) -> str:
    """ТЗ §7.3: карантин — высокий приоритет; внимание — любой другой вердикт, кроме нормы."""
    if verdict.urgency == "high":
        return "quarantine"
    if verdict.code != "normal":
        return "attention"
    return "normal"


def confidence_text(value: float | None) -> str:
    return "нет данных" if value is None else f"{round(value * 100)} %"


def fleet_row(vehicle: Vehicle, thresholds: Thresholds) -> FleetRow:
    title = f"{vehicle.make} {vehicle.model}".strip()
    session = vehicle.last_session
    if session is None:
        return FleetRow(
            vehicle_id=vehicle.vehicle_id,
            garage_no=vehicle.garage_no,
            title=title,
            engine_model=vehicle.engine_model,
            session_id=None,
            checked_at=None,
            status="none",
            status_label=STATUS_LABELS["none"],
            light_icon="⚪",
            headline="Проверок пока нет",
            reason=None,
            score=None,
        )
    verdict = session_verdict(vehicle, session, thresholds)
    status = status_of(verdict)
    return FleetRow(
        vehicle_id=vehicle.vehicle_id,
        garage_no=vehicle.garage_no,
        title=title,
        engine_model=vehicle.engine_model,
        session_id=session.session_id,
        checked_at=session.checked_at.strftime("%d.%m.%Y"),
        status=status,
        status_label=STATUS_LABELS[status],
        light_icon=LIGHT_ICONS[verdict.light],
        headline=verdict.headline,
        reason=verdict.reasons[0] if verdict.reasons else None,
        score=session.anomaly_score,
    )


def dashboard(vehicles: list[Vehicle], thresholds: Thresholds) -> Dashboard:
    rows = [fleet_row(vehicle, thresholds) for vehicle in vehicles]
    rows.sort(key=lambda row: (STATUS_ORDER[row.status], -(row.score or 0.0)))
    counts = {key: 0 for key in STATUS_LABELS}
    for row in rows:
        counts[row.status] += 1
    return Dashboard(rows=rows, counts=counts)


def history_rows(vehicle: Vehicle, thresholds: Thresholds) -> list[HistoryRow]:
    rows: list[HistoryRow] = []
    for session in reversed(vehicle.sessions):
        verdict = session_verdict(vehicle, session, thresholds)
        status = status_of(verdict)
        rows.append(
            HistoryRow(
                session_id=session.session_id,
                checked_at=session.checked_at.strftime("%d.%m.%Y"),
                status_label=STATUS_LABELS[status],
                light_icon=LIGHT_ICONS[verdict.light],
                headline=verdict.headline,
                score=session.anomaly_score,
                confidence=confidence_text(session.confidence),
            )
        )
    return rows


def trend_points(scores: list[float], width: int = 320, height: int = 80) -> str:
    """Точки для SVG-линии оценок: от старых проверок к новым, оценка 0..1 снизу вверх."""
    if len(scores) < 2:
        return ""
    step = width / (len(scores) - 1)
    points = [
        f"{round(index * step, 1)},{round(height - min(max(score, 0.0), 1.0) * height, 1)}"
        for index, score in enumerate(scores)
    ]
    return " ".join(points)
