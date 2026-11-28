"""Граф агента: предзагрузка данных, цепочки инструментов, ticket_guard, проверка цифр (ТЗ §6.4)."""

from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from app.agent.graph import HISTORY_TURNS, recent_messages
from app.agent.guards import UNCONFIRMED_MARK
from app.agent.runner import TurnRequest, load_base_prompt, run_turn
from app.rag.search import Fragment
from tests.agent_helpers import (
    DIAG_SESSION,
    DIAG_VEHICLE,
    YAMZ236_RK,
    ScriptedChat,
    make_services,
    manual_fragment,
    reply,
)

PREFETCH_CHAIN = ["get_vehicle", "get_diagnosis", "get_history"]


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


def test_happy_path_prefetch_then_manual_with_checked_citation() -> None:
    answer = f"Момент затяжки гаек головки 150 Н·м [{YAMZ236_RK}, стр. 267]."
    llm = ScriptedChat(
        [
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

    assert services.journal.chain(_run_id(services)) == [*PREFETCH_CHAIN, "search_manual"]
    verdict = next(data for name, data in events if name == "verdict")
    assert verdict["urgency"] == "high"
    final = next(data for name, data in events if name == "answer_final")
    assert final["text"] == answer
    assert _names(events)[-1] == "done"
    assert any(name == "meta" for name in _names(events))


def test_check_failed_turn_keeps_ticket_out_even_if_model_asks() -> None:
    llm = ScriptedChat(
        [
            reply(
                calls=[
                    (
                        "draft_ticket",
                        {
                            "vehicle_id": "TST-A001",
                            "session_id": "S-9003",
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

    events = _run(services, _turn("TST-A001", "S-9003", "Проверь машину"))

    assert "ticket_draft" not in _names(events)
    assert services.deps.store.list_tickets("TST-A001") == []
    assert services.journal.chain(_run_id(services)) == [*PREFETCH_CHAIN, "draft_ticket"]
    final = next(data for name, data in events if name == "answer_final")
    assert "Повторите запись" in final["text"]


def test_unsupported_number_is_regenerated_then_sanitized() -> None:
    wrong = f"Момент затяжки 200 Н·м [{YAMZ236_RK}, стр. 267]."
    llm = ScriptedChat(
        [
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
    lines = final["text"].splitlines()
    assert lines[0].startswith("В руководстве на ") and lines[0].endswith(" этих данных нет.")
    assert "Что сделать" in final["text"]
    assert UNCONFIRMED_MARK not in final["text"]
    assert "200" not in final["text"]
    assert len(llm.calls) == 3


def test_tool_limit_stops_offering_tools() -> None:
    llm = ScriptedChat(
        [
            reply(
                calls=[
                    (
                        "search_manual",
                        {"query": "момент затяжки головки", "vehicle_id": DIAG_VEHICLE, "top_k": 3},
                    )
                ]
            ),
            reply(content="Момент уточню по руководству."),
        ]
    )
    services = make_services(llm, max_tool_calls=1)
    services.deps.search = lambda query, engine, top_k: [manual_fragment()]

    _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    assert llm.calls[0]["tools"] is not None
    assert llm.calls[1]["tools"] is None
    assert services.journal.chain(_run_id(services)) == [*PREFETCH_CHAIN, "search_manual"]


def test_prefetched_data_is_in_context_and_not_offered_to_model() -> None:
    llm = ScriptedChat([reply(content="Машина в норме.")])
    services = make_services(llm)

    _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    first = llm.calls[0]
    offered = {tool["function"]["name"] for tool in first["tools"]}
    assert offered.isdisjoint(PREFETCH_CHAIN)
    assert "search_manual" in offered
    tool_data = "\n".join(str(m.get("content", "")) for m in first["messages"])
    assert "<tool_data>" in tool_data
    assert DIAG_VEHICLE in tool_data


def test_model_repeating_prefetched_tool_gets_refusal_not_a_second_call() -> None:
    llm = ScriptedChat(
        [
            reply(
                calls=[("get_diagnosis", {"vehicle_id": DIAG_VEHICLE, "session_id": DIAG_SESSION})]
            ),
            reply(content="Диагноз уже в контексте."),
        ]
    )
    services = make_services(llm)

    _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    assert services.journal.chain(_run_id(services)) == [*PREFETCH_CHAIN, "get_diagnosis"]
    refused = [s for s in services.journal.steps if s.name == "get_diagnosis" and s.error]
    assert [s.error for s in refused] == ["tool_refused"]


def test_search_manual_is_limited_to_three_calls_per_turn() -> None:
    search_call = (
        "search_manual",
        {"query": "момент затяжки головки", "vehicle_id": DIAG_VEHICLE, "top_k": 3},
    )
    llm = ScriptedChat(
        [
            reply(calls=[search_call]),
            reply(calls=[search_call]),
            reply(calls=[search_call]),
            reply(calls=[search_call]),
            reply(content="Итог по имеющимся данным."),
        ]
    )
    services = make_services(llm, max_tool_calls=8)
    services.deps.search = lambda query, engine, top_k: [manual_fragment()]

    _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    searches = [s for s in services.journal.steps if s.name == "search_manual"]
    assert [s.error for s in searches] == [None, None, None, "tool_refused"]


def test_number_on_another_page_of_this_turn_moves_the_citation_and_is_logged() -> None:
    page_268 = Fragment(
        manual_id="yamz236_rk",
        manual=YAMZ236_RK,
        pdf_page=268,
        section=None,
        text="Давление масла на холостом ходу не менее 100 кПа.",
        score=0.9,
    )
    answer = f"Минимальное давление масла 100 кПа [{YAMZ236_RK}, стр. 267]."
    llm = ScriptedChat(
        [
            reply(
                calls=[
                    (
                        "search_manual",
                        {
                            "query": "давление масла холостой ход",
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
    services.deps.search = lambda query, engine, top_k: [manual_fragment(), page_268]

    events = _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    final = next(data for name, data in events if name == "answer_final")
    assert final["text"] == f"Минимальное давление масла 100 кПа [{YAMZ236_RK}, стр. 268]."
    fixes = [s for s in services.journal.steps if s.name == "citation_fixed"]
    assert len(fixes) == 1
    assert fixes[0].output["fixes"][0]["claim"] == "100 кПа"
    assert len(llm.calls) == 2


RE_MANUAL = "236-3902150-Б РЭ"
C1_WRONG_PAGE = f"Давление масла может быть ниже 100 кПа [{YAMZ236_RK}, стр. 46]."


def _pages_of_this_turn() -> list[Fragment]:
    page_19 = Fragment(
        manual_id="yamz236_re",
        manual=RE_MANUAL,
        pdf_page=19,
        section=None,
        text="На холостом ходу давление масла не менее 100 кПа.",
        score=0.9,
    )
    return [page_19, manual_fragment("Давление масла не менее 100 кПа при минимальной частоте.")]


def test_c1_wrong_page_is_replaced_by_page_of_this_turn_and_not_cut() -> None:
    """C1 (eval run 7): стр. 46 не получена и не содержит 100 кПа — ссылка заменяется кодом."""
    llm = ScriptedChat(
        [
            reply(
                calls=[
                    (
                        "search_manual",
                        {"query": "давление масла", "vehicle_id": DIAG_VEHICLE, "top_k": 3},
                    )
                ]
            ),
            reply(content=C1_WRONG_PAGE),
        ]
    )
    services = make_services(llm)
    services.deps.search = lambda query, engine, top_k: _pages_of_this_turn()

    events = _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    final = next(data["text"] for name, data in events if name == "answer_final")
    assert final == f"Давление масла может быть ниже 100 кПа [{RE_MANUAL}, стр. 19]."
    assert len(llm.calls) == 2
    fixes = [s for s in services.journal.steps if s.name == "citation_fixed"]
    assert fixes[0].output["fixes"] == [
        {
            "from": f"[{YAMZ236_RK}, стр. 46]",
            "to": f"[{RE_MANUAL}, стр. 19]",
            "claim": "100 кПа",
        }
    ]
    check = next(s for s in services.journal.steps if s.name == "citation_check")
    assert check.output["ok"] is True
    assert check.output["model_problems"]
    assert check.output["regenerated"] is False


def test_fix_is_applied_again_to_regenerated_answer() -> None:
    """Первый ответ — цифра нигде не найдена, регенерация ставит стр. 46: её исправляем кодом."""
    llm = ScriptedChat(
        [
            reply(
                calls=[
                    (
                        "search_manual",
                        {"query": "давление масла", "vehicle_id": DIAG_VEHICLE, "top_k": 3},
                    )
                ]
            ),
            reply(content=f"Давление масла 200 кПа [{YAMZ236_RK}, стр. 267]."),
            reply(content=C1_WRONG_PAGE),
        ]
    )
    services = make_services(llm)
    services.deps.search = lambda query, engine, top_k: _pages_of_this_turn()[1:]

    events = _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    final = next(data["text"] for name, data in events if name == "answer_final")
    assert final == f"Давление масла может быть ниже 100 кПа [{YAMZ236_RK}, стр. 267]."
    assert UNCONFIRMED_MARK not in final
    assert len(llm.calls) == 3
    check = next(s for s in services.journal.steps if s.name == "citation_check")
    assert check.output["ok"] is True
    assert check.output["regenerated"] is True


SEARCH_CALL = (
    "search_manual",
    {"query": "момент затяжки головки", "vehicle_id": DIAG_VEHICLE, "top_k": 3},
)


def test_grounded_answer_with_no_data_phrase_is_not_reformatted() -> None:
    """Первый поиск ничего не нашёл, второй нашёл страницу с цифрой и ссылкой. Фраза «этих данных
    нет» про один подвопрос не должна переписывать ответ под «нет данных» (стенд, С1)."""
    answer = (
        "По прогреву этих данных нет. "
        f"Момент затяжки гаек головки 150 Н·м [{YAMZ236_RK}, стр. 267]."
    )
    found = iter([[], [manual_fragment()]])
    llm = ScriptedChat(
        [reply(calls=[SEARCH_CALL]), reply(calls=[SEARCH_CALL]), reply(content=answer)]
    )
    services = make_services(llm)
    services.deps.search = lambda query, engine, top_k: next(found)

    events = _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    final = next(data["text"] for name, data in events if name == "answer_final")
    assert final == answer
    assert "no_data_format" not in [s.name for s in services.journal.steps]
    assert len(llm.calls) == 3


def test_no_data_phrase_without_found_fragments_is_still_formatted() -> None:
    """Фрагментов нет совсем: фраза «этих данных нет» остаётся поводом для формата «нет данных»."""
    llm = ScriptedChat(
        [
            reply(calls=[SEARCH_CALL]),
            reply(content="По прогреву этих данных нет. Что сделать: дефектовка узла."),
        ]
    )
    services = make_services(llm)
    services.deps.search = lambda query, engine, top_k: []

    events = _run(services, _turn(DIAG_VEHICLE, DIAG_SESSION))

    final = next(data["text"] for name, data in events if name == "answer_final")
    lines = final.splitlines()
    assert lines[0].startswith("В руководстве на ") and lines[0].endswith(" этих данных нет.")
    assert "no_data_format" in [s.name for s in services.journal.steps]


def test_model_context_keeps_only_last_turns_as_whole_units() -> None:
    """В модель уходят последние HISTORY_TURNS ходов целиком, каждый начинается с вопроса."""
    total = HISTORY_TURNS + 2
    history: list[AnyMessage] = []
    for number in range(total):
        history += [
            HumanMessage(content=f"вопрос {number}"),
            AIMessage(
                content="", tool_calls=[{"name": "get_vehicle", "args": {}, "id": str(number)}]
            ),
            ToolMessage(content="данные", tool_call_id=str(number)),
            AIMessage(content=f"ответ {number}"),
        ]

    kept = recent_messages(history)

    assert isinstance(kept[0], HumanMessage)
    assert kept[0].content == f"вопрос {total - HISTORY_TURNS}"
    assert len(kept) == HISTORY_TURNS * 4
    assert recent_messages(history[:4]) == history[:4]


FALLBACK_ANSWER = "В руководстве на ЯМЗ-236М2 этих данных нет.\nЧто сделать: дефектовка узла."


def _turn_messages(number: int, answer: str) -> list[AnyMessage]:
    return [
        HumanMessage(content=f"вопрос {number}"),
        AIMessage(content="", tool_calls=[{"name": "get_vehicle", "args": {}, "id": f"c{number}"}]),
        ToolMessage(content="данные", tool_call_id=f"c{number}"),
        AIMessage(content=answer),
    ]


def test_past_fallback_turn_is_dropped_from_model_context() -> None:
    """Заглушка «нет данных» в прошлом ходе не уходит модели: иначе она копирует её без поиска."""
    history = [
        *_turn_messages(1, "Момент затяжки 150 Н·м."),
        *_turn_messages(2, FALLBACK_ANSWER),
        *_turn_messages(3, "Давление масла 100 кПа."),
        *_turn_messages(4, "Текущий вопрос."),
    ]

    kept = recent_messages(history)

    kept_texts = [str(message.content) for message in kept]
    assert "вопрос 2" not in kept_texts
    assert FALLBACK_ANSWER not in kept_texts
    assert "вопрос 1" in kept_texts
    assert "вопрос 3" in kept_texts
    assert kept[-1].content == "Текущий вопрос."


def test_current_fallback_turn_is_kept() -> None:
    """Текущий ход не выбрасываем, даже если его ответ — заглушка: модель должна видеть вопрос."""
    history = [
        *_turn_messages(1, "Момент затяжки 150 Н·м."),
        *_turn_messages(2, FALLBACK_ANSWER),
    ]

    kept = recent_messages(history)

    kept_texts = [str(message.content) for message in kept]
    assert "вопрос 2" in kept_texts
    assert FALLBACK_ANSWER in kept_texts
    assert "вопрос 1" in kept_texts
