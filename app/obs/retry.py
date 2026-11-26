"""Повторы вызовов внешних сервисов за ход агента: копятся в «мешке» хода и попадают в журнал.

Клиенты (модель, ML, ТОиР) не знают о журнале: они вызывают record_retry. Граф агента забирает
записи через take_retries и пишет шаги kind=retry. Мешок привязан к контексту хода через
ContextVar, поэтому его видят и потоки предзагрузки (copy_context в графе).
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from app.obs.failure import describe_failure

logger = logging.getLogger("app.retry")


@dataclass(frozen=True)
class RetryEvent:
    service: str
    attempt: int
    pause_s: float
    error_class: str
    error_message: str


_sink: ContextVar[list[RetryEvent] | None] = ContextVar("retry_sink", default=None)


@contextmanager
def retry_sink() -> Iterator[list[RetryEvent]]:
    """Открывает мешок повторов на время хода. Вне хода record_retry только пишет в лог."""
    events: list[RetryEvent] = []
    token = _sink.set(events)
    try:
        yield events
    finally:
        _sink.reset(token)


def record_retry(service: str, exc: BaseException, attempt: int, pause_s: float) -> None:
    failure = describe_failure(exc)
    logger.warning(
        "повтор %s: попытка %d упала (%s), пауза %.1f с",
        service,
        attempt,
        failure.error_class,
        pause_s,
    )
    events = _sink.get()
    if events is not None:
        events.append(
            RetryEvent(
                service=service,
                attempt=attempt,
                pause_s=pause_s,
                error_class=failure.error_class,
                error_message=failure.error_message,
            )
        )


def take_retries() -> list[RetryEvent]:
    """Забирает накопленные повторы и очищает мешок."""
    events = _sink.get()
    if not events:
        return []
    taken = list(events)
    events.clear()
    return taken
