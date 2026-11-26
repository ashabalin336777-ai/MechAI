"""Разбиение руководства на чанки. Чанк никогда не пересекает границу страницы PDF (ТЗ §3.4).

Размер задан в символах: для русского текста примерно 4 символа на токен, поэтому
3600 символов ≈ 900 токенов (верх диапазона 600–900), перекрытие 400 ≈ 100 токенов.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

MIN_TEXT_CHARS = 100
HARD_CHARS = 3600
OVERLAP_CHARS = 400
# Версия нарезки: при смене правил руководство переиндексируется (см. миграцию 0005).
CHUNKER_VERSION = 2
NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*\.?\s+\S")
NUMBER_TOKEN = re.compile(r"^\d+([.,]\d+)?$")
VALUE_CELL = re.compile(r"^[\d.,]+$")
SECTION_UNIT = re.compile(r",\s*(л|мм|кг|кПа|мин|Н·м|°C)\s*$")
TABLE_MIN_NUMBERS = 8  # страницы с меньшим числом цифр таблицами не считаем (find_tables медленный)
TABLE_TRUST = 0.9  # доля слов ячеек, которая должна встречаться в обычном тексте страницы
WORD_EDGES = "«»\"'()[].,;:"


@dataclass(frozen=True)
class ChunkDraft:
    pdf_page: int
    section: str | None
    text: str


@dataclass(frozen=True)
class ManualText:
    pages_total: int
    image_only_pages: list[int]
    chunks: list[ChunkDraft]


def is_heading(line: str) -> bool:
    """Эвристика: нумерованный заголовок («3.2 Смазка») или короткая строка заглавными буквами."""
    if len(line) > 90:
        return False
    if NUMBERED_HEADING.match(line):
        return True
    return (
        len(line) >= 10
        and len(line.split()) >= 2
        and line == line.upper()
        and any(c.isalpha() for c in line)
    )


def split_lines(
    lines: list[str], section: str | None
) -> tuple[list[tuple[str | None, str]], str | None]:
    """Режет строки одной страницы на чанки с перекрытием по строкам.

    Секция чанка — ближайший заголовок к его последней строке.
    Возвращает чанки и последний заголовок страницы.
    """
    chunks: list[tuple[str | None, str]] = []
    current: list[tuple[str, str | None]] = []  # строка и заголовок, действующий после неё
    current_len = 0
    heading = section
    for line in lines:
        if is_heading(line):
            heading = line
        size = len(line) + 1
        if current and current_len + size > HARD_CHARS:
            chunks.append((current[-1][1], "\n".join(text for text, _ in current)))
            tail: list[tuple[str, str | None]] = []
            tail_len = 0
            for previous in reversed(current):
                if tail_len + len(previous[0]) + 1 > OVERLAP_CHARS:
                    break
                tail.insert(0, previous)
                tail_len += len(previous[0]) + 1
            current = tail
            current_len = tail_len
        current.append((line, heading))
        current_len += size
    if current:
        chunks.append((current[-1][1], "\n".join(text for text, _ in current)))
    return chunks, heading


def build_manual_text(path: Path) -> ManualText:
    """Текст постранично (pdf_page с 1). Страницы короче 100 символов — «только рисунок»."""
    chunks: list[ChunkDraft] = []
    image_only: list[int] = []
    section: str | None = None
    with pymupdf.open(path) as document:
        pages_total = document.page_count
        for index, page in enumerate(document, start=1):
            raw = page.get_text("text")
            lines = [" ".join(line.split()) for line in raw.splitlines()]
            lines = [line for line in lines if line]
            if len("\n".join(lines)) < MIN_TEXT_CHARS:
                image_only.append(index)
                continue
            lines += table_lines(page, raw)
            page_chunks, section = split_lines(lines, section)
            chunks.extend(
                ChunkDraft(pdf_page=index, section=name, text=text) for name, text in page_chunks
            )
    return ManualText(pages_total=pages_total, image_only_pages=image_only, chunks=chunks)


def table_lines(page: pymupdf.Page, raw: str) -> list[str]:
    """Строки таблиц страницы в виде «строка: колонка значение единица».

    PyMuPDF отдаёт ячейки по одной строке, и единица отрывается от числа: «21» и «л» не рядом,
    поэтому цифра с единицей не находится как фраза (rag.mdc). Таблица берётся, только если её
    слова есть в обычном тексте страницы: повёрнутые таблицы PyMuPDF читает задом наперёд.
    """
    if sum(1 for token in raw.split() if NUMBER_TOKEN.match(token)) < TABLE_MIN_NUMBERS:
        return []
    page_words = {_word(token) for token in raw.split()}
    lines: list[str] = []
    for table in page.find_tables().tables:
        rows = [[" ".join((cell or "").split()) for cell in row] for row in table.extract()]
        if _trusted(rows, page_words):
            lines += linearize_rows(rows)
    return lines


def _trusted(rows: list[list[str]], page_words: set[str]) -> bool:
    tokens = [
        _word(token) for row in rows for cell in row for token in cell.split() if len(token) >= 3
    ]
    if not tokens:
        return False
    known = sum(1 for token in tokens if token in page_words)
    return known / len(tokens) >= TABLE_TRUST


def linearize_rows(rows: list[list[str]]) -> list[str]:
    """Первая строка таблицы — заголовки колонок. Строка с одной ячейкой — раздел с единицей."""
    if len(rows) < 2:
        return []
    header = rows[0]
    unit: str | None = None
    lines: list[str] = []
    for row in rows[1:]:
        filled = [(index, cell) for index, cell in enumerate(row) if cell]
        if not filled:
            continue
        if len(filled) == 1:
            label = filled[0][1]
            unit_match = SECTION_UNIT.search(label)
            if unit_match:
                unit = unit_match.group(1)
            lines.append(label)
            continue
        suffix = f" {unit}" if unit else ""
        pairs = [
            f"{header[index]} {value}{suffix}"
            for index, value in filled[1:]
            if header[index] and VALUE_CELL.match(value)
        ]
        if pairs:
            lines.append(f"{filled[0][1]}: " + "; ".join(pairs))
    return lines


def _word(token: str) -> str:
    return token.strip(WORD_EDGES).lower()
