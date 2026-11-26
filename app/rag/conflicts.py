"""Известные противоречия в руководствах (правила заказчика, data/known_conflicts.yaml).

Код сам не решает, какая формулировка верна: он показывает обе со ссылками и безопасное правило
заказчика. Совпадение — по ключевым словам в запросе механика и в найденных фрагментах.
"""

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.rag.search import Fragment

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;])\s+|\n+")


class ConflictRef(BaseModel):
    manual: str = Field(min_length=3)
    pdf_page: int = Field(ge=1)


class KnownConflict(BaseModel):
    id: str = Field(min_length=3)
    engine_models: list[str] = Field(min_length=1)
    topic: str = Field(min_length=3)
    keywords: list[str] = Field(min_length=2)
    min_matches: int = Field(default=2, ge=1)
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


class _ConflictFile(BaseModel):
    conflicts: list[KnownConflict] = Field(default_factory=list)


def load_conflicts(path: Path) -> list[KnownConflict]:
    """Правила из YAML. Файла нет — правил нет (агент работает без них, но не падает)."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _ConflictFile.model_validate(raw).conflicts


def matching_conflicts(
    conflicts: list[KnownConflict], engine_model: str, text: str
) -> list[KnownConflict]:
    lowered = text.lower()
    return [
        conflict
        for conflict in conflicts
        if engine_model in conflict.engine_models
        and sum(1 for keyword in conflict.keywords if keyword in lowered) >= conflict.min_matches
    ]


def quote_for(conflict: KnownConflict, fragment: Fragment) -> str | None:
    """Предложение из фрагмента, где больше всего ключевых слов правила. Текст — дословно."""
    best: tuple[int, str] | None = None
    for sentence in SENTENCE_SPLIT_RE.split(fragment.text):
        clean = " ".join(sentence.split())
        hits = sum(1 for keyword in conflict.keywords if keyword in clean.lower())
        if hits and (best is None or hits > best[0]):
            best = (hits, clean)
    return best[1] if best else None
