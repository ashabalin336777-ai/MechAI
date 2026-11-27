"""ВРЕМЕННЫЕ эндпоинты OCR (Bearer ADMIN_TOKEN): проверка моделей и распознавание страниц-рисунков.

GET /admin/ocr/models: список моделей Neuraldeep с пометкой vision (ключ не возвращается).
POST /admin/ocr/probe: рендер одной страницы в PNG и дословное распознавание, в БД не пишет.
POST /admin/ocr/ingest: распознать страницы-рисунки, чанки source='ocr' (202, run_id).
GET /admin/ocr/ingest/status?run_id=N: прогресс прогона (без run_id — последний).

TODO: удалить перед финальным коммитом: модуль, include_router в app/main.py,
app/rag/ocr.py, app/rag/ocr_job.py, tests/test_admin_ocr.py.
"""

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.admin_auth import check_admin
from app.clients.vision_client import ModelInfo, VisionClient, VisionError
from app.rag.manifest import ManualEntry
from app.rag.manuals import ManualFileError, ensure_manual_file
from app.rag.ocr_job import OcrRunStatus
from app.rag.ocr_render import page_count, render_page_png

router = APIRouter(prefix="/admin/ocr", tags=["admin"])
logger = logging.getLogger("app.api.admin_ocr")


class OcrModelsResponse(BaseModel):
    models: list[ModelInfo]


class OcrProbeResponse(BaseModel):
    model: str
    page: int
    text: str
    elapsed_ms: int
    tokens_in: int | None
    tokens_out: int | None


class OcrStartResponse(BaseModel):
    status: str
    run_id: int


def _vision_client(request: Request) -> VisionClient:
    settings = request.app.state.settings
    if not settings.neuraldeep_api_key:
        raise HTTPException(status_code=503, detail="Ключ Neuraldeep не задан")
    return VisionClient(settings.neuraldeep_api_key, settings.neuraldeep_base_url)


def _find_manual(request: Request, manual: str) -> ManualEntry:
    for entry in request.app.state.manifest.manuals:
        if entry.id == manual or entry.designation.startswith(manual):
            return entry
    raise HTTPException(status_code=404, detail="Руководство не найдено в манифесте")


@router.get("/models", response_model=OcrModelsResponse)
def ocr_models(request: Request) -> OcrModelsResponse:
    check_admin(request)
    try:
        models = _vision_client(request).list_models()
    except VisionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return OcrModelsResponse(models=models)


@router.post("/probe", response_model=OcrProbeResponse)
def ocr_probe(
    request: Request,
    manual: str = Query(min_length=1, max_length=64),
    page: int = Query(ge=1),
    model: str = Query(min_length=1, max_length=128),
) -> OcrProbeResponse:
    check_admin(request)
    entry = _find_manual(request, manual)
    try:
        path = ensure_manual_file(entry, request.app.state.settings.manuals_dir)
    except ManualFileError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    total = page_count(path)
    if page > total:
        raise HTTPException(
            status_code=422, detail=f"страницы {page} нет: в руководстве {total} стр."
        )
    png = render_page_png(path, page)
    client = _vision_client(request)
    try:
        result = client.describe_page(png, model)
    except VisionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    logger.info(
        "OCR-проба: стр. %d, модель %s, %d мс, символов %d",
        page,
        model,
        result.elapsed_ms,
        len(result.text),
    )
    return OcrProbeResponse(
        model=model,
        page=page,
        text=result.text,
        elapsed_ms=result.elapsed_ms,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
    )


@router.post("/ingest", status_code=202, response_model=OcrStartResponse)
def ocr_ingest_start(request: Request) -> OcrStartResponse:
    check_admin(request)
    settings = request.app.state.settings
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="База данных не настроена")
    if not settings.neuraldeep_api_key:
        raise HTTPException(status_code=503, detail="Ключ Neuraldeep не задан")
    run_id = request.app.state.ocr_job.start(settings)
    if run_id is None:
        raise HTTPException(status_code=409, detail="OCR уже идёт")
    return OcrStartResponse(status="started", run_id=run_id)


@router.get("/ingest/status", response_model=OcrRunStatus)
def ocr_ingest_status(
    request: Request, run_id: int | None = Query(default=None, ge=1)
) -> OcrRunStatus:
    check_admin(request)
    run = request.app.state.ocr_job.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Прогона OCR нет")
    return run.snapshot()
