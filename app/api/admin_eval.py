"""Админ-прогоны проверки: POST /admin/eval (202) и GET /admin/eval/status (Bearer ADMIN_TOKEN).

Прогон идёт в фоновом потоке, как индексация: обрыв сети у клиента его не останавливает.
Без ADMIN_TOKEN в настройках эндпоинтов нет (404). Токен не пишется в журнал.
Состояние и отчёт хранятся в памяти процесса: при перезапуске сервиса теряются.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

import psycopg
from fastapi import APIRouter, HTTPException, Request

from app.agent.evaluation import run_agent_report
from app.agent.scenarios import load_scenarios
from app.api.admin_auth import check_admin
from app.rag.embeddings import EmbeddingError
from app.rag.evaluation import run_eval_report
from app.rag.rerank import RerankError

router = APIRouter(prefix="/admin/eval", tags=["admin"])
logger = logging.getLogger("app")


class EvalJob:
    """Фоновый прогон проверки: один за раз, состояние в памяти процесса.

    Сервер запускается одним воркером (Dockerfile), поэтому состояние общее для всех запросов.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = "idle"  # idle | running | done | error
        self.suite: str | None = None
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.report_md: str | None = None
        self.error: str | None = None

    def start(self, suite: str, run: Callable[[], str]) -> bool:
        with self._lock:
            if self.state == "running":
                return False
            self.state = "running"
            self.suite = suite
            self.started_at = datetime.now(UTC)
            self.finished_at = None
            self.report_md = None
            self.error = None
        threading.Thread(target=self._run, args=(run,), daemon=True).start()
        return True

    def _run(self, run: Callable[[], str]) -> None:
        try:
            report = run()
        except (EmbeddingError, RerankError) as exc:
            self._fail(f"Модели недоступны: {exc}")
            return
        except psycopg.Error:
            self._fail("База данных недоступна")
            return
        except Exception as exc:  # фоновый поток: любой сбой должен быть виден в статусе
            logger.error("прогон проверки завершился с ошибкой: %s", type(exc).__name__)
            self._fail(f"Ошибка прогона: {type(exc).__name__}")
            return
        self.report_md = report
        self.finished_at = datetime.now(UTC)
        self.state = "done"
        logger.info("прогон проверки завершён: %s", self.suite)

    def _fail(self, message: str) -> None:
        self.error = message
        self.finished_at = datetime.now(UTC)
        self.state = "error"
        logger.error("прогон проверки: %s", message)


@router.post("", status_code=202)
def start_eval(request: Request, suite: Literal["rag", "agent"] = "rag") -> dict[str, str]:
    check_admin(request)
    settings = request.app.state.settings
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="База данных не настроена")
    if suite == "agent":
        scenarios = load_scenarios(settings.agent_scenarios_path)
        services = request.app.state.agent
        prompt = request.app.state.agent_prompt

        def run() -> str:
            return run_agent_report(
                services,
                scenarios,
                prompt,
                model=settings.agent_model,
                min_score=settings.rag_min_score,
            )

    else:

        def run() -> str:
            return run_eval_report(settings)

    if not request.app.state.eval_job.start(suite, run):
        raise HTTPException(status_code=409, detail="Прогон уже идёт")
    return {"status": "started", "suite": suite}


@router.get("/status")
def eval_status(request: Request) -> dict:
    check_admin(request)
    job = request.app.state.eval_job
    return {
        "state": job.state,
        "suite": job.suite,
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "error": job.error,
        "report": job.report_md,
    }


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()
