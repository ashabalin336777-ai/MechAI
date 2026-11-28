"""Режим ввода хода агента: text по умолчанию, voice — текст из распознавания речи (ТЗ §10)."""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.agent_helpers import DIAG_SESSION, DIAG_VEHICLE, ScriptedChat, make_services, reply
from tests.helpers import VEHICLES_PATH


@pytest.fixture
def app() -> FastAPI:
    app = create_app(Settings(vehicles_path=VEHICLES_PATH))
    app.state.agent = make_services(ScriptedChat([reply(content="Ответ по запросу.")]))
    return app


def _chat(client: TestClient, **extra: Any) -> Any:
    body = {
        "vehicle_id": DIAG_VEHICLE,
        "session_id": DIAG_SESSION,
        "message": "Какой тепловой зазор?",
        "ui_mode": "standard",
    }
    body.update(extra)
    return client.post("/api/chat", json=body)


def test_voice_turn_is_marked_in_journal(app: FastAPI) -> None:
    response = _chat(TestClient(app), input_mode="voice")

    assert response.status_code == 200
    assert list(app.state.agent.journal.input_modes.values()) == ["voice"]


def test_typed_turn_defaults_to_text(app: FastAPI) -> None:
    response = _chat(TestClient(app))

    assert response.status_code == 200
    assert list(app.state.agent.journal.input_modes.values()) == ["text"]


def test_unknown_input_mode_is_rejected(app: FastAPI) -> None:
    response = _chat(TestClient(app), input_mode="video")

    assert response.status_code == 422
    assert app.state.agent.journal.input_modes == {}
