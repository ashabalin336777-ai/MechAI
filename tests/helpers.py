"""Общие константы и заглушки HTTP для тестов."""

import os
from pathlib import Path

import httpx
import pymupdf
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


def make_scan_pdf(path: Path, pages: int, scan_page: int) -> Path:
    """Синтетический PDF для тестов OCR: текстовые страницы и одна страница-рисунок без текста.

    Текст и рисунок придуманы (не из материалов заказчика): нужны только для проверки логики.
    """
    pixmap = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 300, 200), False)
    pixmap.set_rect(pixmap.irect, (180,))
    picture = pixmap.tobytes("png")
    document = pymupdf.open()
    for number in range(1, pages + 1):
        page = document.new_page(width=595, height=842)
        if number == scan_page:
            page.insert_image(pymupdf.Rect(50, 50, 350, 250), stream=picture)
        else:
            page.insert_text((72, 72), f"Synthetic test page {number}")
    document.save(path)
    document.close()
    return path


class FailingHttp:
    """Имитация недоступного сервиса: каждый запрос падает сетевой ошибкой."""

    def __init__(self) -> None:
        self.calls = 0

    def request(self, method: str, url: str, json: object = None) -> httpx.Response:
        self.calls += 1
        raise httpx.ConnectError("connection refused", request=httpx.Request(method, url))
