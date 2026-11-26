"""Общие константы и заглушки HTTP для тестов."""

from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
VEHICLES_PATH = REPO_ROOT / "mock" / "data" / "vehicles.json"
STUB_BASE = "http://stub"


class FailingHttp:
    """Имитация недоступного сервиса: каждый запрос падает сетевой ошибкой."""

    def __init__(self) -> None:
        self.calls = 0

    def request(self, method: str, url: str, json: object = None) -> httpx.Response:
        self.calls += 1
        raise httpx.ConnectError("connection refused", request=httpx.Request(method, url))
