"""Известные противоречия руководств (правило заказчика X01): обе формулировки, безопасное правило.

Код не выбирает верную формулировку. Ответ с противоречием обязан назвать его, дать обе ссылки
и безопасное правило; если модель этого не сделала, блок дописывается кодом.
"""

from app.agent.runner import TurnRequest, load_base_prompt, run_turn
from app.rag.conflicts import KnownConflict, load_conflicts, matching_conflicts, quote_for
from app.rag.search import Fragment
from tests.agent_helpers import DIAG_SESSION, DIAG_VEHICLE, ScriptedChat, make_services, reply
from tests.helpers import REPO_ROOT

CONFLICTS_PATH = REPO_ROOT / "data" / "known_conflicts.yaml"
RE_31 = "236-3902150-Б РЭ"
RK_269 = "236.01.01 РК"
X01_QUERY = "Когда регулировать тепловые зазоры клапанов у ЯМЗ-236М2: на холодном двигателе?"
X01_SEARCH = "тепловой зазор клапанов холодный двигатель 15 минут регулировка тепловых зазоров"


def _conflict() -> KnownConflict:
    conflicts = load_conflicts(CONFLICTS_PATH)
    assert len(conflicts) == 1
    return conflicts[0]


def _page_fragments(designation: str, page: int) -> list[Fragment]:
    texts = {
        (RE_31, 31): (
            "Тепловые зазоры регулировать на холодном двигателе или менее чем через 15 минут "
            "после его остановки."
        ),
        (RK_269, 269): (
            "Проверить и подрегулировать тепловые зазоры клапанного механизма перед началом и "
            "по окончании обкатки, но не ранее, чем через 15 мин после остановки двигателя."
        ),
        (RK_269, 276): (
            "Проверку зазоров в клапанном механизме производить на холодном двигателе или не "
            "ранее, чем через 15 минут после его остановки."
        ),
    }
    text = texts.get((designation, page))
    if text is None:
        return []
    return [
        Fragment(
            manual_id="yamz236_x",
            manual=designation,
            pdf_page=page,
            section=None,
            text=text,
            score=1.0,
        )
    ]


def _fetch(engine: str, designation: str, pages: list[int]) -> list[Fragment]:
    found: list[Fragment] = []
    for page in pages:
        found += _page_fragments(designation, page)
    return found


def test_customer_rule_is_loaded_with_three_pages_and_safe_rule() -> None:
    conflict = _conflict()
    assert conflict.engine_models == ["ЯМЗ-236М2"]
    assert [(ref.manual, ref.pdf_page) for ref in conflict.refs] == [
        (RE_31, 31),
        (RK_269, 269),
        (RK_269, 276),
    ]
    assert conflict.safe_rule == "на холодном двигателе"


def test_match_needs_enough_keywords_and_the_right_engine() -> None:
    conflicts = [_conflict()]
    assert matching_conflicts(conflicts, "ЯМЗ-236М2", X01_QUERY)
    assert not matching_conflicts(conflicts, "ЯМЗ-536", X01_QUERY)
    assert not matching_conflicts(conflicts, "ЯМЗ-236М2", "давление масла при прогреве")
    assert not matching_conflicts(conflicts, "ЯМЗ-236М2", "зазор клапанов")


def test_quote_is_the_sentence_with_keywords_taken_verbatim() -> None:
    fragment = Fragment(
        manual_id="x",
        manual=RE_31,
        pdf_page=31,
        section=None,
        text="Вводный текст. Тепловые зазоры регулировать на холодном двигателе или менее чем "
        "через 15 минут после его остановки. Другая фраза.",
        score=1.0,
    )
    quote = quote_for(_conflict(), fragment)
    assert quote == (
        "Тепловые зазоры регулировать на холодном двигателе или менее чем через 15 минут "
        "после его остановки."
    )


def _run(services) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    request = TurnRequest(
        vehicle_id=DIAG_VEHICLE,
        session_id=DIAG_SESSION,
        message=X01_QUERY,
        user_action=None,
        ui_mode="standard",
        lang="ru",
    )
    run_turn(services, request, load_base_prompt(), lambda name, data: events.append((name, data)))
    return events


def _services(answer: str, pages_fetcher=_fetch):
    llm = ScriptedChat(
        [
            reply(
                calls=[
                    (
                        "search_manual",
                        {"query": X01_SEARCH, "vehicle_id": DIAG_VEHICLE, "top_k": 3},
                    )
                ]
            ),
            reply(content=answer),
        ]
    )
    services = make_services(llm)
    services.deps.search = lambda query, engine, top_k: _page_fragments(RK_269, 269)
    services.deps.conflicts = [_conflict()]
    services.deps.fetch_pages = pages_fetcher
    return services


def test_search_adds_both_formulations_and_marks_the_conflict() -> None:
    services = _services("Регулировать на холодном двигателе. Уточните у специалиста.")
    _run(services)

    search = next(step for step in services.journal.steps if step.name == "search_manual")
    conflicts = search.output["conflicts"]
    assert len(conflicts) == 1
    assert [(s["manual"], s["pdf_page"]) for s in conflicts[0]["sources"]] == [
        (RE_31, 31),
        (RK_269, 269),
        (RK_269, 276),
    ]
    assert conflicts[0]["safe_rule"] == "на холодном двигателе"
    assert "в документации противоречие" in conflicts[0]["instruction"].lower()


def test_answer_without_conflict_elements_gets_the_block_appended() -> None:
    services = _services("Регулировать на холодном двигателе. Уточните у специалиста.")
    events = _run(services)

    answer = next(data["text"] for name, data in events if name == "answer_final")
    assert "В документации противоречие" in answer
    assert f"[{RE_31}, стр. 31]" in answer
    assert f"[{RK_269}, стр. 269]" in answer
    assert "на холодном двигателе" in answer
    assert any(
        step.name == "conflict_notice"
        for step in services.journal.steps
        if step.kind == "guardrail"
    )


def test_answer_with_all_elements_is_left_as_is() -> None:
    answer = (
        "В документации противоречие. Формулировки: «на холодном двигателе или менее чем через "
        f"15 минут» [{RE_31}, стр. 31]; «не ранее чем через 15 мин» [{RK_269}, стр. 269]; "
        f"«на холодном двигателе или не ранее, чем через 15 минут» [{RK_269}, стр. 276]. "
        "Безопасное правило: на холодном двигателе. Уточните у специалиста."
    )
    services = _services(answer)
    events = _run(services)

    final = next(data["text"] for name, data in events if name == "answer_final")
    assert final == answer
    assert not any(step.name == "conflict_notice" for step in services.journal.steps)


def test_single_formulation_is_not_reported_as_conflict() -> None:
    def only_re(engine: str, designation: str, pages: list[int]) -> list[Fragment]:
        return _page_fragments(RE_31, 31) if designation == RE_31 else []

    services = _services("Регулировать на холодном двигателе.", pages_fetcher=only_re)
    _run(services)

    search = next(step for step in services.journal.steps if step.name == "search_manual")
    assert "conflicts" not in search.output
