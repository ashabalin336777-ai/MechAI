"""OCR страниц руководства, которые состоят только из рисунка (ТЗ §3.4, фаза OCR).

Страница рендерится в PNG (200 dpi), vision-модель дословно переписывает текст, результат режется
так же, как текст слоя PDF (split_lines), и пишется в chunks с source='ocr' эмбеддингом той же
модели, что и обычные чанки. Страницы — те же, что ingest помечает «только рисунок» (порог 100).

Идемпотентность: страница, для которой OCR-чанки уже есть, пропускается до вызова модели.
Запись страницы заменяет её прежние OCR-чанки одной транзакцией, поэтому повтор дублей не даёт.
"""

import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import psycopg

from app.clients.vision_client import VisionClient, VisionError, VisionResult
from app.config import Settings
from app.obs.retry import record_retry
from app.rag.chunking import ChunkDraft, image_only_pages, split_lines
from app.rag.embeddings import EmbeddingClient, vector_literal
from app.rag.manifest import Manifest, ManualEntry, load_manifest
from app.rag.manuals import ensure_manual_file
from app.rag.ocr_render import render_page_png

logger = logging.getLogger("app.rag.ocr")

TENANT_ID = "demo"
OCR_SOURCE = "ocr"
PAGE_ATTEMPTS = 3  # одна попытка и два повтора на каждую модель
RETRY_PAUSES_S = (5.0, 15.0)
MIN_OCR_CHARS = 20
PARALLEL_PAGES = 3
# Модель иногда дописывает в конец текста номер страницы отдельной строкой.
PAGE_NUMBER_LINE = re.compile(r"^[\s*_#>-]*(\d{1,4})[\s*_]*$")


class OcrError(Exception):
    """Запуск или страница не выполнены: текст сообщения виден в статусе прогона."""


@dataclass(frozen=True)
class OcrTask:
    entry: ManualEntry
    path: Path
    page: int


@dataclass(frozen=True)
class PageOutcome:
    manual_id: str
    page: int
    stored: bool
    model: str = ""
    chunks: int = 0
    text_chars: int = 0
    seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    error: str = ""


class OcrStore(Protocol):
    def manual_exists(self, manual_id: str) -> bool: ...

    def ocr_pages(self, manual_id: str) -> set[int]: ...

    def replace_page(
        self,
        entry: ManualEntry,
        page: int,
        chunks: list[ChunkDraft],
        vectors: list[list[float]],
    ) -> None: ...


class VisionPort(Protocol):
    def describe_page(self, png: bytes, model: str) -> VisionResult: ...


class EmbedPort(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class PgOcrStore:
    """Запись OCR-чанков в PostgreSQL. Каждый вызов — своё соединение (потоки пишут параллельно)."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url

    def manual_exists(self, manual_id: str) -> bool:
        with psycopg.connect(self._url, connect_timeout=5) as conn:
            row = conn.execute(
                "SELECT 1 FROM manuals WHERE tenant_id = %s AND id = %s", (TENANT_ID, manual_id)
            ).fetchone()
        return row is not None

    def ocr_pages(self, manual_id: str) -> set[int]:
        with psycopg.connect(self._url, connect_timeout=5) as conn:
            rows = conn.execute(
                "SELECT DISTINCT pdf_page FROM chunks "
                "WHERE tenant_id = %s AND manual_id = %s AND source = %s",
                (TENANT_ID, manual_id, OCR_SOURCE),
            ).fetchall()
        return {row[0] for row in rows}

    def replace_page(
        self,
        entry: ManualEntry,
        page: int,
        chunks: list[ChunkDraft],
        vectors: list[list[float]],
    ) -> None:
        rows = [
            (
                TENANT_ID,
                entry.id,
                entry.engine_models,
                chunk.pdf_page,
                chunk.section,
                chunk.text,
                vector_literal(vector),
                chunk.source,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        with psycopg.connect(self._url, connect_timeout=5) as conn:
            conn.execute(
                "DELETE FROM chunks WHERE tenant_id = %s AND manual_id = %s "
                "AND pdf_page = %s AND source = %s",
                (TENANT_ID, entry.id, page, OCR_SOURCE),
            )
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO chunks (tenant_id, manual_id, engine_models, pdf_page, section, "
                    "text, embedding, source) VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s)",
                    rows,
                )


def clean_ocr_text(raw: str, page: int) -> str:
    """Текст модели без номера страницы, который она дописала последней строкой."""
    lines = [line.rstrip() for line in raw.strip().splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        match = PAGE_NUMBER_LINE.match(lines[-1])
        if match and int(match.group(1)) == page:
            lines.pop()
    return "\n".join(lines).strip()


def pending_pages(candidates: list[int], stored: set[int]) -> list[int]:
    """Страницы-кандидаты, для которых OCR-чанков ещё нет."""
    return [page for page in candidates if page not in stored]


def plan_tasks(manifest: Manifest, manuals_dir: Path, store: OcrStore) -> list[OcrTask]:
    tasks: list[OcrTask] = []
    for entry in manifest.manuals:
        path = ensure_manual_file(entry, manuals_dir)
        if not store.manual_exists(entry.id):
            raise OcrError(f"руководство {entry.id} не проиндексировано: сначала запустите ingest")
        stored = store.ocr_pages(entry.id)
        tasks += [
            OcrTask(entry, path, page) for page in pending_pages(image_only_pages(path), stored)
        ]
    return tasks


def transcribe(
    client: VisionPort,
    png: bytes,
    models: tuple[str, ...],
    pause: Callable[[float], None] = time.sleep,
) -> tuple[VisionResult, str]:
    """Распознавание с повторами: каждая модель получает PAGE_ATTEMPTS попыток, затем следующая."""
    last_error: dict[str, str] = {}
    for model in models:
        for attempt in range(1, PAGE_ATTEMPTS + 1):
            try:
                result = client.describe_page(png, model)
                if not result.text.strip():
                    raise OcrError("модель вернула пустой ответ")
                return result, model
            except (VisionError, OcrError) as exc:
                last_error[model] = f"{type(exc).__name__}: {exc}"
                if attempt < PAGE_ATTEMPTS:
                    pause_s = RETRY_PAUSES_S[attempt - 1]
                    record_retry(f"ocr:{model}", exc, attempt, pause_s)
                    pause(pause_s)
    detail = "; ".join(f"{model}: {error}" for model, error in last_error.items())
    raise OcrError(f"распознавание не удалось ({detail})")


def process_task(
    task: OcrTask,
    client: VisionPort,
    embedder: EmbedPort,
    store: OcrStore,
    models: tuple[str, ...],
    pause: Callable[[float], None] = time.sleep,
) -> PageOutcome:
    """Одна страница: рендер, распознавание, нарезка, эмбеддинги, запись. Сбой не валит запуск."""
    began = time.monotonic()
    try:
        png = render_page_png(task.path, task.page)
        result, model = transcribe(client, png, models, pause)
        text = clean_ocr_text(result.text, task.page)
        if len(text) < MIN_OCR_CHARS:
            raise OcrError("распознано слишком мало текста")
        pieces, _ = split_lines([line for line in text.splitlines() if line.strip()], None)
        chunks = [
            ChunkDraft(pdf_page=task.page, section=section, text=piece, source=OCR_SOURCE)
            for section, piece in pieces
        ]
        vectors = embedder.embed([chunk.text for chunk in chunks])
        store.replace_page(task.entry, task.page, chunks, vectors)
    except Exception as exc:  # страница не должна останавливать остальные
        error = f"{type(exc).__name__}: {exc}"[:300]
        logger.error("OCR стр. %d (%s): %s", task.page, task.entry.id, error)
        return PageOutcome(
            manual_id=task.entry.id,
            page=task.page,
            stored=False,
            seconds=round(time.monotonic() - began, 1),
            error=error,
        )
    seconds = round(time.monotonic() - began, 1)
    logger.info(
        "OCR стр. %d (%s): %s, %.1f с, символов %d, чанков %d",
        task.page,
        task.entry.id,
        model,
        seconds,
        len(text),
        len(chunks),
    )
    return PageOutcome(
        manual_id=task.entry.id,
        page=task.page,
        stored=True,
        model=model,
        chunks=len(chunks),
        text_chars=len(text),
        seconds=seconds,
        tokens_in=result.tokens_in or 0,
        tokens_out=result.tokens_out or 0,
    )


def run_ocr_pages(
    settings: Settings,
    on_total: Callable[[int], None],
    on_outcome: Callable[[PageOutcome], None],
) -> None:
    """Страницы-рисунки всех руководств: план, параллельное распознавание, отчёт по странице."""
    if not settings.neuraldeep_api_key:
        raise OcrError("ключ Neuraldeep не задан")
    manifest = load_manifest(settings.manuals_dir / "manifest.yaml")
    store = PgOcrStore(settings.database_url)
    tasks = plan_tasks(manifest, settings.manuals_dir, store)
    on_total(len(tasks))
    models = tuple(dict.fromkeys(m for m in (settings.ocr_model, settings.ocr_fallback_model) if m))
    client = VisionClient(settings.neuraldeep_api_key, settings.neuraldeep_base_url)
    embedder = EmbeddingClient(
        settings.neuraldeep_api_key, settings.neuraldeep_base_url, settings.embed_model
    )
    with ThreadPoolExecutor(max_workers=PARALLEL_PAGES) as pool:
        futures = [
            pool.submit(process_task, task, client, embedder, store, models) for task in tasks
        ]
        for future in as_completed(futures):
            on_outcome(future.result())


def scrub(message: str, secrets: tuple[str, ...]) -> str:
    """Убирает из текста ошибки строку подключения и ключ API."""
    for secret in secrets:
        if secret:
            message = message.replace(secret, "<скрыто>")
    return message[:300]
