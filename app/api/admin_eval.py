"""Админ-эндпоинт прогона проверки RAG: POST /admin/eval (Bearer ADMIN_TOKEN).

Без ADMIN_TOKEN в настройках эндпоинта нет (404). Токен не пишется в журнал.
Фаза 06 расширит этот же эндпоинт сценариями С1–С3.
"""

from typing import Literal

import psycopg
from fastapi import APIRouter, HTTPException, Request

from app.agent.evaluation import run_agent_report
from app.agent.scenarios import load_scenarios
from app.api.admin_auth import check_admin
from app.rag.embeddings import EmbeddingError
from app.rag.evaluation import run_eval_report
from app.rag.rerank import RerankError

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/eval")
def run_rag_eval(request: Request, suite: Literal["rag", "agent"] = "rag") -> dict[str, str]:
    check_admin(request)
    settings = request.app.state.settings
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="База данных не настроена")
    if suite == "agent":
        scenarios = load_scenarios(settings.agent_scenarios_path)
        report = run_agent_report(
            request.app.state.agent,
            scenarios,
            request.app.state.agent_prompt,
            model=settings.agent_model,
            min_score=settings.rag_min_score,
        )
        return {"report": report}
    try:
        report = run_eval_report(settings)
    except (EmbeddingError, RerankError) as exc:
        raise HTTPException(status_code=503, detail=f"Модели недоступны: {exc}") from exc
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="База данных недоступна") from exc
    return {"report": report}
