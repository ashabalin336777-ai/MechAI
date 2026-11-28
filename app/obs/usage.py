"""Расход эмбеддингов и реранка за ход агента: копится в «мешке» хода и попадает в журнал.

Клиенты (эмбеддинги, реранк) не знают о журнале: они вызывают record_usage. Граф агента забирает
записи через take_usage и пишет шаги kind=embed или kind=rerank с ценой из app/obs/prices.py.
Вне хода (ингест, OCR) мешка нет: record_usage ничего не делает. Мешок виден потокам инструментов
через ContextVar и copy_context в графе.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class UsageEvent:
    kind: str  # embed | rerank
    model: str
    prompt_tokens: int | None  # None, если сервис не вернул число токенов
    ms: int


_sink: ContextVar[list[UsageEvent] | None] = ContextVar("usage_sink", default=None)


@contextmanager
def usage_sink() -> Iterator[list[UsageEvent]]:
    """Открывает мешок расхода на время хода."""
    events: list[UsageEvent] = []
    token = _sink.set(events)
    try:
        yield events
    finally:
        _sink.reset(token)


def record_usage(kind: str, model: str, prompt_tokens: int | None, ms: int) -> None:
    events = _sink.get()
    if events is not None:
        events.append(UsageEvent(kind=kind, model=model, prompt_tokens=prompt_tokens, ms=ms))


def take_usage() -> list[UsageEvent]:
    """Забирает накопленный расход и очищает мешок."""
    events = _sink.get()
    if not events:
        return []
    taken = list(events)
    events.clear()
    return taken
