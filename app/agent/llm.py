"""Вызов модели агента через openai SDK (Neuraldeep, ТЗ §9): стрим, TTFT, токены, ток/с.

На каждый вызов отдаём ttft_ms, токены и tok_per_s (ТЗ §9, требование скорости > 20 ток/с).
При ошибке основной модели пробуем AGENT_FALLBACK_MODEL, если она задана и отличается.
"""

import time
from collections.abc import Callable
from typing import Any, Protocol

from openai import APIConnectionError, InternalServerError, OpenAI, OpenAIError
from pydantic import BaseModel

from app.obs.retry import record_retry

CHARS_PER_TOKEN_ESTIMATE = 3  # грубая оценка, если сервер не вернул usage
MAX_ATTEMPTS = 2  # одна попытка и один повтор при 5xx, таймауте или обрыве соединения
RETRY_PAUSE_S = 2.0


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class LlmReply(BaseModel):
    content: str
    tool_calls: list[ToolCall]
    model: str
    prompt_tokens: int
    completion_tokens: int
    ttft_ms: int | None
    tok_per_s: float | None
    ms: int


class LlmError(Exception):
    """Модель недоступна или ответила с ошибкой. Текст для пользователя — user_message."""

    user_message = "Модель временно недоступна, повторите запрос."


def root_cause(exc: BaseException) -> BaseException:
    """Исходная ошибка SDK для LlmError: в журнал пишем её класс, а не общий LlmError."""
    if isinstance(exc, LlmError) and exc.__cause__ is not None:
        return exc.__cause__
    return exc


class ChatModel(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_token: Callable[[str], None] | None,
        timeout_s: float,
    ) -> LlmReply: ...


class NeuraldeepChat:
    def __init__(self, api_key: str, base_url: str, model: str, fallback_model: str) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self._model = model
        self._fallback = fallback_model

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_token: Callable[[str], None] | None,
        timeout_s: float,
    ) -> LlmReply:
        emitted = [False]  # есть ли уже отданный механику текст: тогда повтор не делаем

        def watch(text: str) -> None:
            emitted[0] = True
            if on_token is not None:
                on_token(text)

        try:
            return self._call(self._model, messages, tools, watch, timeout_s, emitted)
        except OpenAIError as exc:
            if not self._fallback or self._fallback == self._model:
                raise LlmError(f"модель недоступна: {type(exc).__name__}") from exc
        try:
            return self._call(self._fallback, messages, tools, watch, timeout_s, emitted)
        except OpenAIError as exc:
            raise LlmError(f"запасная модель недоступна: {type(exc).__name__}") from exc

    def _call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_token: Callable[[str], None],
        timeout_s: float,
        emitted: list[bool],
    ) -> LlmReply:
        attempt = 1
        while True:
            try:
                return self._stream(model, messages, tools, on_token, timeout_s)
            except OpenAIError as exc:
                if attempt >= MAX_ATTEMPTS or emitted[0] or not _retryable(exc):
                    raise
                record_retry("neuraldeep", exc, attempt, RETRY_PAUSE_S)
                time.sleep(RETRY_PAUSE_S)
                attempt += 1

    def _stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_token: Callable[[str], None] | None,
        timeout_s: float,
    ) -> LlmReply:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "timeout": timeout_s,
        }
        if tools:
            kwargs["tools"] = tools
        started = time.monotonic()
        first: float | None = None
        text_parts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        usage: Any = None
        stream = self._client.chat.completions.create(**kwargs)
        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = delta.content or ""
            deltas = delta.tool_calls or []
            if (text or deltas) and first is None:
                first = time.monotonic()
            if text:
                text_parts.append(text)
                if on_token is not None:
                    on_token(text)
            for item in deltas:
                entry = calls.setdefault(item.index, {"id": "", "name": "", "arguments": ""})
                if item.id:
                    entry["id"] = item.id
                if item.function is not None:
                    entry["name"] += item.function.name or ""
                    entry["arguments"] += item.function.arguments or ""
        ended = time.monotonic()
        content = "".join(text_parts)
        completion = _count(usage, "completion_tokens", content)
        prompt = _count(usage, "prompt_tokens", _messages_text(messages))
        ttft_ms = None if first is None else int((first - started) * 1000)
        tok_per_s = None
        if first is not None and completion > 0 and ended > first:
            tok_per_s = round(completion / (ended - first), 2)
        return LlmReply(
            content=content,
            tool_calls=[
                ToolCall(id=entry["id"], name=entry["name"], arguments=entry["arguments"] or "{}")
                for _, entry in sorted(calls.items())
            ],
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            ttft_ms=ttft_ms,
            tok_per_s=tok_per_s,
            ms=int((ended - started) * 1000),
        )


def _retryable(exc: OpenAIError) -> bool:
    """Повтор только при обрыве, таймауте (наследник APIConnectionError) и 5xx. 4xx не повторяем."""
    return isinstance(exc, (APIConnectionError, InternalServerError))


def _count(usage: Any, field: str, fallback_text: str) -> int:
    value = getattr(usage, field, None) if usage is not None else None
    if isinstance(value, int):
        return value
    return max(1, len(fallback_text) // CHARS_PER_TOKEN_ESTIMATE) if fallback_text else 0


def _messages_text(messages: list[dict[str, Any]]) -> str:
    return "".join(str(message.get("content") or "") for message in messages)
