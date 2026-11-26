"""Журнал ошибок агента: класс и текст сбоя хода и вызова модели, шаги retry, таймаут 15 с.

Модель подменена заготовками (ScriptedChat), инструменты ходят в заглушки mock/.
"""

import dataclasses
from typing import Any

import httpx2
from openai import APITimeoutError

from app.agent import graph as graph_module
from app.agent.llm import LlmError
from app.agent.runner import GENERIC_ERROR, TurnRequest, load_base_prompt, run_turn
from app.clients.errors import Unavailable
from app.obs.journal import MemoryJournal
from app.obs.retry import record_retry
from tests.agent_helpers import (
    DIAG_SESSION,
    DIAG_VEHICLE,
    ScriptedChat,
    make_services,
    reply,
)


class _FailingChat:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    def complete(self, messages: Any, tools: Any, on_token: Any, timeout_s: float) -> Any:
        raise self._error


class _TimeoutRecordingChat(ScriptedChat):
    def __init__(self, replies: list[Any]) -> None:
        super().__init__(replies)
        self.timeouts: list[float] = []

    def complete(self, messages: Any, tools: Any, on_token: Any, timeout_s: float) -> Any:
        self.timeouts.append(timeout_s)
        return super().complete(messages, tools, on_token, timeout_s)


class _RetryingChat(ScriptedChat):
    """Перед ответом пишет повтор, как это делает клиент модели внутри вызова."""

    def complete(self, messages: Any, tools: Any, on_token: Any, timeout_s: float) -> Any:
        cause = APITimeoutError(request=httpx2.Request("POST", "https://api.example/v1"))
        record_retry("neuraldeep", cause, 1, 2.0)
        return super().complete(messages, tools, on_token, timeout_s)


def _turn() -> TurnRequest:
    return TurnRequest(
        vehicle_id=DIAG_VEHICLE,
        session_id=DIAG_SESSION,
        message="Что с машиной?",
        user_action=None,
        ui_mode="standard",
        lang="ru",
    )


def _run(services: Any) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    run_turn(services, _turn(), load_base_prompt(), lambda name, data: events.append((name, data)))
    return events


def _steps(journal: MemoryJournal, kind: str) -> list[Any]:
    return [step for step in journal.steps if step.kind == kind]


def _llm_error(cause: BaseException) -> LlmError:
    error = LlmError("модель недоступна: APITimeoutError")
    error.__cause__ = cause
    return error


def test_model_timeout_is_journaled_with_class_and_timeout() -> None:
    cause = APITimeoutError(request=httpx2.Request("POST", "https://api.example/v1"))
    services = make_services(_FailingChat(_llm_error(cause)))  # type: ignore[arg-type]

    events = _run(services)

    assert ("error", {"message": GENERIC_ERROR}) in events
    chat_error = next(step for step in _steps(services.journal, "error") if step.name == "chat")
    assert chat_error.error_class == "APITimeoutError"
    assert chat_error.output is not None
    assert chat_error.output["timeout_s"] >= 15.0
    turn_error = next(step for step in _steps(services.journal, "error") if step.name == "turn")
    assert turn_error.error_class == "APITimeoutError"
    run = next(iter(services.journal.runs.values()))
    assert run.status == "error"


def test_secrets_are_removed_from_journal_text() -> None:
    leaked = RuntimeError(
        "ошибка postgresql://gen_user:S3cret@db:5432/app Bearer tok123 password=hunter2"
    )
    services = make_services(_FailingChat(leaked))  # type: ignore[arg-type]

    _run(services)

    turn_error = next(step for step in _steps(services.journal, "error") if step.name == "turn")
    assert turn_error.error_class == "RuntimeError"
    assert turn_error.error_message is not None
    for secret in ("S3cret", "tok123", "hunter2", "gen_user"):
        assert secret not in turn_error.error_message


def test_retry_step_is_written_before_the_model_call_it_belongs_to() -> None:
    llm = _RetryingChat([reply(content="Чем помочь?")])
    services = make_services(llm)  # type: ignore[arg-type]

    _run(services)

    kinds = [step.kind for step in services.journal.steps]
    assert kinds.index("retry") < kinds.index("llm")
    retry = _steps(services.journal, "retry")[0]
    assert retry.name == "neuraldeep"
    assert retry.error_class == "APITimeoutError"
    assert retry.output == {"attempt": 1, "pause_s": 2.0}


def test_retry_inside_prefetch_thread_reaches_journal(monkeypatch: Any) -> None:
    original = graph_module._call_tool

    def flaky(deps: Any, runtime: Any, call: dict[str, Any]) -> Any:
        if call["name"] == "get_history":
            record_retry("mock_ml", Unavailable("mock_ml", "HTTP 503"), 1, 2.0)
        return original(deps, runtime, call)

    monkeypatch.setattr(graph_module, "_call_tool", flaky)
    services = make_services(ScriptedChat([reply(content="Чем помочь?")]))  # type: ignore[arg-type]

    _run(services)

    retries = _steps(services.journal, "retry")
    assert [step.name for step in retries] == ["mock_ml"]
    assert retries[0].error_class == "Unavailable"


def test_failed_tool_records_class_and_message() -> None:
    llm = ScriptedChat([reply(content="Чем помочь?")])
    services = make_services(llm)  # type: ignore[arg-type]

    def broken(runtime: Any, args: Any) -> dict[str, Any]:
        raise ValueError("сломалось на поле engine_model")

    services.registry["get_history"] = dataclasses.replace(
        services.registry["get_history"], run=broken
    )

    _run(services)

    tool = next(
        step
        for step in services.journal.steps
        if step.kind == "tool" and step.name == "get_history"
    )
    assert tool.error is not None and tool.error.startswith("tool_error: ValueError")
    assert tool.error_class == "ValueError"
    assert tool.error_message == "сломалось на поле engine_model"


def test_every_model_call_gets_at_least_fifteen_seconds() -> None:
    llm = _TimeoutRecordingChat([reply(content="Чем помочь?")])
    services = make_services(llm)  # type: ignore[arg-type]

    _run(services)

    assert llm.timeouts and all(timeout >= 15.0 for timeout in llm.timeouts)
    chat = _steps(services.journal, "llm")[0]
    assert chat.output is not None
    assert chat.output["timeout_s"] >= 15.0
    assert "elapsed_s" in chat.output


def test_regenerate_timeout_is_not_fixed_five_seconds() -> None:
    wrong = "Момент затяжки 200 Н·м."  # цифра с единицей без ссылки: нужна перегенерация
    llm = _TimeoutRecordingChat([reply(content=wrong), reply(content="Уточните по руководству.")])
    services = make_services(llm)  # type: ignore[arg-type]

    _run(services)

    assert len(llm.timeouts) == 2
    assert all(timeout >= 15.0 for timeout in llm.timeouts)
