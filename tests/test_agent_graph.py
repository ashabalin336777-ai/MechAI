"""Граф агента: цепочки инструментов, ticket_guard в живом ходе, проверка цифр (ТЗ §6.4)."""

from typing import Any

from app.agent.guards import UNCONFIRMED_MARK
from app.agent.runner import TurnRequest, load_base_prompt, run_turn
from tests.agent_helpers import (
    DIAG_SESSION,
    DIAG_VEHICLE,
    YAMZ236_RK,
    ScriptedChat,
    make_services,
    manual_fragment,
    reply,
)


def _turn(vehicle: str, session: str, message: str = "Что с машиной?") -> TurnRequest:
    return TurnRequest(
        vehicle_id=vehicle,
        session_id=session,
        message=message,
        user_action=None,
        ui_mode="standard",
        lang="ru",
    )


def _run(services: Any, request: TurnRequest) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    run_turn(services, request, load_base_prompt(), lambda name, data: events.append((name, data)))
    return events


def _run_id(services: Any) -> int:
    return next(iter(services.journal.runs))


def _names(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [name for name, _ in events]


def test_happy_path_diagnosis_then_manual_with_checked_citation() -> None:
    answer = f"Момент затяжки гаек головки 150 Н·м [{YAMZ236_RK}, стр. 267]."
    llm = ScriptedChat(
        [
            reply(
                calls=[("get_diagnosis", {"vehicle_id": DIAG_VEHICLE, "session_id": DIAG_SESSION})]
            ),
            reply(
                calls=[
                    (
                        "search_manual",
                        {
                            "query": "момент затяжки головки блока",
                            "vehicle_id": DIAG_VEHICLE,
                            "top_k": 3,
                        },
                    )
                ]
            ),
            reply(content=answer),
        ]
    )
    services = make_services(llm)
    services.deps.search = lambda query, engine, top_k: [manual_fragment()]

    events = _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    assert services.journal.chain(_run_id(services)) == ["get_diagnosis", "search_manual"]
    verdict = next(data for name, data in events if name == "verdict")
    assert verdict["urgency"] == "high"
    final = next(data for name, data in events if name == "answer_final")
    assert final["text"] == answer
    assert _names(events)[-1] == "done"
    assert any(name == "meta" for name in _names(events))


def test_check_failed_turn_keeps_ticket_out_even_if_model_asks() -> None:
    llm = ScriptedChat(
        [
            reply(calls=[("get_diagnosis", {"vehicle_id": "P456AT178", "session_id": "S-0003"})]),
            reply(
                calls=[
                    (
                        "draft_ticket",
                        {
                            "vehicle_id": "P456AT178",
                            "session_id": "S-0003",
                            "conclusion": "Попытка создать заявку при сбое записи",
                            "urgency": "high",
                            "operations": ["Снять головку блока"],
                            "spare_parts": [],
                            "references": [{"manual": YAMZ236_RK, "pdf_page": 267}],
                        },
                    )
                ]
            ),
            reply(content="Повторите запись: сигнал не распознан, заявку не создаю."),
        ]
    )
    services = make_services(llm)

    events = _run(services, _turn("P456AT178", "S-0003", "Проверь машину"))

    assert "ticket_draft" not in _names(events)
    assert services.deps.store.list_tickets("P456AT178") == []
    assert services.journal.chain(_run_id(services)) == ["get_diagnosis", "draft_ticket"]
    final = next(data for name, data in events if name == "answer_final")
    assert "Повторите запись" in final["text"]


def test_unsupported_number_is_regenerated_then_sanitized() -> None:
    wrong = f"Момент затяжки 200 Н·м [{YAMZ236_RK}, стр. 267]."
    llm = ScriptedChat(
        [
            reply(
                calls=[("get_diagnosis", {"vehicle_id": DIAG_VEHICLE, "session_id": DIAG_SESSION})]
            ),
            reply(
                calls=[
                    (
                        "search_manual",
                        {"query": "момент затяжки головки", "vehicle_id": DIAG_VEHICLE, "top_k": 3},
                    )
                ]
            ),
            reply(content=wrong),
            reply(content=wrong),  # регенерация тоже не подтверждена фрагментами
        ]
    )
    services = make_services(llm)
    services.deps.search = lambda query, engine, top_k: [manual_fragment()]

    events = _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    final = next(data for name, data in events if name == "answer_final")
    assert UNCONFIRMED_MARK in final["text"]
    assert "200" not in final["text"]
    assert len(llm.calls) == 4


def test_tool_limit_stops_offering_tools() -> None:
    llm = ScriptedChat(
        [
            reply(
                calls=[("get_diagnosis", {"vehicle_id": DIAG_VEHICLE, "session_id": DIAG_SESSION})]
            ),
            reply(calls=[("get_vehicle", {"vehicle_id": DIAG_VEHICLE})]),
        ]
    )
    services = make_services(llm, max_tool_calls=1)

    _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    assert llm.calls[1]["tools"] is None
    assert services.journal.chain(_run_id(services)) == ["get_diagnosis"]
