"""Страница /admin/logs: журнал агента и прогоны проверки (ТЗ §14, фаза 06). Только чтение.

GET /admin/logs?tab=runs&status=all|ok|error|running — ходы агента (время, ТС, статус, длительность,
токены); tab=eval — прогоны проверки (набор, итог, коммит).
GET /admin/logs/runs/{id} — шаги хода: вызовы инструментов, raw_answer, citation_check,
conflict_notice, ошибки и повторы.
GET /admin/logs/eval/{id} — прогон с текстом отчёта.
POST /admin/logs/access (поле token) и POST /admin/logs/logout — вход и выход на странице.
Без ADMIN_TOKEN страницы нет (404). Без входа показывается форма входа. Токен не попадает в
журнал, в cookie лежит HMAC от него. Ответы ходов могут содержать данные машины: доступ только
у администратора.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import parse_qs

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.api.admin_auth import (
    ADMIN_COOKIE,
    ADMIN_COOKIE_MAX_AGE_S,
    admin_cookie_value,
    is_admin,
    token_matches,
)
from app.db.agent_journal import AgentRunRow, AgentStepRow
from app.db.eval_runs import EvalRunRecord
from app.paths import TEMPLATES_DIR

router = APIRouter(prefix="/admin/logs", tags=["admin"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)
logger = logging.getLogger("app")

# Стенд работает в Новосибирске (UTC+7); фиксированное смещение, без tzdata в образе.
LOCAL_TZ = timezone(timedelta(hours=7), "UTC+7")
LIST_LIMIT = 50
NO_DATABASE = "База данных не настроена: ходы агента и прогоны проверки не записываются."
DB_UNAVAILABLE = "База данных недоступна. Журнал временно не открывается, обновите страницу позже."
RUN_STATUS_LABELS = {"ok": "успешно", "error": "ошибка", "running": "идёт"}
EVAL_STATUS_LABELS = {"done": "готово", "error": "ошибка", "running": "идёт"}
FILTERS = {"all": "Все", "ok": "Успешные", "error": "С ошибкой", "running": "Идут"}


class RunView(BaseModel):
    id: int
    started: str
    vehicle: str
    session: str
    status: str
    status_key: str
    duration: str
    tokens: str


class StepView(BaseModel):
    n: int
    title: str
    ms: str
    model: str
    tokens: str
    error: str
    input_text: str
    output_text: str


class RunDetail(BaseModel):
    run: RunView
    tok_per_s: str
    cost: str
    steps: list[StepView]


class EvalView(BaseModel):
    id: int
    started: str
    suite: str
    status: str
    result: str
    commit: str
    error: str


def _dash(value: object) -> str:
    return "—" if value is None or value == "" else str(value)


def _local(moment: datetime) -> str:
    return moment.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M:%S")


def _run_view(row: AgentRunRow) -> RunView:
    tokens = "—"
    if row.prompt_tokens is not None or row.completion_tokens is not None:
        tokens = f"{_dash(row.prompt_tokens)} / {_dash(row.completion_tokens)}"
    return RunView(
        id=row.id,
        started=_local(row.started_at),
        vehicle=_dash(row.vehicle_id),
        session=_dash(row.session_id),
        status=RUN_STATUS_LABELS.get(row.status, row.status),
        status_key=row.status,
        duration=f"{row.total_ms} мс" if row.total_ms is not None else "—",
        tokens=tokens,
    )


def _pretty(value: dict[str, Any] | None) -> str:
    """Текст шага для чтения: одиночное поле «text» (ответ модели) показываем как есть."""
    if not value:
        return "—"
    if set(value) in ({"text"}, {"truncated"}) and isinstance(next(iter(value.values())), str):
        return str(next(iter(value.values())))
    return json.dumps(value, ensure_ascii=False, indent=2)


def _step_view(step: AgentStepRow) -> StepView:
    tokens = "—"
    if step.prompt_tokens is not None or step.completion_tokens is not None:
        tokens = f"{_dash(step.prompt_tokens)} / {_dash(step.completion_tokens)}"
    error = ""
    if step.error_class or step.error_message or step.error:
        parts = [part for part in (step.error_class, step.error_message or step.error) if part]
        error = ": ".join(parts)
    return StepView(
        n=step.n,
        title=f"{step.kind} · {step.name}",
        ms=f"{step.ms} мс" if step.ms is not None else "—",
        model=_dash(step.model),
        tokens=tokens,
        error=error,
        input_text=_pretty(step.input),
        output_text=_pretty(step.output),
    )


def _eval_view(record: EvalRunRecord) -> EvalView:
    result = "—"
    if record.passed is not None and record.total is not None:
        result = f"{record.passed} из {record.total}"
    return EvalView(
        id=record.id,
        started=_local(record.started_at),
        suite=record.suite,
        status=EVAL_STATUS_LABELS.get(record.status, record.status),
        result=result,
        commit=_dash(record.commit_sha),
        error=_dash(record.error_message),
    )


def _expected_token(request: Request) -> str:
    expected = request.app.state.settings.admin_token
    if not expected:
        raise HTTPException(status_code=404)
    return expected


def _https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip() == "https"


def _login_page(request: Request, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {"title": "Вход · журнал агента", "error": error},
        status_code=status_code,
    )


def _message(request: Request, title: str, message: str, status_code: int):
    return templates.TemplateResponse(
        request,
        "error.html",
        {"title": title, "message": message},
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def logs_page(
    request: Request,
    tab: Literal["runs", "eval"] = "runs",
    status: Literal["all", "ok", "error", "running"] = "all",
) -> HTMLResponse:
    expected = _expected_token(request)
    if not is_admin(request, expected):
        return _login_page(request)
    error: str | None = None
    runs: list[RunView] = []
    evals: list[EvalView] = []
    reader = request.app.state.journal_reader
    if reader is None:
        error = NO_DATABASE
    elif tab == "runs":
        try:
            rows = reader.list_runs(None if status == "all" else status, LIST_LIMIT)
            runs = [_run_view(row) for row in rows]
        except psycopg.Error:
            logger.error("журнал агента: база недоступна при открытии списка")
            error = DB_UNAVAILABLE
    else:
        try:
            evals = [_eval_view(r) for r in request.app.state.eval_store.list_runs(LIST_LIMIT)]
        except psycopg.Error:
            logger.error("журнал агента: база недоступна при открытии прогонов")
            error = DB_UNAVAILABLE
    return templates.TemplateResponse(
        request,
        "admin/logs.html",
        {
            "title": "Журнал агента",
            "tab": tab,
            "status": status,
            "filters": FILTERS,
            "runs": runs,
            "evals": evals,
            "error": error,
        },
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: int) -> HTMLResponse:
    expected = _expected_token(request)
    if not is_admin(request, expected):
        return _login_page(request)
    reader = request.app.state.journal_reader
    if reader is None:
        return _message(request, "Журнал агента", NO_DATABASE, 503)
    try:
        row = reader.get_run(run_id)
        steps = reader.list_steps(run_id) if row is not None else []
    except psycopg.Error:
        logger.error("журнал агента: база недоступна при открытии хода %s", run_id)
        return _message(request, "Журнал агента", DB_UNAVAILABLE, 503)
    if row is None:
        return _message(request, "Ход не найден", "В журнале нет хода с таким номером.", 404)
    detail = RunDetail(
        run=_run_view(row),
        tok_per_s=f"{row.tok_per_s} ток/с" if row.tok_per_s is not None else "—",
        cost=f"{row.cost_rub} ₽" if row.cost_rub is not None else "—",
        steps=[_step_view(step) for step in steps],
    )
    return templates.TemplateResponse(
        request,
        "admin/run.html",
        {"title": f"Ход {row.id}", "detail": detail},
    )


@router.get("/eval/{run_id}", response_class=HTMLResponse)
def eval_page(request: Request, run_id: int) -> HTMLResponse:
    expected = _expected_token(request)
    if not is_admin(request, expected):
        return _login_page(request)
    try:
        record = request.app.state.eval_store.get_run(run_id)
    except psycopg.Error:
        logger.error("журнал агента: база недоступна при открытии прогона %s", run_id)
        return _message(request, "Прогоны проверки", DB_UNAVAILABLE, 503)
    if record is None:
        return _message(request, "Прогон не найден", "Прогона с таким номером нет.", 404)
    return templates.TemplateResponse(
        request,
        "admin/eval_run.html",
        {
            "title": f"Прогон {record.id}",
            "view": _eval_view(record),
            "report": record.report_md
            or "Отчёта пока нет: прогон ещё идёт или завершился ошибкой.",
        },
    )


@router.post("/access")
async def login(request: Request) -> Response:
    expected = _expected_token(request)
    form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    token = form.get("token", [""])[0]
    if not token or not token_matches(token, expected):
        return _login_page(request, error="Неверный токен", status_code=401)
    response = RedirectResponse("/admin/logs", status_code=303)
    response.set_cookie(
        ADMIN_COOKIE,
        admin_cookie_value(expected),
        max_age=ADMIN_COOKIE_MAX_AGE_S,
        httponly=True,
        samesite="strict",
        secure=_https(request),
        path="/admin",
    )
    return response


@router.post("/logout")
def logout(request: Request) -> Response:
    _expected_token(request)
    response = RedirectResponse("/admin/logs", status_code=303)
    response.delete_cookie(ADMIN_COOKIE, path="/admin")
    return response
