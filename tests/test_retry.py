"""Повторы: модель (5xx, таймаут, обрыв до первого токена) и клиенты ML/ТОиР.

Сеть не трогаем: SDK и httpx подменены заготовками. Пауза 2 с проверяется через подмену sleep.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import httpx2
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    OpenAIError,
)

from app.agent.llm import LlmError, NeuraldeepChat
from app.clients.errors import NotFound, Unavailable, ValidationFailed
from app.clients.ml_client import MlClient
from app.clients.toir_client import Reference, TicketRequest, ToirClient
from app.obs.retry import retry_sink
from tests.helpers import STUB_BASE

DIAG_OK = {
    "vehicle_id": "TST-B002",
    "session_id": "S-9005",
    "status": "normal",
    "anomaly_type": None,
    "anomaly_title": None,
    "anomaly_score": None,
    "confidence": None,
    "signal_quality": "good",
    "description": "норма",
    "model_version": "stub",
}
TICKET_OK = {"ticket_id": "T-1", "status": "created"}


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Пауза между попытками записывается, но не ждётся."""
    recorded: list[float] = []
    monkeypatch.setattr("time.sleep", recorded.append)
    return recorded


# --- Модель ----------------------------------------------------------------------------------


def _req() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.example/v1/chat/completions")


def _status_error(code: int) -> Exception:
    response = httpx2.Response(code, request=_req())
    if code >= 500:
        return InternalServerError("сбой на стороне сервиса", response=response, body=None)
    return BadRequestError("плохой запрос", response=response, body=None)


def _text(content: str) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def _broken_after_text() -> Iterator[Any]:
    yield _text("часть ответа")
    raise APIConnectionError(request=_req())


class _PerModel:
    """Сценарии ответов по моделям: исключение или список чанков на каждую попытку."""

    def __init__(self, scripts: dict[str, list[Any]]) -> None:
        self._scripts = {name: list(items) for name, items in scripts.items()}
        self.models: list[str] = []

    def create(self, **kwargs: Any) -> Any:
        model = kwargs["model"]
        self.models.append(model)
        outcome = self._scripts[model].pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return iter(outcome) if not isinstance(outcome, Iterator) else outcome


def _chat(scripts: dict[str, list[Any]], fallback: str = "fallback") -> tuple[Any, _PerModel]:
    chat = NeuraldeepChat(
        api_key="test", base_url="http://localhost", model="primary", fallback_model=fallback
    )
    completions = _PerModel(scripts)
    chat._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[assignment]
    return chat, completions


def _complete(chat: Any) -> Any:
    return chat.complete([{"role": "user", "content": "вопрос"}], None, None, 30)


def test_model_timeout_is_retried_once_on_same_model(sleeps: list[float]) -> None:
    timeout = APITimeoutError(request=_req())
    chat, models = _chat({"primary": [timeout, [_text("ок")]]})

    with retry_sink() as events:
        reply = _complete(chat)

    assert models.models == ["primary", "primary"]
    assert reply.model == "primary"
    assert sleeps == [2.0]
    assert [(e.service, e.attempt, e.error_class) for e in events] == [
        ("neuraldeep", 1, "APITimeoutError")
    ]


def test_server_error_is_retried_once(sleeps: list[float]) -> None:
    chat, models = _chat({"primary": [_status_error(503), [_text("ок")]]})

    reply = _complete(chat)

    assert models.models == ["primary", "primary"]
    assert reply.content == "ок"
    assert sleeps == [2.0]


def test_server_error_twice_moves_to_fallback(sleeps: list[float]) -> None:
    chat, models = _chat(
        {"primary": [_status_error(500), _status_error(502)], "fallback": [[_text("запасной")]]}
    )

    reply = _complete(chat)

    assert models.models == ["primary", "primary", "fallback"]
    assert reply.model == "fallback"


def test_bad_request_is_not_retried(sleeps: list[float]) -> None:
    chat, models = _chat({"primary": [_status_error(400)], "fallback": [[_text("запасной")]]})

    _complete(chat)

    assert models.models == ["primary", "fallback"]
    assert sleeps == []


def test_connection_break_after_text_is_not_retried(sleeps: list[float]) -> None:
    """Текст уже отдан механику: повтор задвоил бы ответ в потоке, поэтому не повторяем."""
    chat, models = _chat({"primary": [_broken_after_text()], "fallback": [[_text("запасной")]]})
    tokens: list[str] = []

    chat.complete([{"role": "user", "content": "вопрос"}], None, tokens.append, 30)

    assert models.models == ["primary", "fallback"]
    assert sleeps == []


def test_retry_stops_after_second_attempt() -> None:
    timeout = APITimeoutError(request=_req())
    chat, models = _chat({"primary": [timeout, timeout]}, fallback="primary")

    with pytest.raises(LlmError):
        _complete(chat)

    assert models.models == ["primary", "primary"]


def test_openai_error_without_retry_class_is_not_retried(sleeps: list[float]) -> None:
    chat, models = _chat({"primary": [OpenAIError("странная ошибка")], "fallback": [[_text("ок")]]})

    _complete(chat)

    assert models.models == ["primary", "fallback"]
    assert sleeps == []


# --- Клиенты ML и ТОиР -----------------------------------------------------------------------


class _Scripted:
    """Ответы httpx по очереди: объект ответа или исключение транспорта."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def request(self, method: str, url: str, json: object = None) -> httpx.Response:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _ticket() -> TicketRequest:
    return TicketRequest(
        vehicle_id="TST-B002",
        session_id="S-9005",
        anomaly_type="F08",
        conclusion="Тестовая заявка",
        urgency="medium",
        operations=["Проверить топливоподачу"],
        spare_parts=[],
        references=[Reference(manual="236-3902150-Б РЭ", pdf_page=1)],
    )


def test_diagnose_retries_once_on_503(sleeps: list[float]) -> None:
    http = _Scripted([httpx.Response(503), httpx.Response(200, json=DIAG_OK)])
    client = MlClient(STUB_BASE, http=http)  # type: ignore[arg-type]

    with retry_sink() as events:
        result = client.diagnose("TST-B002", "S-9005")

    assert result.status == "normal"
    assert http.calls == 2
    assert sleeps == [2.0]
    assert [(e.service, e.error_class) for e in events] == [("mock_ml", "Unavailable")]


def test_diagnose_retries_on_timeout(sleeps: list[float]) -> None:
    http = _Scripted([httpx.ReadTimeout("медленно"), httpx.Response(200, json=DIAG_OK)])
    client = MlClient(STUB_BASE, http=http)  # type: ignore[arg-type]

    client.diagnose("TST-B002", "S-9005")

    assert http.calls == 2


def test_diagnose_gives_up_after_two_server_errors(sleeps: list[float]) -> None:
    http = _Scripted([httpx.Response(503), httpx.Response(503)])
    client = MlClient(STUB_BASE, http=http)  # type: ignore[arg-type]

    with pytest.raises(Unavailable):
        client.diagnose("TST-B002", "S-9005")
    assert http.calls == 2


@pytest.mark.parametrize(("status", "error"), [(404, NotFound), (422, ValidationFailed)])
def test_diagnose_client_errors_are_not_retried(
    status: int, error: type, sleeps: list[float]
) -> None:
    http = _Scripted([httpx.Response(status)])
    client = MlClient(STUB_BASE, http=http)  # type: ignore[arg-type]

    with pytest.raises(error):
        client.diagnose("TST-B002", "S-9005")
    assert http.calls == 1
    assert sleeps == []


def test_ticket_is_not_retried_on_server_error(sleeps: list[float]) -> None:
    http = _Scripted([httpx.Response(503)])
    client = ToirClient(STUB_BASE, http=http)  # type: ignore[arg-type]

    with pytest.raises(Unavailable):
        client.create_ticket(_ticket())
    assert http.calls == 1


def test_ticket_is_not_retried_on_timeout(sleeps: list[float]) -> None:
    """Таймаут после отправки: заявка могла уже создаться, повтор создал бы дубль."""
    http = _Scripted([httpx.ReadTimeout("медленно")])
    client = ToirClient(STUB_BASE, http=http)  # type: ignore[arg-type]

    with pytest.raises(Unavailable):
        client.create_ticket(_ticket())
    assert http.calls == 1


def test_ticket_is_retried_when_connection_was_refused(sleeps: list[float]) -> None:
    """Соединение не установлено: запрос не дошёл до сервиса, повтор безопасен."""
    http = _Scripted([httpx.ConnectError("refused"), httpx.Response(201, json=TICKET_OK)])
    client = ToirClient(STUB_BASE, http=http)  # type: ignore[arg-type]

    result = client.create_ticket(_ticket())

    assert result.ticket_id == "T-1"
    assert http.calls == 2


def test_health_is_not_retried(sleeps: list[float]) -> None:
    http = _Scripted([httpx.ConnectError("refused")])
    client = ToirClient(STUB_BASE, http=http)  # type: ignore[arg-type]

    assert client.health() is False
    assert http.calls == 1
