"""Чистка ответа после sanitize: пересказ блока противоречия удаляется целиком (run_id=4, C1)."""

from app.agent.guards import UNCONFIRMED_MARK, tidy_answer

OIL_TOPIC = "Давление масла в системе смазки при номинальных оборотах"
VALVE_TOPIC = "Когда регулировать тепловые зазоры клапанов"

# Фрагмент ответа C1 из run_id=4: модель пересказала блок давления своими словами.
C1_ANSWER = """## Вердикт

Отклонение: низкое давление масла в системе смазки ЯМЗ-236М2 — требуется дефектовка.

**Риск**

Подшипники коленчатого вала могут работать без подачи масла [236-3902150-Б РЭ, стр. 7].

**Давление масла в системе смазки при номинальных оборотах**
- 236.01.01 РК, стр. 12: «Давление в масляной системе при номинальных оборотах: 400-730 (4-7,3) кПа»

(не подтверждено руководством)

Рекомендуем.

"""


def test_c1_retelling_section_is_removed_with_its_heading() -> None:
    result = tidy_answer(C1_ANSWER, [OIL_TOPIC, VALVE_TOPIC])
    assert f"**{OIL_TOPIC}**" not in result
    assert "236.01.01 РК, стр. 12: «Давление" not in result


def test_c1_leftover_mark_and_hanging_recommendation_are_gone() -> None:
    result = tidy_answer(C1_ANSWER, [OIL_TOPIC, VALVE_TOPIC])
    assert UNCONFIRMED_MARK not in result
    assert "Рекомендуем." not in result


def test_c1_other_sections_stay_and_blank_lines_collapse() -> None:
    result = tidy_answer(C1_ANSWER, [OIL_TOPIC, VALVE_TOPIC])
    assert "## Вердикт" in result
    assert "**Риск**" in result
    assert "Подшипники коленчатого вала" in result
    assert "\n\n\n" not in result


def test_empty_bullets_and_headings_without_body_are_removed() -> None:
    answer = "**Этапы работ**\n\n**Запчасти**\nДеталь уточнить по каталогу.\n-\n1.\nГотово."
    result = tidy_answer(answer, [])
    assert "**Этапы работ**" not in result
    assert "**Запчасти**" in result
    assert "\n-\n" not in result and "\n1.\n" not in result
    assert "Готово." in result


def test_section_is_kept_when_heading_is_not_a_conflict_topic() -> None:
    answer = "**Давление масла на холостом ходу**\n- пункт про давление."
    assert tidy_answer(answer, [OIL_TOPIC]) == answer


def test_mark_after_phrase_without_numeric_norm_is_removed() -> None:
    answer = (
        "**Риск**\n\nПодшипники могут работать без подачи масла. (не подтверждено руководством)\n"
    )
    result = tidy_answer(answer, [])
    assert UNCONFIRMED_MARK not in result
    assert result == "**Риск**\n\nПодшипники могут работать без подачи масла."


def test_mark_after_phrase_with_numeric_norm_is_kept() -> None:
    answer = "Давление 400-700 кПа [236.01.01 РК, стр. 267]. (не подтверждено руководством)"
    result = tidy_answer(answer, [])
    assert result == answer
