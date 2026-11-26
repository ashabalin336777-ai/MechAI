"""Страницы интерфейса: список машин, карточка ТС, чат, шаги, заявка и главный механик (ТЗ §11).

Рендер на сервере (Jinja2). Живые части — чат и заявка — работают в браузере через /api.
Неизвестная машина или проверка — понятная страница с кодом 404, а не трасса.
"""

import psycopg
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.agent.verdict import Thresholds
from app.data.vehicles import SessionRecord, Vehicle
from app.paths import TEMPLATES_DIR
from app.ui.views import (
    dashboard,
    fleet_row,
    history_rows,
    session_verdict,
    trend_points,
)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _thresholds(request: Request) -> Thresholds:
    return request.app.state.agent.deps.thresholds


def _vehicle(request: Request, vehicle_id: str) -> Vehicle | None:
    return request.app.state.vehicles.get(vehicle_id)


def _session(vehicle: Vehicle, session_id: str | None) -> SessionRecord | None:
    """Выбранная проверка; если не указана или не найдена — последняя (по умолчанию, ТЗ §11)."""
    for session in vehicle.sessions:
        if session.session_id == session_id:
            return session
    return vehicle.last_session


def _missing(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"title": "Не найдено", "message": message},
        status_code=404,
    )


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/vehicles", status_code=303)


@router.get("/vehicles", response_class=HTMLResponse)
def vehicles(request: Request, q: str = Query("", max_length=64)) -> HTMLResponse:
    rows = [fleet_row(v, _thresholds(request)) for v in request.app.state.vehicles.search(q)]
    context = {"rows": rows, "q": q, "title": "Машины"}
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "partials/vehicle_list.html", context)
    return templates.TemplateResponse(request, "vehicles.html", context)


@router.get("/vehicles/{vehicle_id}", response_class=HTMLResponse)
def vehicle_page(
    request: Request, vehicle_id: str, session: str | None = Query(None, max_length=64)
) -> HTMLResponse:
    vehicle = _vehicle(request, vehicle_id)
    if vehicle is None:
        return _missing(request, "Машина с таким госномером не найдена. Проверьте номер в списке.")
    chosen = _session(vehicle, session)
    verdict = session_verdict(vehicle, chosen, _thresholds(request)) if chosen else None
    return templates.TemplateResponse(
        request,
        "vehicle.html",
        {
            "title": vehicle.vehicle_id,
            "vehicle": vehicle,
            "session": chosen,
            "verdict": verdict,
            "sessions": list(reversed(vehicle.sessions)),
        },
    )


@router.get("/vehicles/{vehicle_id}/chat", response_class=HTMLResponse)
def chat_page(
    request: Request,
    vehicle_id: str,
    session: str | None = Query(None, max_length=64),
    action: str | None = Query(None, max_length=32),
) -> HTMLResponse:
    vehicle = _vehicle(request, vehicle_id)
    if vehicle is None:
        return _missing(request, "Машина с таким госномером не найдена. Проверьте номер в списке.")
    chosen = _session(vehicle, session)
    if chosen is None:
        return _missing(request, "По этой машине ещё нет проверок. Запись нужно сделать на стенде.")
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "title": f"Чат · {vehicle.vehicle_id}",
            "vehicle": vehicle,
            "session": chosen,
            "auto_diagnosis": action == "diagnosis",
        },
    )


@router.get("/vehicles/{vehicle_id}/steps", response_class=HTMLResponse)
def steps_page(
    request: Request, vehicle_id: str, session: str | None = Query(None, max_length=64)
) -> HTMLResponse:
    vehicle = _vehicle(request, vehicle_id)
    if vehicle is None:
        return _missing(request, "Машина с таким госномером не найдена. Проверьте номер в списке.")
    chosen = _session(vehicle, session)
    if chosen is None:
        return _missing(request, "По этой машине ещё нет проверок. Запись нужно сделать на стенде.")
    return templates.TemplateResponse(
        request,
        "steps.html",
        {"title": "Этапы работ", "vehicle": vehicle, "session": chosen},
    )


@router.get("/vehicles/{vehicle_id}/ticket", response_class=HTMLResponse)
def ticket_page(
    request: Request, vehicle_id: str, session: str | None = Query(None, max_length=64)
) -> HTMLResponse:
    vehicle = _vehicle(request, vehicle_id)
    if vehicle is None:
        return _missing(request, "Машина с таким госномером не найдена. Проверьте номер в списке.")
    chosen = _session(vehicle, session)
    if chosen is None:
        return _missing(request, "По этой машине ещё нет проверок. Запись нужно сделать на стенде.")
    return templates.TemplateResponse(
        request,
        "ticket.html",
        {"title": "Заявка в ТОиР", "vehicle": vehicle, "session": chosen},
    )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request) -> HTMLResponse:
    board = dashboard(request.app.state.vehicles.all(), _thresholds(request))
    return templates.TemplateResponse(
        request, "dashboard.html", {"title": "Главный механик", "board": board}
    )


@router.get("/dashboard/{vehicle_id}", response_class=HTMLResponse)
def dashboard_vehicle(request: Request, vehicle_id: str) -> HTMLResponse:
    vehicle = _vehicle(request, vehicle_id)
    if vehicle is None:
        return _missing(request, "Машина с таким госномером не найдена. Проверьте номер в списке.")
    thresholds = _thresholds(request)
    history = history_rows(vehicle, thresholds)
    scores = [s.anomaly_score for s in vehicle.sessions if s.anomaly_score is not None]
    tickets_error = False
    try:
        tickets = request.app.state.agent.deps.store.list_tickets(vehicle_id)
    except psycopg.Error:
        tickets, tickets_error = [], True
    return templates.TemplateResponse(
        request,
        "dashboard_vehicle.html",
        {
            "title": f"Карточка · {vehicle.vehicle_id}",
            "vehicle": vehicle,
            "history": history,
            "trend": trend_points(scores),
            "tickets": tickets,
            "tickets_error": tickets_error,
        },
    )
