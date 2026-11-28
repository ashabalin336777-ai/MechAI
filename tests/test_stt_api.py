"""POST /api/stt: голос без хранения аудио, язык, журнал шага stt, понятные ошибки (ТЗ §10).

Клиент распознавания подменён: в тестах нет сети и ключей. Журнал — MemoryJournal из приложения.
"""

import logging
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.clients.stt_client import UNAVAILABLE_MESSAGE, SttError, Transcript
from tests.agent_helpers import DIAG_SESSION, DIAG_VEHICLE

CONSENT = "2026-11-28T08:40:00+07:00"
MAX_BYTES = 10 * 1024 * 1024
TEXT = "Проверьте тепловой зазор."


class FakeStt:
    model = "whisper-1"

    def __init__(self, result: Transcript | None = None, error: SttError | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[int, str]] = []
        self.languages: list[str | None] = []

    def transcribe(self, audio: bytes, filename: str, language: str | None) -> Transcript:
        self.calls.append((len(audio), filename))
        self.languages.append(language)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@pytest.fixture
def app(app_with_stubs: FastAPI) -> FastAPI:
    app_with_stubs.state.stt_client = FakeStt(
        result=Transcript(text=TEXT, duration_s=12.5, language="ru")
    )
    return app_with_stubs


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _post(
    client: TestClient,
    *,
    audio: bytes = b"\x1aE\xdf\xa3voice",
    mime: str = "audio/webm;codecs=opus",
    consent: str = CONSENT,
    lang: str | None = None,
) -> Any:
    data = {"consent_at": consent, "vehicle_id": DIAG_VEHICLE, "session_id": DIAG_SESSION}
    if lang is not None:
        data["lang"] = lang
    return client.post(
        "/api/stt",
        data=data,
        files={"audio": ("voice-record", audio, mime)},
    )


def _voice_step(app: FastAPI) -> Any:
    journal = app.state.agent.journal
    return next(step for step in journal.steps if step.kind == "stt")


def test_transcript_goes_back_as_text_and_run_is_marked_voice(
    client: TestClient, app: FastAPI
) -> None:
    response = _post(client)

    assert response.status_code == 200
    assert response.json() == {"text": TEXT, "duration_s": 12.5, "language": "ru"}
    journal = app.state.agent.journal
    run_id = next(iter(journal.input_modes))
    assert journal.input_modes[run_id] == "voice"
    run = journal.runs[run_id]
    assert run.status == "ok"
    assert run.cost_rub == Decimal("0.2083")


def test_journal_step_has_no_audio_bytes(client: TestClient, app: FastAPI) -> None:
    _post(client)

    step = _voice_step(app)
    assert step.name == "whisper-1"
    assert step.input == {"model": "whisper-1", "language": "ru", "bytes": 9, "mime": "audio/webm"}
    assert step.output == {"chars": len(TEXT), "duration_s": 12.5, "language": "ru"}
    assert step.error is None
    assert all(not isinstance(value, bytes) for value in step.input.values())


def test_default_language_comes_from_settings(client: TestClient, app: FastAPI) -> None:
    _post(client)

    assert app.state.stt_client.languages == ["ru"]


def test_empty_setting_means_autodetect(client: TestClient, app: FastAPI) -> None:
    app.state.settings = app.state.settings.model_copy(update={"stt_language": ""})
    app.state.stt_client = FakeStt(result=Transcript(text=TEXT, duration_s=3.0, language="uz"))

    response = _post(client)

    assert app.state.stt_client.languages == [None]
    assert response.json()["language"] == "uz"
    assert _voice_step(app).input is not None
    assert _voice_step(app).input["language"] == "auto"


def test_form_language_overrides_setting(client: TestClient, app: FastAPI) -> None:
    app.state.stt_client = FakeStt(result=Transcript(text="Тест", duration_s=3.0, language=None))

    response = _post(client, lang="kk")

    assert app.state.stt_client.languages == ["kk"]
    assert response.json()["language"] == "kk"


def test_detected_language_is_returned_and_journaled(client: TestClient, app: FastAPI) -> None:
    app.state.stt_client = FakeStt(result=Transcript(text="Сәлем", duration_s=2.0, language="kk"))

    response = _post(client, lang="kk")

    assert response.json()["language"] == "kk"
    assert _voice_step(app).output == {"chars": 5, "duration_s": 2.0, "language": "kk"}


def test_unsupported_language_is_rejected_before_recognition(
    client: TestClient, app: FastAPI
) -> None:
    response = _post(client, lang="fr")

    assert response.status_code == 422
    assert "не поддерживается" in response.json()["detail"]
    assert app.state.stt_client.calls == []


def test_audio_is_sent_to_the_client_only(client: TestClient, app: FastAPI) -> None:
    _post(client, audio=b"x" * 2048)

    assert app.state.stt_client.calls == [(2048, "voice.webm")]


def test_empty_recording_is_rejected_before_journal(client: TestClient, app: FastAPI) -> None:
    response = _post(client, audio=b"")

    assert response.status_code == 422
    assert "Запись пустая" in response.json()["detail"]
    assert app.state.agent.journal.input_modes == {}


def test_oversized_recording_is_rejected(client: TestClient, app: FastAPI) -> None:
    response = _post(client, audio=b"x" * (MAX_BYTES + 1))

    assert response.status_code == 413
    assert "10 МБ" in response.json()["detail"]
    assert app.state.stt_client.calls == []


def test_unknown_format_is_rejected(client: TestClient, app: FastAPI) -> None:
    response = _post(client, audio=b"hello", mime="text/plain")

    assert response.status_code == 415
    assert app.state.stt_client.calls == []


def test_missing_consent_is_rejected(client: TestClient, app: FastAPI) -> None:
    response = _post(client, consent="")

    assert response.status_code == 422
    assert "согласие" in response.json()["detail"]
    assert app.state.stt_client.calls == []


def test_recording_longer_than_thirty_seconds_is_rejected(client: TestClient, app: FastAPI) -> None:
    app.state.stt_client = FakeStt(
        result=Transcript(text="Длинная запись", duration_s=45.0, language="ru")
    )

    response = _post(client)

    assert response.status_code == 422
    assert "длиннее 30 секунд" in response.json()["detail"]
    journal = app.state.agent.journal
    run = next(iter(journal.runs.values()))
    assert run.status == "error"
    assert _voice_step(app).error_message == "too_long"


def test_service_failure_is_a_russian_503_and_is_journaled(
    client: TestClient, app: FastAPI
) -> None:
    app.state.stt_client = FakeStt(error=SttError(503, UNAVAILABLE_MESSAGE, "APIConnectionError"))

    response = _post(client)

    assert response.status_code == 503
    assert response.json()["detail"] == UNAVAILABLE_MESSAGE
    step = _voice_step(app)
    assert step.error_class == "SttError"
    assert step.error_message == "APIConnectionError"
    assert "sk-" not in str(step.input)


def test_silence_returns_empty_text_without_error(client: TestClient, app: FastAPI) -> None:
    app.state.stt_client = FakeStt(result=Transcript(text="", duration_s=2.0, language="ru"))

    response = _post(client)

    assert response.status_code == 200
    assert response.json()["text"] == ""


def test_journal_failure_does_not_lose_the_transcript(
    client: TestClient,
    app: FastAPI,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(**_: Any) -> int:
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(app.state.agent.journal, "start_run", down)

    with caplog.at_level(logging.ERROR, logger="app"):
        response = _post(client)

    assert response.status_code == 200
    assert response.json()["text"] == TEXT
    assert "журнал голоса: ход не записан" in caplog.text
    assert "connection refused" in caplog.text
