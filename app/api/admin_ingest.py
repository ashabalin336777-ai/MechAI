"""ВРЕМЕННЫЙ эндпоинт индексации руководств на стенде (Bearer ADMIN_TOKEN).

POST /admin/ingest запускает app.rag.ingest.run_ingest в фоне и отвечает 202.
GET /admin/ingest/status — состояние задачи и по каждому руководству chunker_version и число чанков.
Эндпоинт нужен, пока Neuraldeep недоступен с рабочей машины. После индексации удалить
(роутер, IngestJob и строку include_router в app/main.py), см. docs/deploy.md.
"""

import psycopg
from fastapi import APIRouter, HTTPException, Request

from app.api.admin_auth import check_admin
from app.rag.chunking import CHUNKER_VERSION

router = APIRouter(prefix="/admin/ingest", tags=["admin"])

MANUALS_SQL = (
    "SELECT id, chunker_version, "
    "(SELECT count(*) FROM chunks c WHERE c.manual_id = m.id) AS chunks "
    "FROM manuals m ORDER BY id"
)


def manuals_in_db(database_url: str) -> list[dict]:
    """Руководства в БД: версия нарезки и число чанков (только чтение)."""
    with psycopg.connect(database_url, connect_timeout=5) as conn:
        rows = conn.execute(MANUALS_SQL).fetchall()
    return [{"id": row[0], "chunker_version": row[1], "chunks": row[2]} for row in rows]


@router.post("", status_code=202)
def start_ingest(request: Request) -> dict[str, str]:
    check_admin(request)
    settings = request.app.state.settings
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="База данных не настроена")
    if not request.app.state.ingest_job.start(settings):
        raise HTTPException(status_code=409, detail="Индексация уже идёт")
    return {"status": "started"}


@router.get("/status")
def ingest_status(request: Request) -> dict:
    check_admin(request)
    job = request.app.state.ingest_job
    settings = request.app.state.settings
    manuals: list[dict] | None = None
    manuals_error: str | None = None
    if settings.database_url:
        try:
            manuals = manuals_in_db(settings.database_url)
        except psycopg.Error:
            manuals_error = "База данных недоступна"
    return {
        "state": job.state,
        "error": job.error,
        "report": job.report_md,
        "chunker_version_expected": CHUNKER_VERSION,
        "manuals": manuals,
        "manuals_error": manuals_error,
    }
