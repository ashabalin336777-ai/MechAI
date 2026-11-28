"""Известные противоречия руководств (правило заказчика X01): обе формулировки, безопасное правило.

Код не выбирает верную формулировку. Блок противоречия собирает код дословно из правила: все
страницы со ссылками, безопасное правило. Фразы модели о трактовке и отсылки к специалисту
убираются.
"""

import pymupdf
import pytest

from app.agent.runner import TurnRequest, load_base_prompt, run_turn
from app.rag.conflicts import (
    KnownConflict,
    conflict_triggers,
    load_conflicts,
    matching_conflicts,
    quote_for,
    quote_for_ref,
)
from app.rag.search import Fragment
from tests.agent_helpers import DIAG_SESSION, DIAG_VEHICLE, ScriptedChat, make_services, reply
from tests.helpers import REPO_ROOT, requires_real_materials

CONFLICTS_PATH = REPO_ROOT / "data" / "known_conflicts.yaml"
RE_31 = "236-3902150-Б РЭ"
RK_269 = "236.01.01 РК"
X01_QUERY = "Когда регулировать тепловые зазоры клапанов у ЯМЗ-236М2: на холодном двигателе?"
X01_SEARCH = "тепловой зазор клапанов холодный двигатель 15 минут регулировка тепловых зазоров"


OIL_ID = "yamz236_oil_pressure"
OIL_QUERY = "давление масла номинальной частоте минимальной холостого хода"


def _conflict(conflict_id: str = "yamz236_valve_clearance_timing") -> KnownConflict:
    conflicts = {conflict.id: conflict for conflict in load_conflicts(CONFLICTS_PATH)}
    assert len(conflicts) == 2
    return conflicts[conflict_id]


def _real_page_fragment(file_name: str, designation: str, page: int) -> Fragment | None:
    path = REPO_ROOT / "data" / "manuals" / file_name
    if not path.exists():
        return None
    with pymupdf.open(path) as document:
        text = document[page - 1].get_text("text")
    return Fragment(
        manual_id="yamz236_rk",
        manual=designation,
        pdf_page=page,
        section=None,
        text=text,
        score=1.0,
    )


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
            "Примечание - Проверку регулировки зазоров в клапанном механизме производить на "
            "холодном двигателе или не ранее, чем через 15 минут после его остановки."
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


def _run(services, message: str = X01_QUERY) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    request = TurnRequest(
        vehicle_id=DIAG_VEHICLE,
        session_id=DIAG_SESSION,
        message=message,
        user_action=None,
        ui_mode="standard",
        lang="ru",
    )
    run_turn(services, request, load_base_prompt(), lambda name, data: events.append((name, data)))
    return events


def _services(
    answer: str,
    pages_fetcher=_fetch,
    search_pages: tuple[tuple[str, int], ...] = ((RK_269, 269),),
    search_query: str = X01_SEARCH,
):
    llm = ScriptedChat(
        [
            reply(
                calls=[
                    (
                        "search_manual",
                        {"query": search_query, "vehicle_id": DIAG_VEHICLE, "top_k": 3},
                    )
                ]
            ),
            reply(content=answer),
        ]
    )
    services = make_services(llm)
    found = [
        fragment
        for designation, page in search_pages
        for fragment in _page_fragments(designation, page)
    ]
    services.deps.search = lambda query, engine, top_k: found
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


def test_answer_gets_the_verbatim_block_with_all_three_references() -> None:
    services = _services("Регулировать на холодном двигателе. Уточните у специалиста.")
    events = _run(services)

    answer = next(data["text"] for name, data in events if name == "answer_final")
    assert "В документации противоречие" in answer
    rule = _conflict()
    for ref in rule.refs:
        assert f"- «{ref.quote}» [{ref.manual}, стр. {ref.pdf_page}]" in answer
    assert "Безопасное правило: на холодном двигателе." in answer
    assert "специалист" not in answer.lower()
    assert any(
        step.name == "conflict_notice" and step.kind == "guardrail"
        for step in services.journal.steps
    )


def test_model_paraphrase_of_the_conflict_is_replaced_by_the_block() -> None:
    answer = (
        "Регулировать на холодном двигателе.\n"
        "Формулировки не взаимоисключающие: одна про холодный двигатель, другая про 15 минут "
        f"[{RE_31}, стр. 31].\n"
        "Уточните у специалиста."
    )
    services = _services(answer)
    events = _run(services)

    final = next(data["text"] for name, data in events if name == "answer_final")
    assert "взаимоисключ" not in final.lower()
    assert final.startswith("Регулировать на холодном двигателе.")
    assert "- «Тепловые зазоры регулировать на холодном двигателе" in final
    step = next(step for step in services.journal.steps if step.name == "conflict_notice")
    assert any("взаимоисключ" in line.lower() for line in step.output["removed"])


def test_single_formulation_is_not_reported_as_conflict() -> None:
    def only_re(engine: str, designation: str, pages: list[int]) -> list[Fragment]:
        return _page_fragments(RE_31, 31) if designation == RE_31 else []

    services = _services("Регулировать на холодном двигателе.", pages_fetcher=only_re)
    _run(services)

    search = next(step for step in services.journal.steps if step.name == "search_manual")
    assert "conflicts" not in search.output


def test_oil_pressure_rule_has_both_refs_and_narrow_safe_rule() -> None:
    conflict = _conflict(OIL_ID)
    assert [(ref.manual, ref.pdf_page) for ref in conflict.refs] == [
        ("236.01.01 РК", 12),
        ("236.01.01 РК", 267),
    ]
    assert conflict.refs[0].quote == (
        "Давление в масляной системе при номинальных оборотах: 400-730 (4-7,3) кПа"
    )
    assert "400–700 кПа" in conflict.safe_rule


def test_oil_pressure_rule_matches_its_query_but_not_a_single_term() -> None:
    conflicts = [_conflict(OIL_ID)]
    assert matching_conflicts(conflicts, "ЯМЗ-236М2", OIL_QUERY)
    assert not matching_conflicts(conflicts, "ЯМЗ-236М2", "давление масла при прогреве")
    assert not matching_conflicts(conflicts, "ЯМЗ-536", OIL_QUERY)


def test_rule_quote_is_used_when_its_numbers_are_on_the_page() -> None:
    conflict = _conflict(OIL_ID)
    fragment = Fragment(
        manual_id="yamz236_rk",
        manual="236.01.01 РК",
        pdf_page=12,
        section=None,
        text="Масляный насос\nДавление в масляной системе,\n400-730 (4-7,3)\n100 (1,0)",
        score=1.0,
    )
    assert quote_for_ref(conflict, conflict.refs[0], fragment) == conflict.refs[0].quote


def test_rule_quote_is_refused_when_its_numbers_are_missing_on_the_page() -> None:
    conflict = _conflict(OIL_ID)
    fragment = Fragment(
        manual_id="yamz236_rk",
        manual="236.01.01 РК",
        pdf_page=12,
        section=None,
        text="Давление в масляной системе 400-700 (4-7) 100 (1,0)",
        score=1.0,
    )
    assert quote_for_ref(conflict, conflict.refs[0], fragment) is None


@requires_real_materials
def test_real_pages_give_both_oil_pressure_formulations() -> None:
    conflict = _conflict(OIL_ID)
    page_12 = _real_page_fragment("yamz-236_rk_2014.pdf", "236.01.01 РК", 12)
    page_267 = _real_page_fragment("yamz-236_rk_2014.pdf", "236.01.01 РК", 267)
    if page_12 is None or page_267 is None:
        pytest.skip("руководство ЯМЗ-236М2 (РК) не найдено в data/manuals")
    assert quote_for_ref(conflict, conflict.refs[0], page_12) == conflict.refs[0].quote
    quote_267 = quote_for_ref(conflict, conflict.refs[1], page_267)
    assert quote_267 is not None and "400-700 кПа" in quote_267


def test_verbatim_quote_is_refused_when_the_page_says_something_else() -> None:
    conflict = _conflict()
    fragment = Fragment(
        manual_id="x",
        manual=RE_31,
        pdf_page=31,
        section=None,
        text="Тепловые зазоры регулировать на холодном двигателе или менее чем через 20 минут "
        "после его остановки.",
        score=1.0,
    )
    assert quote_for_ref(conflict, conflict.refs[0], fragment) is None


def test_verbatim_quote_survives_line_breaks_and_hyphenation_of_the_page() -> None:
    conflict = _conflict()
    fragment = Fragment(
        manual_id="x",
        manual=RK_269,
        pdf_page=269,
        section=None,
        text="6.4.1 Проверить и подрегулировать тепловые зазоры клапанного меха-\n"
        "низма перед началом и по окончании обкатки, но не ранее, чем через 15 мин\n"
        "после остановки двигателя.",
        score=1.0,
    )
    assert quote_for_ref(conflict, conflict.refs[1], fragment) == conflict.refs[1].quote


@requires_real_materials
def test_real_pages_contain_the_verbatim_quotes_of_the_rule() -> None:
    conflict = _conflict()
    pages = {
        (RE_31, 31): ("yamz-236_re_2010.pdf", RE_31),
        (RK_269, 269): ("yamz-236_rk_2014.pdf", RK_269),
        (RK_269, 276): ("yamz-236_rk_2014.pdf", RK_269),
    }
    for ref in conflict.refs:
        file_name, designation = pages[(ref.manual, ref.pdf_page)]
        page = _real_page_fragment(file_name, designation, ref.pdf_page)
        if page is None:
            pytest.skip("руководство ЯМЗ-236М2 не найдено в data/manuals")
        assert quote_for_ref(conflict, ref, page) == ref.quote, (ref.manual, ref.pdf_page)


def test_conflict_notice_drops_model_consult_and_adds_no_phrase() -> None:
    services = _services("Регулировать на холодном двигателе. Уточните у специалиста.")
    events = _run(services)

    answer = next(data["text"] for name, data in events if name == "answer_final")
    assert "специалист" not in answer.lower()
    # Фраза модели вырезается до блока противоречия отдельным шагом (ТЗ, этап 07a).
    removed = next(step for step in services.journal.steps if step.name == "consult_removed")
    assert removed.output["removed"] == ["Уточните у специалиста."]
    step = next(step for step in services.journal.steps if step.name == "conflict_notice")
    assert "phrase" not in step.output
    assert step.output["consult_removed"] == []
    raw = next(step for step in services.journal.steps if step.name == "raw_answer")
    assert "Уточните у специалиста." in raw.output["text"]
    assert raw.output["truncated"] is False


PAGES_QUERY = "Порядок регулировки клапанов у ЯМЗ-236М2 по руководству?"
PAGES_SEARCH = "тепловой зазор клапанов регулировка порядок"


def test_two_pages_in_turn_trigger_the_block_with_the_missing_formulation() -> None:
    # В ходе найдены только РЭ 31 и РК 269 (без ключевых слов в запросе): блок дособирает код.
    services = _services(
        "Регулировать на холодном двигателе.",
        search_pages=((RE_31, 31), (RK_269, 269)),
        search_query=PAGES_SEARCH,
    )
    events = _run(services, message=PAGES_QUERY)

    answer = next(data["text"] for name, data in events if name == "answer_final")
    assert "- «Проверить и подрегулировать тепловые зазоры" in answer
    assert "[236.01.01 РК, стр. 276]" in answer
    assert "Формулировки в руководствах расходятся" in answer
    assert "специалист" not in answer.lower()
    step = next(step for step in services.journal.steps if step.name == "conflict_notice")
    # Страницы правила в выдаче достаточны; тексты фрагментов дают и совпадение по ключевым словам.
    assert "pages" in step.output["trigger"]["yamz236_valve_clearance_timing"]


def test_query_keywords_trigger_the_block_and_record_it_in_the_journal() -> None:
    services = _services("Регулировать на холодном двигателе.")
    _run(services)

    step = next(step for step in services.journal.steps if step.name == "conflict_notice")
    assert step.output["trigger"] == {"yamz236_valve_clearance_timing": ["keywords"]}


def test_oil_pressure_rule_triggers_by_pages_and_by_query() -> None:
    conflict = _conflict(OIL_ID)
    by_query = conflict_triggers(conflict, "ЯМЗ-236М2", OIL_QUERY, [])
    assert by_query == ["keywords"]

    pages = [
        Fragment(manual_id="x", manual="236.01.01 РК", pdf_page=12, section=None, text="", score=1),
        Fragment(
            manual_id="x", manual="236.01.01 РК", pdf_page=267, section=None, text="", score=1
        ),
    ]
    assert conflict_triggers(conflict, "ЯМЗ-236М2", "давление масла при прогреве", pages) == [
        "pages"
    ]


def test_keywords_in_found_pages_do_not_trigger_the_rule() -> None:
    # Слова правила есть в найденной странице, но механик спросил о другом: блок не нужен.
    page = Fragment(
        manual_id="x",
        manual=RE_31,
        pdf_page=31,
        section=None,
        text="Тепловые зазоры регулировать на холодном двигателе после остановки, 15 мин.",
        score=1.0,
    )
    assert conflict_triggers(_conflict(), "ЯМЗ-236М2", "Порядок регулировки клапанов", [page]) == []


def test_pages_trigger_needs_two_rule_pages_and_the_right_engine() -> None:
    conflict = _conflict()
    one_page = [
        Fragment(manual_id="x", manual=RE_31, pdf_page=31, section=None, text="", score=1),
    ]
    assert conflict_triggers(conflict, "ЯМЗ-236М2", "давление масла", one_page) == []
    two_pages = one_page + [
        Fragment(manual_id="x", manual=RK_269, pdf_page=269, section=None, text="", score=1),
    ]
    assert conflict_triggers(conflict, "ЯМЗ-236М2", "давление масла", two_pages) == ["pages"]
    assert conflict_triggers(conflict, "ЯМЗ-536", "давление масла", two_pages) == []


def test_docker_image_copies_the_conflict_rules() -> None:
    lines = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    assert "COPY data/known_conflicts.yaml ./data/known_conflicts.yaml" in [
        line.strip() for line in lines
    ]
    assert CONFLICTS_PATH.exists()


def test_missing_rules_file_is_logged(tmp_path, caplog) -> None:
    with caplog.at_level("WARNING", logger="app.rag"):
        assert load_conflicts(tmp_path / "known_conflicts.yaml") == []
    assert "известных противоречий не найден" in caplog.text
