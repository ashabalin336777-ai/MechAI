"""Временные эндпоинты /admin/ocr: доступ, 404/422/503, без сети и ключа в ответе."""

import pytest
from fastapi.testclient import TestClient

from app.api import admin_ocr
from app.clients.vision_client import VisionResult, detect_vision
from app.config import Settings
from app.main import create_app
from tests.helpers import REPO_ROOT, VEHICLES_PATH

TOKEN = "admin-token-for-ocr-tests-9"
API_KEY = "test-key-not-real-0123456789"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
PROBE = "/admin/ocr/probe?manual=236.01.01&page=280&model=vision-test"


class FakeVisionClient:
    """Подмена клиента Neuraldeep: сети нет, ответ фиксированный."""

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key

    def describe_page(self, png: bytes, model: str) -> VisionResult:
        assert png.startswith(b"\x89PNG")
        return VisionResult(text="Таблица 6.10", tokens_in=1200, tokens_out=40, elapsed_ms=1234)


def _client(token: str = TOKEN, api_key: str = API_KEY) -> TestClient:
    settings = Settings(
        admin_token=token,
        neuraldeep_api_key=api_key,
        manuals_dir=REPO_ROOT / "data" / "manuals",
        vehicles_path=VEHICLES_PATH,
        mount_mocks=False,
    )
    return TestClient(create_app(settings))


@pytest.fixture
def fake_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_ocr, "VisionClient", FakeVisionClient)


def test_endpoints_are_absent_without_admin_token() -> None:
    client = _client(token="")
    assert client.get("/admin/ocr/models").status_code == 404
    assert client.post(PROBE).status_code == 404


def test_wrong_or_missing_bearer_is_rejected() -> None:
    client = _client()
    assert (
        client.get("/admin/ocr/models", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    assert client.post(PROBE).status_code == 401


def test_vision_detected_from_catalog_modalities_and_id() -> None:
    assert detect_vision({"id": "m1", "input_modalities": ["text", "image"]}) is True
    assert detect_vision({"id": "m2", "input_modalities": ["text"]}) is False
    assert detect_vision({"id": "qwen2.5-vl-72b"}) is True
    assert detect_vision({"id": "bge-m3"}) is None


def test_probe_returns_text_and_no_key(fake_vision: None) -> None:
    response = _client().post(PROBE, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "model": "vision-test",
        "page": 280,
        "text": "Таблица 6.10",
        "elapsed_ms": 1234,
        "tokens_in": 1200,
        "tokens_out": 40,
    }
    assert API_KEY not in response.text


def test_probe_rejects_page_out_of_range_and_unknown_manual(fake_vision: None) -> None:
    client = _client()
    assert client.post(PROBE.replace("page=280", "page=9999"), headers=HEADERS).status_code == 422
    assert client.post(PROBE.replace("236.01.01", "999.99"), headers=HEADERS).status_code == 404


def test_probe_without_api_key_is_503(fake_vision: None) -> None:
    client = _client()
    # create_app создаёт клиент агента и требует ключ; сам эндпоинт проверяет ключ отдельно.
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"neuraldeep_api_key": ""}
    )
    response = client.post(PROBE, headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"] == "Ключ Neuraldeep не задан"
