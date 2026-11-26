"""Черновик заявки: цифра с единицей только из фрагментов этого диалога (rag.mdc, ТЗ §6.4)."""

from app.tools import draft_ticket, get_diagnosis
from app.tools.runtime import Runtime, TurnContext
from tests.agent_helpers import (
    DIAG_SESSION,
    DIAG_VEHICLE,
    YAMZ236_RK,
    ScriptedChat,
    make_services,
    manual_fragment,
)


def _draft(conclusion: str):
    services = make_services(ScriptedChat([]))
    turn = TurnContext(vehicle_id=DIAG_VEHICLE, session_id=DIAG_SESSION)
    runtime = Runtime(deps=services.deps, turn=turn)
    diagnosis = get_diagnosis.run(
        runtime, get_diagnosis.Args(vehicle_id=DIAG_VEHICLE, session_id=DIAG_SESSION)
    )
    assert diagnosis["ok"], diagnosis
    turn.remember([manual_fragment("Момент затяжки гаек головки блока 150 Н·м")])
    return draft_ticket.run(
        runtime,
        draft_ticket.Args(
            vehicle_id=DIAG_VEHICLE,
            session_id=DIAG_SESSION,
            conclusion=conclusion,
            urgency="high",
            operations=["Проверить затяжку гаек"],
            spare_parts=[],
            references=[{"manual": YAMZ236_RK, "pdf_page": 267}],
        ),
    )


def test_draft_with_number_from_this_dialog_is_accepted() -> None:
    result = _draft("Проверить затяжку гаек головки, норма 150 Н·м, нужна дефектовка")
    assert result["ok"], result


def test_draft_with_number_not_from_manual_is_refused() -> None:
    result = _draft("Проверить затяжку гаек головки, норма 300 Н·м, нужна дефектовка")
    assert result["ok"] is False
    assert any("300 Н·м" in problem for problem in result["problems"]), result
