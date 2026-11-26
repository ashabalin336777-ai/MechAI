"""Класс и краткий текст ошибки для журнала агента. Адреса, пароли и токены вырезаются."""

import re
from dataclasses import dataclass

MESSAGE_LIMIT = 200

_SECRET_PATTERNS = (
    (re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+"), "<адрес скрыт>"),
    (re.compile(r"(?i)\bbearer\s+\S+"), "Bearer <скрыто>"),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization)\b\s*[=:]\s*\S+"
        ),
        r"\1=<скрыто>",
    ),
    (re.compile(r"sk-[A-Za-z0-9_-]{8,}"), "<ключ скрыт>"),
)


@dataclass(frozen=True)
class Failure:
    error_class: str
    error_message: str


def describe_failure(exc: BaseException) -> Failure:
    """Имя класса исключения и первые символы текста без строк подключения и ключей."""
    text = " ".join(str(exc).split())
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return Failure(error_class=type(exc).__name__, error_message=text[:MESSAGE_LIMIT])
