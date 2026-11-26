"""Адаптер модели (openai SDK, стрим): текст, дельты tool_calls, usage, запасная модель.

Сеть не трогаем: клиент SDK подменён объектом, который отдаёт заготовленные чанки.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAIError

from app.agent.llm import NeuraldeepChat


def _chunk(
    content: str | None = None, tool_calls: list[Any] | None = None, usage: Any = None
) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choices = [SimpleNamespace(delta=delta)] if (content is not None or tool_calls) else []
    return SimpleNamespace(choices=choices, usage=usage)


def _call(index: int, call_id: str | None, name: str | None, arguments: str | None) -> Any:
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class _FakeCompletions:
    def __init__(self, scripts: dict[str, Any]) -> None:
        self._scripts = scripts
        self.models: list[str] = []

    def create(self, **kwargs: Any) -> Any:
        model = kwargs["model"]
        self.models.append(model)
        script = self._scripts[model]
        if isinstance(script, Exception):
            raise script
        return iter(script)


def _chat(
    scripts: dict[str, Any], fallback: str = "fallback"
) -> tuple[NeuraldeepChat, _FakeCompletions]:
    chat = NeuraldeepChat(
        api_key="test", base_url="http://localhost", model="primary", fallback_model=fallback
    )
    completions = _FakeCompletions(scripts)
    chat._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[assignment]
    return chat, completions


def test_text_stream_collects_tokens_and_estimates_usage() -> None:
    chat, _ = _chat({"primary": [_chunk("Момент "), _chunk("150 Н·м")]})
    tokens: list[str] = []

    reply = chat.complete([{"role": "user", "content": "привет"}], None, tokens.append, 10)

    assert tokens == ["Момент ", "150 Н·м"]
    assert reply.content == "Момент 150 Н·м"
    assert reply.tool_calls == []
    assert reply.model == "primary"
    assert reply.ttft_ms is not None
    assert reply.completion_tokens > 0
    assert reply.prompt_tokens > 0


def test_tool_call_arguments_are_joined_across_deltas() -> None:
    chunks = [
        _chunk(tool_calls=[_call(0, "call_a", "get_diagnosis", '{"vehicle_id": ')]),
        _chunk(tool_calls=[_call(0, None, None, '"T792HO98", "session_id": "S-0043"}')]),
    ]
    chat, _ = _chat({"primary": chunks})

    reply = chat.complete(
        [{"role": "user", "content": "что с машиной"}], [{"type": "function"}], None, 10
    )

    assert len(reply.tool_calls) == 1
    call = reply.tool_calls[0]
    assert call.id == "call_a"
    assert call.name == "get_diagnosis"
    assert call.arguments == '{"vehicle_id": "T792HO98", "session_id": "S-0043"}'


def test_usage_chunk_overrides_estimate() -> None:
    usage = SimpleNamespace(prompt_tokens=321, completion_tokens=45)
    chat, _ = _chat({"primary": [_chunk("ок"), _chunk(usage=usage)]})

    reply = chat.complete([{"role": "user", "content": "x"}], None, None, 10)

    assert reply.prompt_tokens == 321
    assert reply.completion_tokens == 45


def test_fallback_model_is_used_when_primary_fails() -> None:
    chat, completions = _chat(
        {"primary": OpenAIError("сервис недоступен"), "fallback": [_chunk("запасной ответ")]}
    )

    reply = chat.complete([{"role": "user", "content": "x"}], None, None, 10)

    assert completions.models == ["primary", "fallback"]
    assert reply.model == "fallback"
    assert reply.content == "запасной ответ"


def test_error_on_both_models_becomes_llm_error() -> None:
    from app.agent.llm import LlmError

    chat, _ = _chat({"primary": OpenAIError("а"), "fallback": OpenAIError("б")})

    with pytest.raises(LlmError):
        chat.complete([{"role": "user", "content": "x"}], None, None, 10)
