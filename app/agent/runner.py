"""Один ход агента: журнал, граф, события для интерфейса (ТЗ §6.1, §14).

События SSE: token (стрим), verdict и ticket_draft (от инструментов), answer_final (текст после
проверки цитат, заменяет стрим), meta (ttft, ток/с, ₽), error (понятный текст), done.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph import AgentDeps, RunStats, build_graph, record_error
from app.agent.llm import ChatModel, LlmError
from app.obs.journal import Journal, RunSummary
from app.obs.prices import cost_rub
from app.obs.retry import retry_sink
from app.tools.registry import ToolSpec
from app.tools.runtime import ToolDeps, TurnContext

logger = logging.getLogger("app.agent")

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "system_ru.md"
RECURSION_LIMIT = 40
UI_MODES = ("standard", "novice", "senior")
GENERIC_ERROR = "Сервис диагностики или модель временно недоступны, повторите."

Emit = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class TurnRequest:
    vehicle_id: str
    session_id: str
    message: str
    user_action: str | None
    ui_mode: str
    lang: str
    input_mode: str = "text"


@dataclass
class AgentServices:
    deps: ToolDeps
    llm: ChatModel
    registry: dict[str, ToolSpec]
    journal: Journal
    checkpointer: Any
    timeout_s: float
    max_tool_calls: int


def load_base_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def run_turn(services: AgentServices, request: TurnRequest, base_prompt: str, emit: Emit) -> None:
    started = time.monotonic()
    vehicle = services.deps.vehicles.get(request.vehicle_id)
    if vehicle is None:
        emit("error", {"message": "Машина не найдена."})
        emit("done", {})
        return
    run_id = services.journal.start_run(
        vehicle_id=request.vehicle_id,
        session_id=request.session_id,
        lang=request.lang,
        input_mode=request.input_mode,
    )
    stats = RunStats()
    deps = AgentDeps(
        llm=services.llm,
        tools=services.deps,
        registry=services.registry,
        journal=services.journal,
        run_id=run_id,
        turn=TurnContext(vehicle_id=request.vehicle_id, session_id=request.session_id),
        emit=emit,
        system_prompt=_system_prompt(base_prompt, vehicle, request),
        timeout_s=services.timeout_s,
        max_tool_calls=services.max_tool_calls,
        stats=stats,
    )
    graph = build_graph(deps, services.checkpointer)
    config = {
        "configurable": {"thread_id": _thread_id(request)},
        "recursion_limit": RECURSION_LIMIT,
    }
    payload = {
        "messages": [HumanMessage(content=_user_text(request))],
        "tool_calls": 0,
        "tool_usage": {},
        "started_at": time.monotonic(),
    }
    status = "ok"
    with retry_sink():
        try:
            deps.turn.show_verdict = request.user_action == "get_diagnosis" or _is_first_turn(
                graph, config
            )
            result = graph.invoke(payload, config)
            final = result["messages"][-1]
            if isinstance(final, AIMessage):
                emit("answer_final", {"text": str(final.content)})
        except LlmError as exc:
            status = "error"
            logger.warning("модель недоступна: %s", exc)
            record_error(deps, "turn", exc)
            emit("error", {"message": GENERIC_ERROR})
        except Exception as exc:
            status = "error"
            logger.exception("сбой хода агента")
            record_error(deps, "turn", exc)
            emit("error", {"message": GENERIC_ERROR})

    total_ms = int((time.monotonic() - started) * 1000)
    services.journal.finish_run(
        run_id,
        RunSummary(
            status=status,
            total_ms=total_ms,
            prompt_tokens=stats.prompt_tokens,
            completion_tokens=stats.completion_tokens,
            tok_per_s=stats.tok_per_s,
            cost_rub=_cost(stats),
        ),
    )
    emit(
        "meta",
        {
            "run_id": run_id,
            "ttft_ms": stats.ttft_ms,
            "tok_per_s": stats.tok_per_s,
            "model": stats.model,
            "total_ms": total_ms,
            "steps": stats.steps,
        },
    )
    emit("done", {})


def _is_first_turn(graph: Any, config: dict[str, Any]) -> bool:
    """В состоянии потока (сессии) ещё нет сообщений: это первый ход сессии."""
    return not graph.get_state(config).values.get("messages")


def _cost(stats: RunStats) -> Any:
    if stats.model is None:
        return None
    return cost_rub(stats.model, stats.prompt_tokens, stats.completion_tokens)


def _thread_id(request: TurnRequest) -> str:
    """Состояние диалога: tenant:user:vehicle:session (ТЗ §6.1). Пользователь демо — mechanic."""
    return f"demo:mechanic:{request.vehicle_id}:{request.session_id}"


def _user_text(request: TurnRequest) -> str:
    if request.user_action == "get_diagnosis":
        return (
            "[Событие интерфейса: user_action=get_diagnosis] "
            f"Нажата кнопка «Получить результат диагностики» для машины {request.vehicle_id}, "
            f"проверка {request.session_id}."
        )
    return request.message


def _system_prompt(base: str, vehicle: Any, request: TurnRequest) -> str:
    mode = request.ui_mode if request.ui_mode in UI_MODES else "standard"
    card = (
        f"ТС {vehicle.vehicle_id} ({vehicle.make} {vehicle.model}), "
        f"двигатель {vehicle.engine_model}, "
        f"топливо {vehicle.fuel}; проверка {request.session_id}"
    )
    return f"{base}\n\n## Контекст диалога\n{card}\nui_mode = {mode}\nlang = {request.lang}\n"
