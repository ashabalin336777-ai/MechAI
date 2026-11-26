from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_is_available_without_auth() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_is_russian_stub() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Цифровой механик" in response.text
    assert 'lang="ru"' in response.text
