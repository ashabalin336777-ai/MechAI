"""HTTP-слой агента: SSE-чат, кнопка диагностики, подтверждение заявки (ТЗ §14, F7)."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.agent_helpers import (
    DIAG_SESSION,
    DIAG_VEHICLE,
    ScriptedChat,
    make_ready_draft,
    make_services,
    reply,
)
from tests.helpers import VEHICLES_PATH


@pytest.fixture
def make_app() -> Iterator[Any]:
    def build(llm: ScriptedChat) -> FastAPI:
        app = create_app(Settings(vehicles_path=VEHICLES_PATH))
        app.state.agent = make_services(llm)
        return app

    yield build


def _events(body: str) -> list[tuple[str, dict]]:
    """Разбор потока SSE: пары (событие, данные)."""
    parsed = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        name = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        parsed.append((name, data))
    return parsed


def test_chat_streams_verdict_and_final_answer(make_app: Any) -> None:
    llm = ScriptedChat(
        [
            reply(
                calls=[("get_diagnosis", {"vehicle_id": DIAG_VEHICLE, "session_id": DIAG_SESSION})]
            ),
            reply(content="Вердикт: отклонение, приоритет high."),
        ]
    )
    client = TestClient(make_app(llm))

    response = client.post(
        "/api/chat",
        json={
            "vehicle_id": DIAG_VEHICLE,
            "session_id": DIAG_SESSION,
            "message": "Что с машиной?",
            "ui_mode": "novice",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    names = [name for name, _ in _events(response.text)]
    assert "verdict" in names
    assert "answer_final" in names
    assert "meta" in names
    assert names[-1] == "done"
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "ui_mode = novice" in prompt


def test_diagnosis_button_runs_get_diagnosis(make_app: Any) -> None:
    llm = ScriptedChat(
        [
            reply(
                calls=[("get_diagnosis", {"vehicle_id": DIAG_VEHICLE, "session_id": DIAG_SESSION})]
            ),
            reply(content="Отклонение F02, приоритет high."),
        ]
    )
    client = TestClient(make_app(llm))

    response = client.post(
        "/api/action/get_diagnosis",
        json={"vehicle_id": DIAG_VEHICLE, "session_id": DIAG_SESSION},
    )

    assert response.status_code == 200
    names = [name for name, _ in _events(response.text)]
    assert "verdict" in names


def test_chat_unknown_vehicle_is_not_found(make_app: Any) -> None:
    client = TestClient(make_app(ScriptedChat([])))
    response = client.post(
        "/api/chat",
        json={"vehicle_id": "X000XX00", "session_id": "S-9001", "message": "Привет"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Машина не найдена."


def test_chat_rejects_empty_message(make_app: Any) -> None:
    client = TestClient(make_app(ScriptedChat([])))
    response = client.post(
        "/api/chat",
        json={"vehicle_id": DIAG_VEHICLE, "session_id": DIAG_SESSION, "message": ""},
    )
    assert response.status_code == 422


def test_confirm_unknown_draft_is_404(make_app: Any) -> None:
    client = TestClient(make_app(ScriptedChat([])))
    response = client.post(
        "/api/tickets/confirm",
        json={"draft_id": "DR-нет", "confirm_token": "токен"},
    )
    assert response.status_code == 404
    assert "не найден" in response.json()["detail"]


def test_confirm_wrong_token_is_403(make_app: Any) -> None:
    app = make_app(ScriptedChat([]))
    draft_id, _ = make_ready_draft(app.state.agent)
    client = TestClient(app)
    response = client.post(
        "/api/tickets/confirm",
        json={"draft_id": draft_id, "confirm_token": "неверный"},
    )
    assert response.status_code == 403


def test_confirm_creates_once_then_returns_200(make_app: Any) -> None:
    app = make_app(ScriptedChat([]))
    draft_id, token = make_ready_draft(app.state.agent)
    client = TestClient(app)

    created = client.post(
        "/api/tickets/confirm", json={"draft_id": draft_id, "confirm_token": token}
    )
    repeated = client.post(
        "/api/tickets/confirm", json={"draft_id": draft_id, "confirm_token": token}
    )

    assert created.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json()["ticket_id"] == created.json()["ticket_id"]
    assert len(app.state.agent.deps.store.list_tickets(DIAG_VEHICLE)) == 1


def test_confirm_requires_token_field(make_app: Any) -> None:
    client = TestClient(make_app(ScriptedChat([])))
    response = client.post("/api/tickets/confirm", json={"draft_id": "DR-1"})
    assert response.status_code == 422
