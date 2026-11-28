"""Клиент распознавания речи: параметры whisper-1, понятные ошибки, стоимость (ТЗ §10).

Сеть не трогаем: SDK openai подменён, ошибки собираем из настоящих классов исключений.
"""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from app.clients.stt_client import (
    MAX_AUDIO_SECONDS,
    TERMS_PROMPT,
    UNAVAILABLE_MESSAGE,
    SttClient,
    SttError,
)
from app.obs.prices import stt_cost_rub

SECRET_KEY = "sk-test-secret-123"
REQUEST = httpx.Request("POST", "https://api.example.invalid/v1/audio/transcriptions")


class FakeTranscriptions:
    def __init__(self, *, result: Any = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def _client_with(fake: FakeTranscriptions) -> SttClient:
    client = SttClient(SECRET_KEY, "https://api.example.invalid/v1", "whisper-1")
    client._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=fake))  # type: ignore[assignment]
    return client


def _verbose(text: str, duration: float | None, language: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(text=text, duration=duration, language=language)


def test_request_asks_whisper_for_the_given_language_with_terms_prompt() -> None:
    fake = FakeTranscriptions(result=_verbose(" Проверьте зазор. ", 3.2, "russian"))
    result = _client_with(fake).transcribe(b"audio-bytes", filename="voice.webm", language="ru")

    call = fake.calls[0]
    assert call["model"] == "whisper-1"
    assert call["language"] == "ru"
    assert call["prompt"] == TERMS_PROMPT
    assert call["response_format"] == "verbose_json"
    assert call["file"] == ("voice.webm", b"audio-bytes")
    assert result.text == "Проверьте зазор."
    assert result.duration_s == pytest.approx(3.2)
    assert result.language == "ru"


def test_no_language_lets_whisper_detect_it() -> None:
    fake = FakeTranscriptions(result=_verbose("Тест", 1.0, "kazakh"))
    result = _client_with(fake).transcribe(b"x", filename="voice.webm", language=None)

    assert fake.calls[0]["language"] is openai.NOT_GIVEN
    assert result.language == "kk"


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("russian", "ru"),
        ("Uzbek", "uz"),
        ("kazakh", "kk"),
        ("tajik", "tg"),
        ("kyrgyz", "ky"),
        ("english", "en"),
        ("uz", "uz"),
        ("klingon", None),
        (None, None),
    ],
)
def test_whisper_language_name_becomes_a_code(name: str | None, code: str | None) -> None:
    fake = FakeTranscriptions(result=_verbose("Тест", 1.0, name))
    assert (
        _client_with(fake).transcribe(b"x", filename="voice.webm", language=None).language == code
    )


def test_missing_duration_is_none() -> None:
    fake = FakeTranscriptions(result=_verbose("Тест", None))
    assert (
        _client_with(fake).transcribe(b"x", filename="voice.webm", language="ru").duration_s is None
    )


def test_timeout_becomes_504_with_russian_message() -> None:
    fake = FakeTranscriptions(error=openai.APITimeoutError(request=REQUEST))
    with pytest.raises(SttError) as caught:
        _client_with(fake).transcribe(b"x", filename="voice.webm", language="ru")
    assert caught.value.status_code == 504
    assert "30 секунд" in caught.value.user_message


@pytest.mark.parametrize("status", [400, 413, 415, 422])
def test_rejected_audio_becomes_422(status: int) -> None:
    response = httpx.Response(status, request=REQUEST)
    fake = FakeTranscriptions(error=openai.APIStatusError("bad", response=response, body=None))
    with pytest.raises(SttError) as caught:
        _client_with(fake).transcribe(b"x", filename="voice.webm", language="ru")
    assert caught.value.status_code == 422
    assert caught.value.detail == f"HTTP {status}"


def test_server_error_becomes_503_without_trace_or_key() -> None:
    response = httpx.Response(500, request=REQUEST)
    fake = FakeTranscriptions(
        error=openai.InternalServerError("boom", response=response, body=None)
    )
    with pytest.raises(SttError) as caught:
        _client_with(fake).transcribe(b"x", filename="voice.webm", language="ru")
    assert caught.value.status_code == 503
    assert caught.value.user_message == UNAVAILABLE_MESSAGE
    assert SECRET_KEY not in str(caught.value)


def test_connection_error_becomes_503() -> None:
    fake = FakeTranscriptions(error=openai.APIConnectionError(request=REQUEST))
    with pytest.raises(SttError) as caught:
        _client_with(fake).transcribe(b"x", filename="voice.webm", language="ru")
    assert caught.value.status_code == 503
    assert caught.value.detail == "APIConnectionError"


def test_limit_is_thirty_seconds() -> None:
    assert MAX_AUDIO_SECONDS == 30.0


def test_stt_cost_is_one_ruble_per_minute() -> None:
    assert stt_cost_rub(60.0) == Decimal("1.0000")
    assert stt_cost_rub(30.0) == Decimal("0.5000")
    assert stt_cost_rub(None) is None
