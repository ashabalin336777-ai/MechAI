"""/admin/logs: доступ (404, вход, Bearer, cookie, выход), фильтр, шаги, прогоны, ошибки базы.

Журнал и прогоны здесь в памяти с тем же контрактом, что PgJournalReader и PgEvalRunStore.
Настоящий SQL и только чтение проверяются в tests/test_agent_journal_db.py (TEST_DATABASE_URL).
"""

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.admin_auth import ADMIN_COOKIE
from app.config import Settings
from app.db.agent_journal import AgentRunRow, AgentStepRow
from app.db.eval_runs import EvalRunRecord
from app.main import create_app

TOKEN = "admin-token-for-logs-42"
DB_URL = "postgresql://user:secret@db.example:5432/mechai"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
STARTED = datetime(2026, 11, 27, 9, 30, 0, tzinfo=UTC)  # 16:30 по Новосибирску


class MemoryJournalReader:
    def __init__(self) -> None:
        self.runs = [
            AgentRunRow(
                id=2,
                started_at=STARTED,
                vehicle_id="P456AT178",
                session_id="S-0003",
                status="error",
                total_ms=5300,
                prompt_tokens=6100,
                completion_tokens=420,
                tok_per_s=None,
                cost_rub=None,
            ),
            AgentRunRow(
                id=1,
                started_at=STARTED,
                vehicle_id="M260EH47",
                session_id="S-0001",
                status="ok",
                total_ms=2100,
                prompt_tokens=None,
                completion_tokens=None,
                tok_per_s=None,
                cost_rub=None,
            ),
        ]
        self.steps = [
            AgentStepRow(
                n=1,
                kind="tool",
                name="search_manual",
                ms=120,
                ttft_ms=None,
                prompt_tokens=None,
                completion_tokens=None,
                tok_per_s=None,
                model=None,
                error=None,
                error_class=None,
                error_message=None,
                input={"query": "<script>alert(1)</script>", "engine": "ЯМЗ-236М2"},
                output={"fragments": 3},
            ),
            AgentStepRow(
                n=2,
                kind="error",
                name="chat",
                ms=15000,
                ttft_ms=None,
                prompt_tokens=None,
                completion_tokens=None,
                tok_per_s=None,
                model="qwen3.8-flash-next-ru-noreason",
                error="timeout",
                error_class="TimeoutError",
                error_message="таймаут ответа модели",
                input=None,
                output=None,
            ),
            AgentStepRow(
                n=3,
                kind="guardrail",
                name="raw_answer",
                ms=None,
                ttft_ms=None,
                prompt_tokens=None,
                completion_tokens=None,
                tok_per_s=None,
                model=None,
                error=None,
                error_class=None,
                error_message=None,
                input=None,
                output={"text": "Давление масла: 400 кПа [ЯМЗ-236М2, стр. 280]."},
            ),
        ]
        self.calls: list[tuple[str | None, int]] = []
        self.fail = False

    def list_runs(self, status: str | None, limit: int) -> list[AgentRunRow]:
        self.calls.append((status, limit))
        if self.fail:
            raise psycopg.OperationalError("connection refused")
        rows = [r for r in self.runs if status is None or r.status == status]
        return rows[:limit]

    def get_run(self, run_id: int) -> AgentRunRow | None:
        return next((r for r in self.runs if r.id == run_id), None)

    def list_steps(self, run_id: int) -> list[AgentStepRow]:
        return self.steps if run_id == 2 else []


class MemoryEvalStore:
    def __init__(self) -> None:
        self.rows = {
            1: EvalRunRecord(
                id=1,
                suite="rag",
                commit_sha="6dc4c25",
                status="done",
                started_at=STARTED,
                finished_at=STARTED,
                passed=12,
                total=14,
                error_message=None,
                report_md="# Отчёт RAG\nQ11 PASS\n",
                report_json={"cases": []},
            ),
            2: EvalRunRecord(
                id=2,
                suite="agent",
                commit_sha=None,
                status="error",
                started_at=STARTED,
                finished_at=STARTED,
                passed=None,
                total=None,
                error_message="Модели недоступны",
            ),
        }

    def list_runs(self, limit: int) -> list[EvalRunRecord]:
        newest = sorted(self.rows, reverse=True)[:limit]
        return [self.rows[run_id].model_copy(update={"report_md": None}) for run_id in newest]

    def get_run(self, run_id: int) -> EvalRunRecord | None:
        return self.rows.get(run_id)


def _client(token: str = TOKEN, database_url: str = DB_URL) -> TestClient:
    app = create_app(Settings(admin_token=token, database_url=database_url, mount_mocks=False))
    app.state.journal_reader = MemoryJournalReader() if database_url else None
    app.state.eval_store = MemoryEvalStore()
    return TestClient(app)


def _reader(client: TestClient) -> MemoryJournalReader:
    return client.app.state.journal_reader


def _login(client: TestClient, token: str = TOKEN):
    return client.post(
        "/admin/logs/access",
        content=f"token={token}".encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )


def test_page_is_absent_without_admin_token() -> None:
    client = _client(token="")
    assert client.get("/admin/logs").status_code == 404
    assert client.get("/admin/logs/runs/1").status_code == 404
    assert client.get("/admin/logs/eval/1").status_code == 404
    assert _login(client).status_code == 404


def test_without_access_shows_login_form_not_data() -> None:
    client = _client()
    response = client.get("/admin/logs")
    assert response.status_code == 200
    assert "Вход в журнал агента" in response.text
    assert "P456AT178" not in response.text
    assert _reader(client).calls == []


def test_wrong_login_token_is_rejected_without_cookie() -> None:
    client = _client()
    response = _login(client, token="wrong-token")
    assert response.status_code == 401
    assert "Неверный токен" in response.text
    assert ADMIN_COOKIE not in response.headers.get("set-cookie", "")


def test_login_sets_httponly_cookie_without_token_value() -> None:
    client = _client()
    response = _login(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/logs"
    cookie = response.headers["set-cookie"]
    assert f"{ADMIN_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "samesite=strict" in cookie.lower()
    assert TOKEN not in cookie


def test_login_cookie_opens_runs_list() -> None:
    client = _client()
    _login(client)
    response = client.get("/admin/logs")
    assert response.status_code == 200
    assert "P456AT178" in response.text
    assert "/admin/logs/runs/2" in response.text


def test_bearer_token_opens_page_without_login() -> None:
    client = _client()
    response = client.get("/admin/logs", headers=AUTH)
    assert response.status_code == 200
    assert "M260EH47" in response.text


def test_forged_cookie_is_rejected() -> None:
    client = _client()
    client.cookies.set(ADMIN_COOKIE, "0" * 64)
    response = client.get("/admin/logs")
    assert "Вход в журнал агента" in response.text
    assert _reader(client).calls == []


def test_logout_clears_cookie() -> None:
    client = _client()
    _login(client)
    response = client.post("/admin/logs/logout", follow_redirects=False)
    assert response.status_code == 303
    assert f"{ADMIN_COOKIE}=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.parametrize("status", ["all", "ok", "error", "running"])
def test_status_filter_is_passed_to_reader(status: str) -> None:
    client = _client()
    response = client.get(f"/admin/logs?status={status}", headers=AUTH)
    assert response.status_code == 200
    expected = None if status == "all" else status
    assert _reader(client).calls == [(expected, 50)]


def test_unknown_status_filter_is_rejected() -> None:
    client = _client()
    assert client.get("/admin/logs?status=drop", headers=AUTH).status_code == 422


def test_error_filter_shows_only_error_runs() -> None:
    client = _client()
    response = client.get("/admin/logs?status=error", headers=AUTH)
    assert "P456AT178" in response.text
    assert "M260EH47" not in response.text


def test_run_page_lists_steps_errors_and_raw_answer() -> None:
    client = _client()
    response = client.get("/admin/logs/runs/2", headers=AUTH)
    assert response.status_code == 200
    assert "tool · search_manual" in response.text
    assert "error · chat" in response.text
    assert "TimeoutError: таймаут ответа модели" in response.text
    assert "raw_answer" in response.text
    assert "Давление масла: 400 кПа [ЯМЗ-236М2, стр. 280]." in response.text


def test_run_page_escapes_step_content() -> None:
    client = _client()
    response = client.get("/admin/logs/runs/2", headers=AUTH)
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


def test_run_page_does_not_show_token_or_database_url() -> None:
    client = _client()
    _login(client)
    for response in (
        client.get("/admin/logs", headers=AUTH),
        client.get("/admin/logs/runs/2", headers=AUTH),
    ):
        assert TOKEN not in response.text
        assert "secret" not in response.text


def test_missing_run_is_404_in_russian() -> None:
    client = _client()
    response = client.get("/admin/logs/runs/999", headers=AUTH)
    assert response.status_code == 404
    assert "Ход не найден" in response.text


def test_database_error_is_shown_in_russian_not_500() -> None:
    client = _client()
    _reader(client).fail = True
    response = client.get("/admin/logs", headers=AUTH)
    assert response.status_code == 200
    assert "База данных недоступна" in response.text


def test_missing_database_is_reported_without_connecting() -> None:
    client = _client(database_url="")
    response = client.get("/admin/logs", headers=AUTH)
    assert response.status_code == 200
    assert "База данных не настроена" in response.text


def test_eval_tab_lists_runs_with_result_and_report_link() -> None:
    client = _client()
    response = client.get("/admin/logs?tab=eval", headers=AUTH)
    assert response.status_code == 200
    assert "12 из 14" in response.text
    assert "6dc4c25" in response.text
    assert "/admin/logs/eval/1" in response.text
    assert "Модели недоступны" in response.text


def test_eval_report_page_shows_report_text() -> None:
    client = _client()
    response = client.get("/admin/logs/eval/1", headers=AUTH)
    assert response.status_code == 200
    assert "# Отчёт RAG" in response.text
    assert "Q11 PASS" in response.text


def test_eval_report_page_without_report_says_so() -> None:
    client = _client()
    response = client.get("/admin/logs/eval/2", headers=AUTH)
    assert "Отчёта пока нет" in response.text


def test_missing_eval_run_is_404() -> None:
    client = _client()
    assert client.get("/admin/logs/eval/99", headers=AUTH).status_code == 404


def test_steps_helper_keeps_arbitrary_payload_as_text() -> None:
    from app.api.admin_logs import _pretty

    payload: dict[str, Any] = {"fragments": [1, 2], "note": "тест"}
    assert '"fragments": [' in _pretty(payload)
    assert _pretty(None) == "—"
