"""Ответ вне базы знаний (решение заказчика, этап 07a).

Если руководство на двигатель этой машины не дало нужных данных, ответ строится так:
1. первая строка: «В руководстве на <двигатель> этих данных нет.»;
2. «Что сделать»: конкретное действие (дефектовка узла, проверка по ближайшему разделу);
3. необязательный блок «Общие сведения (не из руководства)» — только качественное описание.

В блоке общих сведений код не допускает чисел с единицами и нумерованных шагов: такой блок
вырезается целиком, и это считается метрикой. Механик сам специалист, поэтому фраз
«обратитесь к специалисту» в ответе нет (их убирает strip_consult в guards.py).
"""

import re

from pydantic import BaseModel

GENERAL_TITLE = "Общие сведения (не из руководства)"
NEXT_STEP_LABEL = "Что сделать"
DEFAULT_NEXT_STEP = "Что сделать: рекомендуем дефектовку узла по руководству на этот двигатель."
NO_DATA_PHRASE_RE = re.compile(r"этих данных нет", re.IGNORECASE)
# Первая строка заглушки «нет данных» (no_data_line). По ней такие ходы не отдаём модели в историю.
FALLBACK_FIRST_LINE_RE = re.compile(r"^\W*В руководстве на .{1,60}\s+этих данных нет")
HEADING_LINE_RE = re.compile(r"^\s*(?:#{1,6}\s|\*\*[^*\n]+\*\*\s*$)")
# Число с единицей измерения: в общих сведениях такого быть не должно.
NUMBER_WITH_UNIT_RE = re.compile(
    r"\d[\d.,]*\s*(?:мм|см|м|кПа|МПа|бар|кгс|Н·м|Н\s?м|кг|г|л|мл|°C|°С|%|об/мин|мин|ч|с|В|А|кВт)"
    r"(?![A-Za-zА-Яа-яЁё])",
)
STEP_LINE_RE = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)


class NoDataAnswer(BaseModel):
    text: str
    general_cut: int = 0
    next_step_added: bool = False


def no_data_line(engine: str) -> str:
    return f"В руководстве на {engine} этих данных нет."


def needs_no_data_format(text: str, no_data_turn: bool) -> bool:
    """Формат нужен: ход без данных руководства, в ответе «этих данных нет» или ответа нет."""
    return no_data_turn or not text.strip() or bool(NO_DATA_PHRASE_RE.search(text))


def format_no_data(answer: str, engine: str) -> NoDataAnswer:
    """Собирает ответ вне базы: первая строка, «Что сделать», общие сведения без чисел и шагов."""
    body, general = _split_general_block(answer)
    general_cut = 0
    if general is not None and _unsafe_general(general):
        general_cut = 1
        general = None
    body_lines = [line for line in body.split("\n") if not NO_DATA_PHRASE_RE.search(line)]
    body_text = "\n".join(body_lines).strip()
    next_step_added = NEXT_STEP_LABEL.lower() not in body_text.lower()
    parts = [no_data_line(engine)]
    if body_text:
        parts.append(body_text)
    if next_step_added:
        parts.append(DEFAULT_NEXT_STEP)
    if general is not None:
        parts.append(general.strip())
    return NoDataAnswer(
        text="\n\n".join(parts),
        general_cut=general_cut,
        next_step_added=next_step_added,
    )


def _split_general_block(text: str) -> tuple[str, str | None]:
    """Отделяет блок «Общие сведения» от остального текста. Блок — до следующего заголовка."""
    lines = text.split("\n")
    start = next(
        (index for index, line in enumerate(lines) if GENERAL_TITLE.lower() in line.lower()),
        None,
    )
    if start is None:
        return text, None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if HEADING_LINE_RE.match(lines[index]):
            end = index
            break
    block = "\n".join(lines[start:end])
    rest = "\n".join(lines[:start] + lines[end:])
    return rest, block


def _unsafe_general(block: str) -> bool:
    """В общих сведениях запрещены числа с единицами и пошаговый порядок работ."""
    return bool(NUMBER_WITH_UNIT_RE.search(block) or STEP_LINE_RE.search(block))
