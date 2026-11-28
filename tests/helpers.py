"""Общие константы и заглушки HTTP для тестов."""

import os
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "mock_data"
VEHICLES_PATH = FIXTURES_DIR / "vehicles.json"
FAULT_TYPES_PATH = FIXTURES_DIR / "fault_types.json"
STUB_BASE = "http://stub"

# Тесты, которым нужны настоящие PDF из data/manuals (материалы задачи, п. 9.1), запускаются
# только вручную: MECHAI_REAL_MATERIALS=1. В чистом клоне и в CI они пропускаются.
REAL_MATERIALS = os.environ.get("MECHAI_REAL_MATERIALS") == "1"
requires_real_materials = pytest.mark.skipif(
    not REAL_MATERIALS,
    reason="нужны материалы задачи: MECHAI_REAL_MATERIALS=1 и PDF в data/manuals",
)


class FailingHttp:
    """Имитация недоступного сервиса: каждый запрос падает сетевой ошибкой."""

    def __init__(self) -> None:
        self.calls = 0

    def request(self, method: str, url: str, json: object = None) -> httpx.Response:
        self.calls += 1
        raise httpx.ConnectError("connection refused", request=httpx.Request(method, url))
