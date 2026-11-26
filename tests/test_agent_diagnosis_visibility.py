"""Карточка вердикта и запись диагноза по ходам одной сессии.

Карточка вердикта — в первом ходе сессии и по кнопке «Получить результат»; диагноз сессии
хранится одной строкой (upsert), а не копится по каждому сообщению.
"""

from typing import Any

from app.agent.runner import TurnRequest, load_base_prompt, run_turn
from tests.agent_helpers import DIAG_SESSION, DIAG_VEHICLE, ScriptedChat, make_services, reply


def _turn(user_action: str | None = None) -> TurnRequest:
    return TurnRequest(
        vehicle_id=DIAG_VEHICLE,
        session_id=DIAG_SESSION,
        message="Что с машиной?",
        user_action=user_action,
        ui_mode="standard",
        lang="ru",
    )


def _run(services: Any, request: TurnRequest) -> list[str]:
    names: list[str] = []
    run_turn(
        services,
        request,
        load_base_prompt(),
        lambda name, data: names.append(name),
    )
    return names


def test_verdict_card_is_shown_only_on_first_turn_of_session() -> None:
    llm = ScriptedChat([reply(content="Машина в норме."), reply(content="Без изменений.")])
    services = make_services(llm)

    first = _run(services, _turn())
    second = _run(services, _turn())

    assert "verdict" in first
    assert "verdict" not in second


def test_get_diagnosis_button_shows_verdict_card_again() -> None:
    llm = ScriptedChat([reply(content="Машина в норме."), reply(content="Снова норма.")])
    services = make_services(llm)
    _run(services, _turn())

    again = _run(services, _turn(user_action="get_diagnosis"))

    assert "verdict" in again


def test_repeated_turns_keep_one_diagnosis_row_per_session() -> None:
    llm = ScriptedChat([reply(content="Норма."), reply(content="Норма."), reply(content="Норма.")])
    services = make_services(llm)

    _run(services, _turn())
    _run(services, _turn())
    _run(services, _turn(user_action="get_diagnosis"))

    diagnoses = services.deps.store.diagnoses
    assert list(diagnoses) == [(DIAG_VEHICLE, DIAG_SESSION)]
