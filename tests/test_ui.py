"""Интерфейс механика: страницы, русские подписи, мобильная вёрстка, главный механик (ТЗ §11).

Проверяем то, что видит механик: HTML-разметку, статусы по правилам §7.3 и размеры касаний.
Живой чат с моделью здесь не гоняем — он покрыт тестами агента.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.verdict import Verdict
from app.paths import STATIC_DIR, TEMPLATES_DIR
from app.ui.views import dashboard, status_of, trend_points

DIAG_VEHICLE = "TST-A001"
DIAG_SESSION = "S-9002"
ENGLISH_LABELS = re.compile(r"\b(Submit|Login|Cancel|Sign in|Sign up)\b", re.IGNORECASE)
HTML_SUBMIT_TYPE = re.compile(r'type="submit"|\.submit\(\)')


def _has_english_label(markup: str) -> bool:
    """Ищем англоязычные подписи; атрибут type="submit" — не подпись, его пропускаем."""
    return ENGLISH_LABELS.search(HTML_SUBMIT_TYPE.sub("", markup)) is not None


@pytest.fixture
def client(app_with_stubs: FastAPI) -> TestClient:
    return TestClient(app_with_stubs)


def _verdict(code: str, urgency: str | None) -> Verdict:
    light = {"normal": "green", "check_failed": "grey"}.get(code, "red")
    return Verdict(
        code=code,  # type: ignore[arg-type]
        light=light,  # type: ignore[arg-type]
        headline="тест",
        urgency=urgency,  # type: ignore[arg-type]
        reasons=[],
        recording_ok=True,
    )


def test_root_redirects_to_vehicle_list(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/vehicles"


def test_vehicle_list_is_mobile_and_russian(client: TestClient) -> None:
    response = client.get("/vehicles")

    assert response.status_code == 200
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in response.text
    assert 'lang="ru"' in response.text
    assert "Машины" in response.text
    assert "Аа" in response.text


def test_vehicle_list_partial_for_htmx_search(client: TestClient) -> None:
    response = client.get("/vehicles", params={"q": DIAG_VEHICLE}, headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert "<html" not in response.text
    assert DIAG_VEHICLE in response.text


def test_empty_search_result_is_explained_in_russian(client: TestClient) -> None:
    response = client.get("/vehicles", params={"q": "НЕТ-ТАКОЙ"})

    assert "По запросу «НЕТ-ТАКОЙ» машин нет" in response.text


def test_unknown_vehicle_gets_friendly_404_not_trace(client: TestClient) -> None:
    response = client.get("/vehicles/NOPE000")

    assert response.status_code == 404
    assert "не найдена" in response.text
    assert "Traceback" not in response.text


def test_vehicle_page_has_big_diagnosis_button(client: TestClient) -> None:
    response = client.get(f"/vehicles/{DIAG_VEHICLE}")

    assert response.status_code == 200
    assert "Получить результат диагностики" in response.text
    assert "btn-xl" in response.text


def test_chat_page_runs_diagnosis_only_when_asked(client: TestClient) -> None:
    auto = client.get(
        f"/vehicles/{DIAG_VEHICLE}/chat", params={"session": DIAG_SESSION, "action": "diagnosis"}
    )
    manual = client.get(f"/vehicles/{DIAG_VEHICLE}/chat", params={"session": DIAG_SESSION})

    assert 'data-auto="yes"' in auto.text
    assert 'data-auto="no"' in manual.text
    assert "Этапы работ" in manual.text
    assert "Создать заявку" in manual.text


def test_chat_unknown_session_falls_back_to_last_check(client: TestClient) -> None:
    response = client.get(f"/vehicles/{DIAG_VEHICLE}/chat", params={"session": "S-NOPE"})

    assert response.status_code == 200
    vehicle = client.app.state.vehicles.get(DIAG_VEHICLE)
    assert vehicle is not None and vehicle.last_session is not None
    assert f'data-session="{vehicle.last_session.session_id}"' in response.text


def test_steps_and_ticket_pages_render_with_session_data(client: TestClient) -> None:
    steps = client.get(f"/vehicles/{DIAG_VEHICLE}/steps", params={"session": DIAG_SESSION})
    ticket = client.get(f"/vehicles/{DIAG_VEHICLE}/ticket", params={"session": DIAG_SESSION})

    assert steps.status_code == 200
    assert 'data-session="S-9002"' in steps.text
    assert "Готово → далее" in steps.text
    assert ticket.status_code == 200
    assert "Состав проверил" in ticket.text
    assert "Отправить в ТОиР" in ticket.text
    assert ":disabled" in ticket.text or "x-bind:disabled" in ticket.text


def test_dashboard_shows_three_statuses_and_all_vehicles(client: TestClient) -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    for label in ("Карантин", "Требует внимания", "Норма"):
        assert label in response.text
    vehicles = client.app.state.vehicles.all()
    board = dashboard(vehicles, client.app.state.agent.deps.thresholds)
    assert sum(board.counts.values()) == len(vehicles)
    assert len(board.rows) == len(vehicles)


def test_dashboard_vehicle_page_has_history_and_trend(client: TestClient) -> None:
    response = client.get(f"/dashboard/{DIAG_VEHICLE}")

    assert response.status_code == 200
    assert "История проверок" in response.text
    assert "Заявки в ТОиР" in response.text
    assert "График оценок аномалии" in response.text


def test_status_rules_follow_tz_7_3() -> None:
    assert status_of(_verdict("anomaly", "high")) == "quarantine"
    assert status_of(_verdict("needs_confirmation", "medium")) == "attention"
    assert status_of(_verdict("anomaly", "low")) == "attention"
    assert status_of(_verdict("check_failed", None)) == "attention"
    assert status_of(_verdict("normal", None)) == "normal"


def test_trend_points_need_two_scores_and_stay_in_box() -> None:
    assert trend_points([0.5]) == ""
    points = trend_points([0.1, 1.7, -0.3], width=320, height=80).split(" ")

    assert len(points) == 3
    for point in points:
        x, y = (float(value) for value in point.split(","))
        assert 0 <= x <= 320
        assert 0 <= y <= 80


def test_manifest_is_valid_pwa_description() -> None:
    manifest = json.loads((STATIC_DIR / "manifest.webmanifest").read_text(encoding="utf-8"))

    assert manifest["lang"] == "ru"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#0b5fff"
    assert manifest["icons"][0]["src"] == "/static/icon.svg"


def test_touch_targets_grow_with_mode() -> None:
    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")

    assert "--target: 48px" in css
    assert "--target: 56px" in css
    assert 'html[data-mode="senior"]' in css
    assert "--font: 22px" in css


def test_pages_have_no_english_button_labels(client: TestClient) -> None:
    pages = [
        "/vehicles",
        f"/vehicles/{DIAG_VEHICLE}",
        f"/vehicles/{DIAG_VEHICLE}/chat",
        f"/vehicles/{DIAG_VEHICLE}/steps",
        f"/vehicles/{DIAG_VEHICLE}/ticket",
        "/dashboard",
        f"/dashboard/{DIAG_VEHICLE}",
    ]
    for page in pages:
        response = client.get(page)
        assert response.status_code == 200, page
        assert not _has_english_label(response.text), page


def test_static_scripts_are_in_place() -> None:
    for name in (
        "js/common.js",
        "js/markdown.js",
        "js/mode.js",
        "js/chat.js",
        "js/steps.js",
        "js/ticket.js",
    ):
        assert (STATIC_DIR / name).is_file(), name
    assert (STATIC_DIR / "vendor" / "htmx.min.js").is_file()
    assert (STATIC_DIR / "vendor" / "alpine.min.js").is_file()
    assert (TEMPLATES_DIR / "base.html").is_file()
    assert not (TEMPLATES_DIR / "index.html").exists()


def test_templates_are_russian_and_have_no_inline_english_text() -> None:
    for path in Path(TEMPLATES_DIR).rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert not _has_english_label(text), path.name
