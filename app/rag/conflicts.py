"""Известные противоречия в руководствах (правила заказчика, data/known_conflicts.yaml).

Код сам не решает, какая формулировка верна: он показывает обе со ссылками и безопасное правило
заказчика. Совпадение — по ключевым словам в запросе механика и в найденных фрагментах.
"""

import logging
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from app.rag.search import Fragment

logger = logging.getLogger("app.rag")

# Переносы строк PDF внутри предложения не границы: иначе цитата обрывается на полуслове.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;])\s+")
HYPHEN_BREAK_RE = re.compile(r"-\n")


class ConflictRef(BaseModel):
    manual: str = Field(min_length=3)
    pdf_page: int = Field(ge=1)
    # Цитата, заданная правилом. verbatim: должна быть дословно на странице (после склейки строк).
    # numbers: для повёрнутых таблиц, где текст страницы не совпадает побуквенно; проверяются числа.
    quote: str | None = Field(default=None, min_length=3)
    check: Literal["verbatim", "numbers"] = "verbatim"


class KnownConflict(BaseModel):
    id: str = Field(min_length=3)
    engine_models: list[str] = Field(min_length=1)
    topic: str = Field(min_length=3)
    keywords: list[str] = Field(min_length=2)
    # Фразы в запросе механика, по которым правило срабатывает само (тема противоречия).
    query_keywords: list[str] = Field(default_factory=list)
    refs: list[ConflictRef] = Field(min_length=2)
    safe_rule: str = Field(min_length=3)


class ConflictQuote(BaseModel):
    manual: str
    pdf_page: int
    quote: str


class ConflictNotice(BaseModel):
    """Противоречие, найденное в ходе: что показать механику и что проверить в ответе."""

    id: str
    topic: str
    quotes: list[ConflictQuote]
    safe_rule: str
    # Почему сработало: "pages" (две страницы правила в выдаче), "keywords" (тема в запросе).
    trigger: list[str] = Field(default_factory=list)


class _ConflictFile(BaseModel):
    conflicts: list[KnownConflict] = Field(default_factory=list)


def load_conflicts(path: Path) -> list[KnownConflict]:
    """Правила из YAML. Файла нет — правил нет (агент работает без них, но не падает).

    Отсутствие файла пишем в лог: иначе блоки противоречия пропадают молча.
    """
    if not path.exists():
        logger.warning("файл известных противоречий не найден: %s", path)
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _ConflictFile.model_validate(raw).conflicts


def conflict_triggers(
    conflict: KnownConflict, engine_model: str, query: str, found: list[Fragment]
) -> list[str]:
    """Почему правило сработало в этом ходе. Пусто — не сработало.

    pages: в выдаче хода есть не меньше двух страниц правила (обе формулировки уже в поиске).
    keywords: в запросе механика есть фраза темы (query_keywords). Текст фрагментов не учитываем:
    иначе правило срабатывает на чужие вопросы, где те же слова встречаются в найденных страницах.
    """
    if engine_model not in conflict.engine_models:
        return []
    triggers: list[str] = []
    rule_pages = {(ref.manual, ref.pdf_page) for ref in conflict.refs}
    if len({(f.manual, f.pdf_page) for f in found} & rule_pages) >= 2:
        triggers.append("pages")
    if any(phrase in query.lower() for phrase in conflict.query_keywords):
        triggers.append("keywords")
    return triggers


def matching_conflicts(
    conflicts: list[KnownConflict], engine_model: str, text: str
) -> list[KnownConflict]:
    """Правила, которые срабатывают по одному тексту запроса (без выдачи)."""
    return [
        conflict for conflict in conflicts if conflict_triggers(conflict, engine_model, text, [])
    ]


NUMBER_RE = re.compile(r"\d+(?:[-,.]\d+)*")


def quote_for_ref(conflict: KnownConflict, ref: ConflictRef, fragment: Fragment) -> str | None:
    """Цитата для одной ссылки правила.

    Заданная в правиле цитата отдаётся, только если она подтверждена страницей (check). Без цитаты
    в правиле — предложение из фрагмента. Нет подтверждения — None: ссылку не показываем.
    """
    if ref.quote is None:
        return quote_for(conflict, fragment)
    if ref.check == "verbatim":
        return ref.quote if _flat(ref.quote) in _flat(fragment.text) else None
    page_text = re.sub(r"\s+", "", fragment.text)
    numbers = NUMBER_RE.findall(ref.quote)
    if numbers and all(number in page_text for number in numbers):
        return ref.quote
    return None


def _flat(text: str) -> str:
    """Текст одной строкой: перенос слова по дефису склеиваем, пробелы сводим к одному."""
    return " ".join(HYPHEN_BREAK_RE.sub("", text).split())


def quote_for(conflict: KnownConflict, fragment: Fragment) -> str | None:
    """Предложение из фрагмента, где больше всего ключевых слов правила. Текст — дословно."""
    best: tuple[int, str] | None = None
    for sentence in SENTENCE_SPLIT_RE.split(" ".join(fragment.text.split())):
        clean = " ".join(sentence.split())
        hits = sum(1 for keyword in conflict.keywords if keyword in clean.lower())
        if hits and (best is None or hits > best[0]):
            best = (hits, clean)
    return best[1] if best else None
