"""Голос в журнале PostgreSQL: ход input_mode=voice и шаг stt видны через PgJournalReader (ТЗ §14).

Запускается, если задан TEST_DATABASE_URL. Строки помечены vehicle_id TEST-STT и удаляются.
Клиент распознавания подменён: сеть не нужна. Сброс схемы не делаем (ALLOW_RESET не нужен).
"""

import os
from collections.abc import Iterator

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.clients.stt_client import Transcript
from app.config import Settings
from app.db.agent_journal import PgJournalReader
from app.db.database import apply_migrations
from app.main import create_app
from tests.helpers import VEHICLES_PATH

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="нужен TEST_DATABASE_URL")
TEST_VEHICLE = "TEST-STT"
CONSENT = "2026-11-28T08:40:00+07:00"
TEXT = "Проверьте ТНВД на ЯМЗ-236."


class FakeStt:
    model = "whisper-1"

    def transcribe(self, audio: bytes, filename: str, language: str | None) -> Transcript:
        return Transcript(text=TEXT, duration_s=1.8, language="ru")


def _cleanup() -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute("DELETE FROM agent_runs WHERE vehicle_id = %s", (TEST_VEHICLE,))


@pytest.fixture
def app() -> Iterator[FastAPI]:
    apply_migrations(TEST_DATABASE_URL)
    _cleanup()
    app = create_app(Settings(database_url=TEST_DATABASE_URL, vehicles_path=VEHICLES_PATH))
    app.state.stt_client = FakeStt()
    yield app
    _cleanup()


def test_voice_run_and_stt_step_are_visible_in_the_journal(app: FastAPI) -> None:
    response = TestClient(app).post(
        "/api/stt",
        data={"consent_at": CONSENT, "vehicle_id": TEST_VEHICLE, "session_id": "S-TEST-STT"},
        files={"audio": ("voice-record", b"voice", "audio/webm;codecs=opus")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == TEXT

    reader = PgJournalReader(TEST_DATABASE_URL)
    runs = [row for row in reader.list_runs(None, 50) if row.vehicle_id == TEST_VEHICLE]
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "ok"
    assert run.input_mode == "voice"
    assert run.lang == "ru"
    steps = reader.list_steps(run.id)
    assert [step.kind for step in steps] == ["stt"]
    assert steps[0].name == "whisper-1"
    assert steps[0].output == {"chars": len(TEXT), "duration_s": 1.8, "language": "ru"}
    assert steps[0].input is not None and "bytes" in steps[0].input
