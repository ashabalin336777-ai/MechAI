"""Совместимость кода неисправности с топливом (ТЗ §17.1): F13 у дизеля — «нет инструкции».

Процедуру не подбираем (search_manual отказывает), заявку не формируем (draft_ticket отказывает),
рекомендация «повторная дефектовка» сохраняется. Проверяется на машине TST-C003 (ЯМЗ-536, дизель).
"""

import pytest

from app.agent.compat import expected_fuel, fuel_mismatch
from app.agent.runner import TurnRequest, load_base_prompt, run_turn
from app.tools import draft_ticket, get_diagnosis, search_manual
from app.tools.runtime import Runtime, TurnContext
from tests.agent_helpers import ScriptedChat, make_services, reply

MISMATCH_VEHICLE = "TST-C003"
MISMATCH_SESSION = "S-9008"
MANUAL_536 = "536.3902150 РЭ"


@pytest.mark.parametrize(
    ("anomaly_type", "fuel", "required"),
    [
        ("F13", "дизель", "бензин"),
        ("F12", "дизель", "бензин"),
        ("F08", "бензин", "дизель"),
    ],
)
def test_fault_code_from_other_fuel_is_a_mismatch(
    anomaly_type: str, fuel: str, required: str
) -> None:
    assert fuel_mismatch(anomaly_type, fuel) == required


@pytest.mark.parametrize(
    ("anomaly_type", "fuel"),
    [("F13", "бензин"), ("F08", "дизель"), ("F02", "дизель"), (None, "дизель")],
)
def test_matching_or_fuel_free_codes_are_not_a_mismatch(
    anomaly_type: str | None, fuel: str
) -> None:
    assert fuel_mismatch(anomaly_type, fuel) is None


def test_fuel_free_code_has_no_expected_fuel() -> None:
    assert expected_fuel("F02") is None


def test_diagnosis_of_mismatch_vehicle_is_yellow_and_not_ticketable() -> None:
    turn = TurnContext(vehicle_id=MISMATCH_VEHICLE, session_id=MISMATCH_SESSION)
    runtime = Runtime(deps=make_services(ScriptedChat([])).deps, turn=turn)
    result = get_diagnosis.run(
        runtime, get_diagnosis.Args(vehicle_id=MISMATCH_VEHICLE, session_id=MISMATCH_SESSION)
    )
    assert result["ok"], result
    assert result["verdict"]["code"] == "mismatch"
    assert result["verdict"]["light"] == "yellow"
    assert result["verdict"]["urgency"] is None


def test_mismatch_turn_refuses_search_and_ticket_and_records_recommendation() -> None:
    llm = ScriptedChat(
        [
            reply(
                calls=[
                    (
                        "search_manual",
                        {
                            "query": "подача бензина F13",
                            "vehicle_id": MISMATCH_VEHICLE,
                            "top_k": 3,
                        },
                    )
                ]
            ),
            reply(
                calls=[
                    (
                        "draft_ticket",
                        {
                            "vehicle_id": MISMATCH_VEHICLE,
                            "session_id": MISMATCH_SESSION,
                            "conclusion": "Нужна дефектовка топливоподачи",
                            "urgency": "high",
                            "operations": ["Проверить фильтры"],
                            "spare_parts": [],
                            "references": [{"manual": MANUAL_536, "pdf_page": 47}],
                        },
                    )
                ]
            ),
            reply(
                content="Код F13 не относится к дизельному двигателю: несоответствие. "
                "Рекомендую повторную дефектовку, заявку не формирую."
            ),
        ]
    )
    services = make_services(llm)
    events: list[tuple[str, dict]] = []
    request = TurnRequest(
        vehicle_id=MISMATCH_VEHICLE,
        session_id=MISMATCH_SESSION,
        message="Что делать по F13 и можно ли заявку?",
        user_action=None,
        ui_mode="standard",
        lang="ru",
    )
    run_turn(services, request, load_base_prompt(), lambda name, data: events.append((name, data)))

    searches = [step for step in services.journal.steps if step.name == "search_manual"]
    assert searches and "не применим" in searches[0].output["message"]
    assert all(not step.output.get("found") for step in searches)

    drafts = [step for step in services.journal.steps if step.name == "draft_ticket"]
    assert drafts and drafts[0].output["ok"] is False
    assert any("заявка не создаётся" in problem for problem in drafts[0].output["problems"])
    assert not any(name == "ticket_draft" for name, _ in events)

    assert (
        MISMATCH_VEHICLE,
        MISMATCH_SESSION,
        "defect_inspection_no_procedure",
    ) in services.deps.store.recommendations


def test_search_manual_direct_call_is_refused_for_mismatch() -> None:
    turn = TurnContext(vehicle_id=MISMATCH_VEHICLE, session_id=MISMATCH_SESSION)
    services = make_services(ScriptedChat([]))
    runtime = Runtime(deps=services.deps, turn=turn)
    get_diagnosis.run(
        runtime, get_diagnosis.Args(vehicle_id=MISMATCH_VEHICLE, session_id=MISMATCH_SESSION)
    )
    result = search_manual.run(
        runtime,
        search_manual.Args(query="подача бензина", vehicle_id=MISMATCH_VEHICLE, top_k=3),
    )
    assert result["found"] is False
    assert turn.retrieved == []


def test_draft_ticket_direct_call_is_refused_for_mismatch() -> None:
    turn = TurnContext(vehicle_id=MISMATCH_VEHICLE, session_id=MISMATCH_SESSION)
    services = make_services(ScriptedChat([]))
    runtime = Runtime(deps=services.deps, turn=turn)
    get_diagnosis.run(
        runtime, get_diagnosis.Args(vehicle_id=MISMATCH_VEHICLE, session_id=MISMATCH_SESSION)
    )
    result = draft_ticket.run(
        runtime,
        draft_ticket.Args(
            vehicle_id=MISMATCH_VEHICLE,
            session_id=MISMATCH_SESSION,
            conclusion="Нужна дефектовка топливоподачи",
            urgency="high",
            operations=["Проверить фильтры"],
            spare_parts=[],
            references=[{"manual": MANUAL_536, "pdf_page": 47}],
        ),
    )
    assert result["ok"] is False
    assert not any(name == "ticket_draft" for name, _ in turn.events)
