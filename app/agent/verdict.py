"""Вердикт, уверенность и приоритет заявки по правилам ТЗ §7.

Чистые функции без сети и БД: пороги приходят из настроек, основание выводится списком `reasons`,
чтобы механик видел, почему выбран приоритет (ТЗ §7, «основание показываем»).
"""

from typing import Literal

from pydantic import BaseModel, Field

CRITICAL_TYPES = frozenset({"F02", "F03", "F14"})  # давление масла, перегрев/ОЖ, цепь ГРМ (§7.2)
RISE_HIGH = 0.3  # рост score за последние проверки, при котором приоритет high (§7.2)
FUEL_HINTS: dict[str, tuple[frozenset[str], str]] = {
    "дизель": (
        frozenset({"F12", "F13"}),
        "код типа обычно относится к бензиновому двигателю; проверьте тип проверки и запись",
    ),
    "бензин": (
        frozenset({"F08"}),
        "код типа обычно относится к дизельной топливоподаче; проверьте тип проверки и запись",
    ),
}

VerdictCode = Literal["normal", "check_failed", "anomaly", "needs_confirmation"]
Urgency = Literal["low", "medium", "high"]
Light = Literal["green", "yellow", "orange", "red", "grey"]
SignalQuality = Literal["good", "warning", "bad"]


class Thresholds(BaseModel):
    conf_low: float = Field(ge=0, le=1)
    score_medium: float = Field(ge=0, le=1)
    score_high: float = Field(ge=0, le=1)


class VerdictInput(BaseModel):
    status: Literal["normal", "anomaly", "check_failed"]
    anomaly_type: str | None
    anomaly_title: str | None
    anomaly_score: float | None
    confidence: float | None
    signal_quality: SignalQuality
    fuel: str
    previous_score: float | None = None


class Verdict(BaseModel):
    code: VerdictCode
    light: Light
    headline: str
    urgency: Urgency | None
    reasons: list[str]
    recording_ok: bool

    @property
    def ticket_possible(self) -> bool:
        """По §7.1 заявка возможна только при аномалии (включая «требует подтверждения»)."""
        return self.code in ("anomaly", "needs_confirmation")


def compute_verdict(data: VerdictInput, thresholds: Thresholds) -> Verdict:
    if data.status == "check_failed" or data.signal_quality == "bad":
        return Verdict(
            code="check_failed",
            light="grey",
            headline="Сбой проверки — повторите запись",
            urgency=None,
            reasons=["запись не распознана или качество сигнала плохое"],
            recording_ok=False,
        )
    if data.status == "normal":
        return Verdict(
            code="normal",
            light="green",
            headline="Норма — можно эксплуатировать",
            urgency=None,
            reasons=["модель не нашла отклонений по этой записи"],
            recording_ok=True,
        )
    return _anomaly_verdict(data, thresholds)


def _anomaly_verdict(data: VerdictInput, thresholds: Thresholds) -> Verdict:
    score = data.anomaly_score if data.anomaly_score is not None else 0.0
    confidence = data.confidence
    low_confidence = confidence is None or confidence < thresholds.conf_low
    needs_confirmation = low_confidence or data.signal_quality == "warning"
    code: VerdictCode = "needs_confirmation" if needs_confirmation else "anomaly"
    name = data.anomaly_title or data.anomaly_type or "неисправность"
    reasons = _basis(data, thresholds, score)
    fuel_hint = FUEL_HINTS.get(data.fuel)
    if fuel_hint and data.anomaly_type in fuel_hint[0]:
        reasons.append(fuel_hint[1])

    if needs_confirmation:
        # §7.2: любой «требует подтверждения» — приоритет не выше medium
        urgency: Urgency = "medium"
        reasons.append("диагноз не подтверждён: уверенность низкая или запись с помехами")
        return Verdict(
            code=code,
            light="yellow",
            headline=f"Требует подтверждения: {name}",
            urgency=urgency,
            reasons=reasons,
            recording_ok=data.signal_quality == "good",
        )

    urgency = _urgency(data, thresholds, score, reasons)
    light: Light = "red" if urgency == "high" else "orange"
    return Verdict(
        code=code,
        light=light,
        headline=f"Отклонение: {name}",
        urgency=urgency,
        reasons=reasons,
        recording_ok=True,
    )


def _urgency(
    data: VerdictInput, thresholds: Thresholds, score: float, reasons: list[str]
) -> Urgency:
    """Порядок §7.2: сначала high, потом medium, иначе low. Основание дописываем в reasons."""
    rise = data.previous_score is not None and score - data.previous_score >= RISE_HIGH
    if score >= thresholds.score_high:
        reasons.append(f"оценка {score:.2f} ≥ {thresholds.score_high:.2f}: приоритет high")
        return "high"
    if data.anomaly_type in CRITICAL_TYPES and score >= thresholds.score_medium:
        reasons.append(f"критичный узел {data.anomaly_type} при оценке {score:.2f}: приоритет high")
        return "high"
    if rise:
        reasons.append(f"рост оценки на {score - (data.previous_score or 0):.2f}: приоритет high")
        return "high"
    if score >= thresholds.score_medium:
        reasons.append(f"оценка {score:.2f} в диапазоне 0,60–0,80: приоритет medium")
        return "medium"
    reasons.append(f"оценка {score:.2f} ниже 0,60 при хорошей записи: приоритет low")
    return "low"


def _basis(data: VerdictInput, thresholds: Thresholds, score: float) -> list[str]:
    confidence = "нет данных" if data.confidence is None else f"{data.confidence:.2f}"
    quality = {"good": "хорошее", "warning": "с помехами", "bad": "плохое"}[data.signal_quality]
    basis = [f"оценка {score:.2f}", f"уверенность {confidence}", f"качество записи {quality}"]
    if data.confidence is not None and data.confidence < thresholds.conf_low:
        basis.append(f"уверенность ниже порога {thresholds.conf_low:.2f}")
    return basis
