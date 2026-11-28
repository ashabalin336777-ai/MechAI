"""Ответ вне базы знаний (этап 07a): первая строка, «Что сделать», вырезание общих сведений.

Код проверяет формат, а не промпт: блок «Общие сведения» с числом с единицей или нумерованными
шагами вырезается целиком, и это считается метрикой.
"""

import pytest

from app.agent.no_data import (
    DEFAULT_NEXT_STEP,
    format_no_data,
    needs_no_data_format,
)

ENGINE = "ЗМЗ-5234.10"
FIRST_LINE = f"В руководстве на {ENGINE} этих данных нет."


def test_empty_answer_gets_first_line_and_next_step() -> None:
    result = format_no_data("", ENGINE)
    assert result.text == f"{FIRST_LINE}\n\n{DEFAULT_NEXT_STEP}"
    assert result.next_step_added is True
    assert result.general_cut == 0


def test_first_line_is_exact_and_comes_before_everything() -> None:
    result = format_no_data("Понять по звуку трудно.\n\nЧто сделать: дефектовка узла.", ENGINE)
    lines = result.text.split("\n")
    assert lines[0] == FIRST_LINE
    assert result.next_step_added is False
    assert "Что сделать: дефектовка узла." in result.text


def test_model_own_no_data_sentence_is_not_duplicated() -> None:
    answer = f"В руководстве на {ENGINE} этих данных нет.\nЧто сделать: дефектовка узла."
    result = format_no_data(answer, ENGINE)
    assert result.text.count(FIRST_LINE) == 1
    assert result.text.startswith(FIRST_LINE)


def test_qualitative_general_block_is_kept_at_the_end() -> None:
    answer = (
        "Что сделать: дефектовка узла по руководству.\n\n"
        "**Общие сведения (не из руководства)**\n"
        "Стук обычно связан с износом сопряжения, точная причина требует осмотра."
    )
    result = format_no_data(answer, ENGINE)
    assert result.general_cut == 0
    assert result.text.endswith("точная причина требует осмотра.")
    assert "Общие сведения (не из руководства)" in result.text


@pytest.mark.parametrize(
    "block_line",
    [
        "Зазор обычно 0,25 мм.",
        "Момент около 150 Н·м.",
        "Давление порядка 400 кПа при прогреве.",
        "Объём масла примерно 9 л.",
    ],
)
def test_general_block_with_number_and_unit_is_cut(block_line: str) -> None:
    answer = (
        f"Что сделать: дефектовка узла.\n\n**Общие сведения (не из руководства)**\n{block_line}"
    )
    result = format_no_data(answer, ENGINE)
    assert result.general_cut == 1
    assert "Общие сведения" not in result.text
    assert block_line not in result.text


def test_general_block_with_numbered_steps_is_cut() -> None:
    answer = (
        "Что сделать: дефектовка узла.\n\n"
        "**Общие сведения (не из руководства)**\n"
        "1. Снять крышку.\n"
        "2. Промыть детали."
    )
    result = format_no_data(answer, ENGINE)
    assert result.general_cut == 1
    assert "Снять крышку" not in result.text


def test_general_block_stops_at_next_heading() -> None:
    answer = (
        "**Общие сведения (не из руководства)**\n"
        "Износ сопряжения обычно виден по звуку.\n\n"
        "**Ограничения**\n"
        "Окончательный вывод после замеров."
    )
    result = format_no_data(answer, ENGINE)
    assert result.general_cut == 0
    assert "Окончательный вывод после замеров." in result.text
    assert "Износ сопряжения обычно виден по звуку." in result.text


def test_numbers_outside_general_block_are_left_for_citation_check() -> None:
    answer = (
        "Что сделать: проверка по разделу [ЗМЗ-5234, стр. 12].\nМомент 150 Н·м [ЗМЗ-5234, стр. 12]."
    )
    result = format_no_data(answer, ENGINE)
    assert result.general_cut == 0
    assert "150 Н·м [ЗМЗ-5234, стр. 12]" in result.text


@pytest.mark.parametrize(
    ("text", "no_data_turn", "expected"),
    [
        ("Нормальный ответ с фрагментами.", False, False),
        ("Нормальный ответ с фрагментами.", True, True),
        ("", False, True),
        (f"{FIRST_LINE}\nЧто сделать: дефектовка.", False, True),
    ],
)
def test_format_is_needed_for_no_data_turns_and_phrases(
    text: str, no_data_turn: bool, expected: bool
) -> None:
    assert needs_no_data_format(text, no_data_turn) is expected
