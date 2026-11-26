"""Вердикт, уверенность и приоритет по правилам ТЗ §7 (таблица случаев)."""

import pytest

from app.agent.verdict import Thresholds, VerdictInput, compute_verdict

THRESHOLDS = Thresholds(conf_low=0.60, score_medium=0.60, score_high=0.80)


def _input(**overrides: object) -> VerdictInput:
    base: dict[str, object] = {
        "status": "anomaly",
        "anomaly_type": "F05",
        "anomaly_title": "Тестовая неисправность",
        "anomaly_score": 0.70,
        "confidence": 0.90,
        "signal_quality": "good",
        "fuel": "дизель",
        "previous_score": None,
    }
    base.update(overrides)
    return VerdictInput.model_validate(base)


def test_check_failed_status_gives_grey_without_ticket() -> None:
    verdict = compute_verdict(
        _input(
            status="check_failed",
            anomaly_type=None,
            anomaly_score=None,
            confidence=None,
            signal_quality="bad",
        ),
        THRESHOLDS,
    )
    assert verdict.code == "check_failed"
    assert verdict.light == "grey"
    assert verdict.recording_ok is False
    assert verdict.ticket_possible is False


def test_bad_signal_overrides_anomaly_to_check_failed() -> None:
    verdict = compute_verdict(_input(signal_quality="bad"), THRESHOLDS)
    assert verdict.code == "check_failed"
    assert verdict.ticket_possible is False


def test_normal_gives_green_without_ticket() -> None:
    verdict = compute_verdict(
        _input(status="normal", anomaly_type=None, anomaly_title=None, anomaly_score=0.1),
        THRESHOLDS,
    )
    assert verdict.code == "normal"
    assert verdict.light == "green"
    assert verdict.urgency is None
    assert verdict.ticket_possible is False


def test_high_score_with_confidence_gives_red_high() -> None:
    verdict = compute_verdict(_input(anomaly_type="F02", anomaly_score=0.85), THRESHOLDS)
    assert (verdict.code, verdict.light, verdict.urgency) == ("anomaly", "red", "high")
    assert verdict.ticket_possible is True
    assert any("приоритет high" in reason for reason in verdict.reasons)


@pytest.mark.parametrize(
    ("score", "urgency"),
    [(0.70, "medium"), (0.50, "low")],
)
def test_mid_and_low_score_with_confidence_gives_orange(score: float, urgency: str) -> None:
    verdict = compute_verdict(_input(anomaly_score=score), THRESHOLDS)
    assert verdict.code == "anomaly"
    assert verdict.light == "orange"
    assert verdict.urgency == urgency


def test_low_confidence_needs_confirmation_with_medium_urgency_at_most() -> None:
    verdict = compute_verdict(_input(anomaly_score=0.85, confidence=0.50), THRESHOLDS)
    assert verdict.code == "needs_confirmation"
    assert verdict.light == "yellow"
    assert verdict.urgency == "medium"
    assert verdict.ticket_possible is True


def test_missing_confidence_needs_confirmation() -> None:
    verdict = compute_verdict(_input(confidence=None), THRESHOLDS)
    assert verdict.code == "needs_confirmation"


def test_warning_signal_needs_confirmation_even_with_high_confidence() -> None:
    verdict = compute_verdict(_input(anomaly_score=0.9, signal_quality="warning"), THRESHOLDS)
    assert verdict.code == "needs_confirmation"
    assert verdict.urgency == "medium"


def test_critical_type_at_medium_score_gives_high() -> None:
    verdict = compute_verdict(_input(anomaly_type="F02", anomaly_score=0.65), THRESHOLDS)
    assert verdict.urgency == "high"
    assert any("критичный узел F02" in reason for reason in verdict.reasons)


def test_rise_of_score_gives_high() -> None:
    verdict = compute_verdict(_input(anomaly_score=0.72, previous_score=0.40), THRESHOLDS)
    assert verdict.urgency == "high"
    assert any("рост оценки" in reason for reason in verdict.reasons)


def test_diesel_with_petrol_code_is_mismatch_not_a_procedure() -> None:
    """ТЗ §17.1: F13 («подача бензина») у дизеля — 🟡 «Нет инструкции», приоритета и заявки нет."""
    verdict = compute_verdict(_input(anomaly_type="F13", fuel="дизель"), THRESHOLDS)
    assert verdict.code == "mismatch"
    assert verdict.light == "yellow"
    assert verdict.urgency is None
    assert not verdict.ticket_possible
    assert any("бензиновом" in reason or "бензин" in reason for reason in verdict.reasons)


def test_petrol_with_diesel_code_is_mismatch() -> None:
    verdict = compute_verdict(_input(anomaly_type="F08", fuel="бензин"), THRESHOLDS)
    assert verdict.code == "mismatch"
    assert "бензиновому" in verdict.headline
    assert any("дизель" in reason for reason in verdict.reasons)


def test_petrol_code_on_petrol_engine_is_a_normal_anomaly() -> None:
    verdict = compute_verdict(_input(anomaly_type="F13", fuel="бензин"), THRESHOLDS)
    assert verdict.code == "anomaly"
    assert verdict.ticket_possible


def test_code_without_fuel_rule_is_not_a_mismatch() -> None:
    verdict = compute_verdict(_input(anomaly_type="F02", fuel="дизель"), THRESHOLDS)
    assert verdict.code != "mismatch"
