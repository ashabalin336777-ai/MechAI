"""POST /admin/eval: 404 без ADMIN_TOKEN, Bearer и hmac, 503 без БД, отчёт при успехе."""

import pytest
from fastapi.testclient import TestClient

from app.api import admin_eval
from app.config import Settings
from app.main import create_app

TOKEN = "admin-token-for-tests-42"
DB_URL = "postgresql://user:secret@db.example:5432/mechai"


def _client(token: str, database_url: str = DB_URL) -> TestClient:
    return TestClient(
        create_app(Settings(admin_token=token, database_url=database_url, mount_mocks=False))
    )


def test_endpoint_is_absent_without_admin_token() -> None:
    assert _client(token="").post("/admin/eval").status_code == 404


@pytest.mark.parametrize(
    "header",
    [None, "", "Basic " + TOKEN, "Bearer wrong-token", "Bearer " + TOKEN[:-1]],
)
def test_wrong_or_missing_bearer_is_rejected(header: str | None) -> None:
    client = _client(TOKEN)
    headers = {} if header is None else {"Authorization": header}
    response = client.post("/admin/eval", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Неверный токен"


def test_missing_database_is_reported_in_russian() -> None:
    response = _client(TOKEN, database_url="").post(
        "/admin/eval", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "База данных не настроена"


def test_correct_bearer_returns_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_eval, "run_eval_report", lambda settings: "# отчёт\n")
    response = _client(TOKEN).post("/admin/eval", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.json() == {"report": "# отчёт\n"}


def test_model_outage_is_503_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.embeddings import EmbeddingError

    def failing(settings: Settings) -> str:
        raise EmbeddingError("эмбеддинги недоступны: APIConnectionError")

    monkeypatch.setattr(admin_eval, "run_eval_report", failing)
    response = _client(TOKEN).post("/admin/eval", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503
    assert "Модели недоступны" in response.json()["detail"]


def test_agent_suite_requires_bearer() -> None:
    response = _client(TOKEN).post("/admin/eval?suite=agent")
    assert response.status_code == 401


def test_agent_suite_without_database_is_503() -> None:
    response = _client(TOKEN, database_url="").post(
        "/admin/eval?suite=agent", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 503


def test_agent_suite_returns_agent_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_eval, "run_agent_report", lambda *args, **kwargs: "# агент\n")
    response = _client(TOKEN).post(
        "/admin/eval?suite=agent", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 200
    assert response.json() == {"report": "# агент\n"}


def test_unknown_suite_is_422() -> None:
    response = _client(TOKEN).post(
        "/admin/eval?suite=unknown", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 422
