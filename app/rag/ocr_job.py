"""Фоновый запуск OCR с прогрессом по run_id (как POST /admin/eval). Состояние в памяти процесса.

Сервер работает одним воркером (Dockerfile), поэтому состояние общее. Если контейнер перезапустится
во время прогона, статус пропадёт, а повторный запуск безопасен: готовые страницы пропускаются.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel

from app.config import Settings
from app.rag.ocr import PageOutcome, run_ocr_pages, scrub

Runner = Callable[[Settings, Callable[[int], None], Callable[[PageOutcome], None]], None]


class OcrFailure(BaseModel):
    manual_id: str
    pdf_page: int
    error: str


class OcrRunStatus(BaseModel):
    run_id: int
    state: str  # running | done | error
    total: int
    done: int
    stored: int
    chunks: int
    failed: list[OcrFailure]
    models: dict[str, int]  # сколько страниц распознала каждая модель
    tokens_in: int
    tokens_out: int
    started_at: datetime
    finished_at: datetime | None
    error: str | None


@dataclass
class OcrRun:
    run_id: int
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None
    state: str = "running"
    total: int = 0
    done: int = 0
    stored: int = 0
    chunks: int = 0
    failed: list[OcrFailure] = field(default_factory=list)
    models: dict[str, int] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_total(self, total: int) -> None:
        with self._lock:
            self.total = total

    def record(self, outcome: PageOutcome, secrets: tuple[str, ...] = ()) -> None:
        with self._lock:
            self.done += 1
            if outcome.stored:
                self.stored += 1
                self.chunks += outcome.chunks
                self.models[outcome.model] = self.models.get(outcome.model, 0) + 1
                self.tokens_in += outcome.tokens_in
                self.tokens_out += outcome.tokens_out
            else:
                self.failed.append(
                    OcrFailure(
                        manual_id=outcome.manual_id,
                        pdf_page=outcome.page,
                        error=scrub(outcome.error, secrets),
                    )
                )

    def finish(self, error: str | None = None) -> None:
        with self._lock:
            self.state = "error" if error else "done"
            self.error = error
            self.finished_at = datetime.now()

    def snapshot(self) -> OcrRunStatus:
        with self._lock:
            return OcrRunStatus(
                run_id=self.run_id,
                state=self.state,
                total=self.total,
                done=self.done,
                stored=self.stored,
                chunks=self.chunks,
                failed=list(self.failed),
                models=dict(self.models),
                tokens_in=self.tokens_in,
                tokens_out=self.tokens_out,
                started_at=self.started_at,
                finished_at=self.finished_at,
                error=self.error,
            )


class OcrJob:
    def __init__(self, runner: Runner = run_ocr_pages) -> None:
        self._runner = runner
        self._lock = threading.Lock()
        self._runs: dict[int, OcrRun] = {}
        self._active: OcrRun | None = None
        self._next_id = 1

    def start(self, settings: Settings) -> int | None:
        """run_id нового прогона или None, если уже идёт другой."""
        with self._lock:
            if self._active is not None:
                return None
            run = OcrRun(run_id=self._next_id)
            self._next_id += 1
            self._runs[run.run_id] = run
            self._active = run
        threading.Thread(target=self._run, args=(settings, run), daemon=True).start()
        return run.run_id

    def get(self, run_id: int | None) -> OcrRun | None:
        """Прогон run_id или последний прогон, если run_id не задан."""
        with self._lock:
            if run_id is None:
                return self._runs[max(self._runs)] if self._runs else None
            return self._runs.get(run_id)

    def _run(self, settings: Settings, run: OcrRun) -> None:
        secrets = (settings.database_url, settings.neuraldeep_api_key)
        try:
            self._runner(
                settings,
                run.set_total,
                lambda outcome: run.record(outcome, secrets),
            )
        except Exception as exc:  # фоновый поток: любой сбой должен быть виден в статусе
            run.finish(scrub(f"{type(exc).__name__}: {exc}", secrets))
        else:
            run.finish()
        finally:
            with self._lock:
                self._active = None
