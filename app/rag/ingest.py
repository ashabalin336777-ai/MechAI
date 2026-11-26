"""Индексация руководств в PostgreSQL: текст, чанки, эмбеддинги, отчёт (ТЗ §3.4).

Запуск: `python -m app.rag.ingest` (локально) или POST /admin/ingest на стенде.
Повторный запуск идемпотентен: руководство с тем же sha256 и уже записанными чанками пропускается.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psycopg

from app.config import Settings, get_settings
from app.db.database import describe_error
from app.rag.chunking import CHUNKER_VERSION, ChunkDraft, build_manual_text
from app.rag.embeddings import EmbeddingClient, EmbeddingError, vector_literal
from app.rag.manifest import ManualEntry, load_manifest
from app.rag.manuals import ManualFileError, ensure_manual_file

logger = logging.getLogger("app.rag.ingest")

TENANT_ID = "demo"
MANIFEST_NAME = "manifest.yaml"
STATUSES = ("indexed", "skipped", "error")


@dataclass
class ManualResult:
    manual_id: str
    designation: str
    status: str  # indexed | skipped | error
    pages_total: int = 0
    chunks: int = 0
    image_only_pages: list[int] = field(default_factory=list)
    seconds: float = 0.0
    error: str = ""


@dataclass
class IngestReport:
    started_at: datetime
    finished_at: datetime
    results: list[ManualResult]


def run_ingest(settings: Settings) -> str:
    """Индексирует все руководства из манифеста и возвращает отчёт в Markdown."""
    started = datetime.now()
    manuals_dir = settings.manuals_dir
    manifest = load_manifest(manuals_dir / MANIFEST_NAME)
    embedder = EmbeddingClient(
        settings.neuraldeep_api_key, settings.neuraldeep_base_url, settings.embed_model
    )
    results = [
        _ingest_manual(entry, manuals_dir, settings.database_url, embedder)
        for entry in manifest.manuals
    ]
    return render_report(
        IngestReport(started_at=started, finished_at=datetime.now(), results=results)
    )


def _ingest_manual(
    entry: ManualEntry, manuals_dir: Path, database_url: str, embedder: EmbeddingClient
) -> ManualResult:
    began = time.monotonic()
    result = ManualResult(manual_id=entry.id, designation=entry.designation, status="error")
    try:
        path = ensure_manual_file(entry, manuals_dir)
        if _already_indexed(database_url, entry):
            result.status = "skipped"
            return result
        text = build_manual_text(path)
        result.pages_total = text.pages_total
        result.image_only_pages = text.image_only_pages
        if text.pages_total != entry.pages:
            raise ManualFileError(f"в файле {text.pages_total} стр., в манифесте {entry.pages}")
        if not text.chunks:
            raise ManualFileError("в файле нет текстового слоя")
        vectors = embedder.embed([chunk.text for chunk in text.chunks])
        _store(database_url, entry, text.chunks, vectors)
        result.chunks = len(text.chunks)
        result.status = "indexed"
    except ManualFileError as exc:
        result.error = str(exc)
    except EmbeddingError as exc:
        result.error = str(exc)
    except psycopg.Error as exc:
        result.error = describe_error(exc, database_url)
    result.seconds = round(time.monotonic() - began, 1)
    if result.status == "error":
        logger.error("руководство %s не проиндексировано: %s", entry.id, result.error)
    else:
        logger.info("руководство %s: %s, чанков %d", entry.id, result.status, result.chunks)
    return result


def _already_indexed(database_url: str, entry: ManualEntry) -> bool:
    """Пропуск только если тот же файл, та же версия нарезки и чанки уже записаны."""
    with psycopg.connect(database_url, connect_timeout=5) as conn:
        row = conn.execute(
            "SELECT m.sha256, m.chunker_version, "
            "(SELECT count(*) FROM chunks c "
            "WHERE c.tenant_id = m.tenant_id AND c.manual_id = m.id) "
            "FROM manuals m WHERE m.tenant_id = %s AND m.id = %s",
            (TENANT_ID, entry.id),
        ).fetchone()
    return row is not None and row[0] == entry.sha256 and row[1] == CHUNKER_VERSION and row[2] > 0


def _store(
    database_url: str, entry: ManualEntry, chunks: list[ChunkDraft], vectors: list[list[float]]
) -> None:
    """Пишет руководство и чанки одной транзакцией: при сбое база остаётся в прежнем состоянии."""
    rows = [
        (
            TENANT_ID,
            entry.id,
            entry.engine_models,
            chunk.pdf_page,
            chunk.section,
            chunk.text,
            vector_literal(vector),
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    with psycopg.connect(database_url, connect_timeout=5) as conn:
        conn.execute(
            "INSERT INTO manuals (tenant_id, id, designation, title, year, file_name, sha256, "
            "pages, engine_models, chunker_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, id) DO UPDATE SET designation = EXCLUDED.designation, "
            "title = EXCLUDED.title, year = EXCLUDED.year, file_name = EXCLUDED.file_name, "
            "sha256 = EXCLUDED.sha256, pages = EXCLUDED.pages, "
            "engine_models = EXCLUDED.engine_models, chunker_version = EXCLUDED.chunker_version",
            (
                TENANT_ID,
                entry.id,
                entry.designation,
                entry.title,
                entry.year,
                entry.file,
                entry.sha256,
                entry.pages,
                entry.engine_models,
                CHUNKER_VERSION,
            ),
        )
        conn.execute(
            "DELETE FROM chunks WHERE tenant_id = %s AND manual_id = %s", (TENANT_ID, entry.id)
        )
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO chunks (tenant_id, manual_id, engine_models, pdf_page, section, text, "
                "embedding) VALUES (%s, %s, %s, %s, %s, %s, %s::vector)",
                rows,
            )


def render_report(report: IngestReport) -> str:
    counts = {status: sum(1 for r in report.results if r.status == status) for status in STATUSES}
    total_chunks = sum(result.chunks for result in report.results)
    started = f"{report.started_at:%Y-%m-%d %H:%M:%S}"
    finished = f"{report.finished_at:%Y-%m-%d %H:%M:%S}"
    lines = [
        "# Отчёт ingest руководств",
        "",
        f"Начало: {started}, конец: {finished}.",
        f"Проиндексировано: {counts['indexed']}, пропущено: {counts['skipped']}, "
        f"с ошибкой: {counts['error']}. Чанков всего: {total_chunks}.",
        "",
        "| `manual_id` | Обозначение | Стр. PDF | Чанков | Стр. только рисунок "
        "| Статус | Сек | Примечание |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for result in report.results:
        image_only = ", ".join(str(page) for page in result.image_only_pages[:20])
        if len(result.image_only_pages) > 20:
            image_only += f" и ещё {len(result.image_only_pages) - 20}"
        lines.append(
            f"| `{result.manual_id}` | {result.designation} | {result.pages_total} "
            f"| {result.chunks} | {image_only or '—'} | {result.status} "
            f"| {result.seconds} | {result.error or '—'} |"
        )
    lines += [
        "",
        "OCR не выполняется: в образе нет tesseract. Страницы короче 100 символов",
        "помечены как «только рисунок».",
        "",
    ]
    return "\n".join(lines)


class IngestJob:
    """Фоновый запуск индексации: один запуск за раз, состояние в памяти процесса.

    Сервер запускается одним воркером (Dockerfile), поэтому состояние общее для всех запросов.
    """

    def __init__(self, runner: Callable[[Settings], str] = run_ingest) -> None:
        self._runner = runner
        self._lock = threading.Lock()
        self.state = "idle"  # idle | running | done | error
        self.report_md: str | None = None
        self.error: str | None = None

    def start(self, settings: Settings) -> bool:
        with self._lock:
            if self.state == "running":
                return False
            self.state = "running"
            self.report_md = None
            self.error = None
        threading.Thread(target=self._run, args=(settings,), daemon=True).start()
        return True

    def _run(self, settings: Settings) -> None:
        try:
            report = self._runner(settings)
        except Exception as exc:  # фоновый поток: любой сбой должен быть виден в статусе
            self.error = _safe_message(f"{type(exc).__name__}: {exc}", settings)
            self.state = "error"
            logger.error("индексация завершилась с ошибкой: %s", self.error)
            return
        self.report_md = report
        self.state = "done"
        logger.info("индексация завершена")


def _safe_message(message: str, settings: Settings) -> str:
    """Убирает из текста ошибки строку подключения и ключ API: статус виден по HTTP."""
    for secret in (settings.database_url, settings.neuraldeep_api_key):
        if secret:
            message = message.replace(secret, "<скрыто>")
    return message[:300]


if __name__ == "__main__":
    print(run_ingest(get_settings()))
