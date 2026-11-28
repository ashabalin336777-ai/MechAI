"""Проверка мобильной вёрстки (ТЗ фаза 05): 360, 390, 430 px, режимы «Стандартный/Новичок/Крупный».

Запуск (нужен Playwright и браузер Chromium, в requirements.txt их нет):
    pip install playwright
    python -m playwright install chromium
    python scripts/mobile_check.py --base http://127.0.0.1:8010

Если в окружении задан ADMIN_TOKEN, снимаются и страницы /admin/logs (вход формой, токен в HTML
не выводится). Скрипт снимает скриншоты в docs/mobile_design/check/ и пишет report.md:
горизонтальный скролл страницы и цели касания меньше 48 px (56 px в режиме «Крупный»).
Вердикт и черновик заявки
кладутся в sessionStorage теми же ключами, что и чат. Ответ модели не запрашивается:
абзацы и таблица отрисовываются общим MC.renderMarkdown, как в чате.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
WIDTHS = (360, 390, 430)
MODES = ("standard", "novice", "senior")
MODE_TARGET = {"standard": 48, "novice": 48, "senior": 56}
OUT_DIR = REPO_ROOT / "docs" / "mobile_design" / "check"

ANSWER_MD = """## Вердикт
**Риск:** высокий, остановить машину до проверки.

**Почему так считаем:** сигнал о падении давления масла подтверждён на стр. 280 руководства.

| Частота, мин-1 | Нагрузка, кВт | Время, мин | Примечание к проверке, очень длинный текст |
|---|---|---|---|
| 2000 | 147 | 200 | Нагрузка по таблице 6.12, режим номинальный |
| 1600 | 118 | 120 | Проверить после прогрева двигателя до рабочей температуры |

- Проверить уровень масла щупом [ЯМЗ-236М2, стр. 280].
- Измерить давление при 2000 мин-1 не ниже 400 кПа [ЯМЗ-236М2, стр. 280].
"""

VERDICT = {
    "light": "red",
    "headline": "Карантин: не выпускать на линию",
    "confidence": 0.87,
    "signal_quality": "good",
    "urgency": "high",
    "reasons": [
        "Давление масла ниже нормы на 2000 мин-1",
        "Аномалия подтверждена двумя проверками",
    ],
}

DRAFT = {
    "draft_id": "draft-check",
    "confirm_token": "token-check",
    "ticket": {
        "anomaly_type": "F04",
        "conclusion": (
            "Снижение давления масла в системе смазки двигателя, возможен износ вкладышей"
        ),
        "urgency": "high",
        "operations": [
            "Проверить уровень и состояние масла по щупу",
            "Измерить давление масла на 2000 мин-1 и сравнить с нормой 400–700 кПа",
        ],
        "spare_parts": ["Фильтр масляный ЯМЗ-236М2"],
        "references": [{"manual": "ЯМЗ-236М2, РК", "pdf_page": 280}],
    },
}


@dataclass
class PageReport:
    name: str
    width: int
    mode: str
    overflow_px: int = 0
    small_targets: list[str] = field(default_factory=list)
    screenshot: str = ""


def _first_vehicle(base: str) -> tuple[str, str]:
    import urllib.request

    with urllib.request.urlopen(f"{base}/vehicles", timeout=30) as response:
        html = response.read().decode("utf-8")
    vehicle = re.search(r'href="/vehicles/([^"]+)"', html)
    if not vehicle:
        raise SystemExit("В списке нет машин: проверьте данные стенда.")
    with urllib.request.urlopen(f"{base}/vehicles/{vehicle.group(1)}", timeout=30) as response:
        card = response.read().decode("utf-8")
    session = re.search(r'<option value="([^"]+)"', card)
    if not session:
        raise SystemExit("У первой машины нет проверок.")
    return vehicle.group(1), session.group(1)


def _measure(page: Page, target_px: int) -> tuple[int, list[str]]:
    overflow = page.evaluate(
        "() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth)"
    )
    small = page.evaluate(
        """(target) => {
            const picks = document.querySelectorAll(
                'a[href], button, select, textarea, label.check, ' +
                'input:not([type=checkbox]):not([type=hidden])'
            );
            const out = [];
            for (const el of picks) {
                if (el.closest('.visually-hidden') || el.closest('[hidden]')) continue;
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                if (r.height < target) {
                    const text = (el.textContent || el.getAttribute('aria-label') || el.tagName)
                        .trim().replace(/\\s+/g, ' ').slice(0, 60);
                    const size = Math.round(r.width) + '×' + Math.round(r.height);
                    out.push(el.tagName.toLowerCase() + ' «' + text + '» ' + size);
                }
            }
            return out;
        }""",
        target_px,
    )
    return int(overflow), list(small)


def _seed(page: Page, vehicle: str, session: str) -> None:
    page.evaluate(
        """([key, verdict, draft]) => {
            sessionStorage.setItem('verdict:' + key, JSON.stringify(verdict));
            sessionStorage.setItem('draft:' + key, JSON.stringify(draft));
        }""",
        [f"{vehicle}:{session}", VERDICT, DRAFT],
    )


def _add_answer(page: Page) -> None:
    page.evaluate(
        """(text) => {
            const item = document.createElement('li');
            item.className = 'bubble bubble-agent';
            const body = document.createElement('div');
            body.className = 'bubble-body answer';
            body.innerHTML = window.MC.renderMarkdown(text);
            item.appendChild(body);
            document.getElementById('messages').appendChild(item);
        }""",
        ANSWER_MD,
    )


def _shot(page: Page, name: str, width: int, mode: str, reports: list[PageReport]) -> None:
    path = OUT_DIR / f"{name}_{width}_{mode}.png"
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(path), full_page=True)
    overflow, small = _measure(page, MODE_TARGET[mode])
    reports.append(
        PageReport(
            name=name,
            width=width,
            mode=mode,
            overflow_px=overflow,
            small_targets=small,
            screenshot=str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        )
    )


def _run_page(browser, base: str, width: int, mode: str, vehicle: str, session: str, reports):
    context = browser.new_context(
        viewport={"width": width, "height": 800},
        is_mobile=True,
        has_touch=True,
        device_scale_factor=1,
    )
    context.add_init_script(f"localStorage.setItem('mode', '{mode}');")
    page = context.new_page()
    try:
        page.goto(f"{base}/vehicles", wait_until="networkidle")
        _shot(page, "vehicles", width, mode, reports)

        page.goto(f"{base}/vehicles/{vehicle}?session={session}", wait_until="networkidle")
        _shot(page, "vehicle", width, mode, reports)

        page.goto(f"{base}/vehicles/{vehicle}/chat?session={session}", wait_until="networkidle")
        _seed(page, vehicle, session)
        page.reload(wait_until="networkidle")
        _add_answer(page)
        _shot(page, "chat", width, mode, reports)

        page.goto(f"{base}/vehicles/{vehicle}/ticket?session={session}", wait_until="networkidle")
        _seed(page, vehicle, session)
        page.reload(wait_until="networkidle")
        _shot(page, "ticket", width, mode, reports)
    finally:
        context.close()


def _write_report(reports: list[PageReport]) -> None:
    lines = [
        "# Проверка мобильной вёрстки",
        "",
        "Ширины 360, 390, 430 px. Цели касания: 48 px, в режиме «Крупный» — 56 px.",
        "",
        "| Страница | Ширина | Режим | Горизонтальный скролл, px | Мелкие цели | Файл снимка |",
        "|---|---|---|---|---|---|",
    ]
    for r in reports:
        small = "; ".join(r.small_targets) if r.small_targets else "нет"
        lines.append(
            f"| {r.name} | {r.width} | {r.mode} | {r.overflow_px} | {small} "
            f"| `{Path(r.screenshot).name}` |"
        )
    (OUT_DIR / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_admin_pages(browser, base: str, token: str, width: int, reports: list[PageReport]) -> None:
    """Журнал агента: вход формой ADMIN_TOKEN, затем списки, шаги и отчёт прогона."""
    context = browser.new_context(
        viewport={"width": width, "height": 800}, is_mobile=True, has_touch=True
    )
    page = context.new_page()
    try:
        page.goto(f"{base}/admin/logs", wait_until="networkidle")
        page.fill("#token", token)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        _shot(page, "admin_logs", width, "standard", reports)
        runs = re.findall(r"/admin/logs/runs/(\d+)", page.content())
        page.goto(f"{base}/admin/logs?tab=eval", wait_until="networkidle")
        _shot(page, "admin_eval", width, "standard", reports)
        evals = re.findall(r"/admin/logs/eval/(\d+)", page.content())
        if runs:
            page.goto(f"{base}/admin/logs/runs/{runs[0]}", wait_until="networkidle")
            _shot(page, "admin_run", width, "standard", reports)
        if evals:
            page.goto(f"{base}/admin/logs/eval/{evals[0]}", wait_until="networkidle")
            _shot(page, "admin_report", width, "standard", reports)
        if token in page.content():
            raise SystemExit("Токен администратора попал в HTML журнала: остановлено.")
    finally:
        context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    vehicle, session = _first_vehicle(args.base)
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    reports: list[PageReport] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in WIDTHS:
                for mode in MODES:
                    _run_page(browser, args.base, width, mode, vehicle, session, reports)
                if admin_token:
                    _run_admin_pages(browser, args.base, admin_token, width, reports)
        finally:
            browser.close()
    _write_report(reports)
    print(json.dumps([r.__dict__ for r in reports], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
