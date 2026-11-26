"""Админ-прогоны проверки (Bearer ADMIN_TOKEN).

POST /admin/eval?suite=rag|agent — создаёт запись в eval_runs и запускает прогон в фоне (202).
GET /admin/eval/status[?run_id=] — запись прогона (по умолчанию последняя), с отчётом.
GET /admin/eval/runs?limit=10 — последние прогоны без текста отчёта.

Без ADMIN_TOKEN эндпоинтов нет (404). Токен и строка подключения в ответах не появляются.
"""

import logging
import threading
from collections.abc import Callable
from typing import Literal

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request

from app.agent.evaluation import run_agent_result
from app.agent.scenarios import load_scenarios
from app.api.admin_auth import check_admin
from app.db.eval_runs import EvalResult, PgEvalRunStore
from app.rag.embeddings import EmbeddingError
from app.rag.evaluation import run_eval_result
from app.rag.rerank import RerankError

router = APIRouter(prefix="/admin/eval", tags=["admin"])
logger = logging.getLogger("app")
DB_UNAVAILABLE = "База данных недоступна"


class EvalJob:
    """Фоновый запуск прогона. Итог и ошибка пишутся в eval_runs, а не в память процесса."""

    def __init__(self, store: PgEvalRunStore) -> None:
        self._store = store

    def start(
        self, suite: str, commit_sha: str | None, run: Callable[[], EvalResult]
    ) -> int | None:
        """Возвращает run_id или None, если другой прогон ещё идёт."""
        run_id = self._store.create_run(suite, commit_sha)
        if run_id is None:
            return None
        threading.Thread(target=self._run, args=(run_id, run), daemon=True).start()
        return run_id

    def _run(self, run_id: int, run: Callable[[], EvalResult]) -> None:
        try:
            result = run()
        except (EmbeddingError, RerankError) as exc:
            self._fail(run_id, f"Модели недоступны: {exc}")
            return
        except psycopg.Error:
            self._fail(run_id, DB_UNAVAILABLE)
            return
        except Exception as exc:  # фоновый поток: любой сбой должен быть виден в статусе
            logger.error("прогон проверки %s завершился с ошибкой: %s", run_id, type(exc).__name__)
            self._fail(run_id, f"Ошибка прогона: {type(exc).__name__}")
            return
        try:
            self._store.finish_run(run_id, result)
        except psycopg.Error:
            logger.error("итог прогона %s не записан: БД недоступна", run_id)
            return
        logger.info("прогон проверки %s завершён", run_id)

    def _fail(self, run_id: int, message: str) -> None:
        logger.error("прогон проверки %s: %s", run_id, message)
        try:
            self._store.fail_run(run_id, message)
        except psycopg.Error:
            logger.error("ошибка прогона %s не записана: БД недоступна", run_id)


@router.post("", status_code=202)
def start_eval(request: Request, suite: Literal["rag", "agent"] = "rag") -> dict[str, str | int]:
    check_admin(request)
    settings = request.app.state.settings
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="База данных не настроена")
    if suite == "agent":
        scenarios = load_scenarios(settings.agent_scenarios_path)
        services = request.app.state.agent
        prompt = request.app.state.agent_prompt

        def run() -> EvalResult:
            return run_agent_result(
                services,
                scenarios,
                prompt,
                model=settings.agent_model,
                min_score=settings.rag_min_score,
            )

    else:

        def run() -> EvalResult:
            return run_eval_result(settings)

    commit_sha = settings.commit_sha or None
    try:
        run_id = request.app.state.eval_job.start(suite, commit_sha, run)
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE) from exc
    if run_id is None:
        raise HTTPException(status_code=409, detail="Прогон уже идёт")
    return {"status": "started", "suite": suite, "run_id": run_id}


@router.get("/status")
def eval_status(request: Request, run_id: int | None = None) -> dict:
    check_admin(request)
    store: PgEvalRunStore = request.app.state.eval_store
    try:
        record = store.get_run(run_id) if run_id is not None else store.latest_run()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE) from exc
    if record is None:
        detail = "Прогон не найден" if run_id is not None else "Прогонов ещё не было"
        raise HTTPException(status_code=404, detail=detail)
    return record.model_dump(mode="json")


@router.get("/runs")
def eval_runs(request: Request, limit: int = Query(default=10, ge=1, le=100)) -> dict:
    check_admin(request)
    store: PgEvalRunStore = request.app.state.eval_store
    try:
        records = store.list_runs(limit)
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE) from exc
    return {"runs": [record.model_dump(mode="json", exclude={"report_md"}) for record in records]}
