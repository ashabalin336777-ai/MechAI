"""ВРЕМЕННЫЙ эндпоинт запуска индексации руководств на стенде.

Нужен, пока Neuraldeep недоступен с рабочей машины. Защищён заголовком X-Ingest-Token
(переменная INGEST_TOKEN). Без INGEST_TOKEN эндпоинта нет (404). Удаляется после индексации.
"""

import hmac

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/admin/ingest", tags=["admin"])


def _check_token(request: Request) -> None:
    expected = request.app.state.settings.ingest_token
    if not expected:
        raise HTTPException(status_code=404)
    given = request.headers.get("X-Ingest-Token", "")
    if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Неверный токен")


@router.post("", status_code=202)
def start_ingest(request: Request) -> dict[str, str]:
    _check_token(request)
    settings = request.app.state.settings
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="База данных не настроена")
    if not request.app.state.ingest_job.start(settings):
        raise HTTPException(status_code=409, detail="Индексация уже идёт")
    return {"status": "started"}


@router.get("/status")
def ingest_status(request: Request) -> dict[str, str | None]:
    _check_token(request)
    job = request.app.state.ingest_job
    return {"state": job.state, "error": job.error, "report": job.report_md}
