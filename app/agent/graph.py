"""Граф агента LangGraph (ТЗ §6.1): цикл agent ↔ tools, затем проверка цитат.

Выбор инструмента делает модель. Код только исполняет вызовы, ограничивает их число
и проверяет ответ guardrails (ТЗ §6.4). Состояние диалога хранит checkpointer (Postgres в проде).
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from app.agent.guards import check_answer, find_injection_markers, sanitize_answer, wrap_tool_data
from app.agent.llm import ChatModel
from app.obs.journal import Journal, StepRecord
from app.rag.search import Fragment
from app.tools.registry import ToolSpec, openai_tools
from app.tools.runtime import Runtime, ToolDeps, TurnContext

logger = logging.getLogger("app.agent")

TIMEOUT_TEXT = "Ответ занимает слишком много времени. Повторите вопрос."
NO_TOOLS_LEFT_NOTE = (
    "Лимит вызовов инструментов исчерпан: ответь механику по уже полученным данным."
)
MIN_CALL_TIMEOUT_S = 5.0


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    retrieved: list[dict[str, Any]]
    diagnosis: dict[str, Any] | None
    tool_calls: int
    started_at: float


@dataclass
class RunStats:
    """Итоги хода для журнала и meta-события: токены, TTFT первого вызова, ток/с."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    steps: int = 0
    ttft_ms: int | None = None
    tok_per_s: float | None = None
    model: str | None = None


@dataclass
class AgentDeps:
    llm: ChatModel
    tools: ToolDeps
    registry: dict[str, ToolSpec]
    journal: Journal
    run_id: int
    turn: TurnContext
    emit: Callable[[str, dict[str, Any]], None]
    system_prompt: str
    timeout_s: float
    max_tool_calls: int
    stats: RunStats = field(default_factory=RunStats)

    def next_step(self) -> int:
        self.stats.steps += 1
        return self.stats.steps

    def record(self, step: StepRecord) -> None:
        self.journal.add_step(step)


def build_graph(deps: AgentDeps, checkpointer: Any) -> Any:
    """Собирает граф под один ход: инструменты и поток событий замкнуты на контекст хода."""
    runtime = Runtime(deps=deps.tools, turn=deps.turn)
    timeout_s = deps.timeout_s

    def prepare(state: AgentState) -> dict[str, Any]:
        deps.turn.retrieved = [Fragment.model_validate(item) for item in state.get("retrieved", [])]
        deps.turn.fetched_now = []
        deps.turn.diagnosis = state.get("diagnosis")
        return {}

    def agent(state: AgentState) -> dict[str, Any]:
        elapsed = time.monotonic() - state["started_at"]
        if elapsed >= timeout_s:
            return {"messages": [AIMessage(content=TIMEOUT_TEXT)]}
        calls = state["tool_calls"]
        messages = [{"role": "system", "content": deps.system_prompt}]
        if calls >= deps.max_tool_calls:
            messages.append({"role": "system", "content": NO_TOOLS_LEFT_NOTE})
        messages += to_openai(state["messages"])
        tools = openai_tools(deps.registry) if calls < deps.max_tool_calls else None
        reply = deps.llm.complete(
            messages,
            tools,
            lambda text: deps.emit("token", {"text": text}),
            max(MIN_CALL_TIMEOUT_S, timeout_s - elapsed),
        )
        _count_llm(deps, reply)
        tool_calls = [
            {
                "name": call.name,
                "args": _parse_args(call.arguments),
                "id": call.id or f"call_{calls}_{i}",
            }
            for i, call in enumerate(reply.tool_calls)
        ]
        if calls >= deps.max_tool_calls:
            tool_calls = []
        return {"messages": [AIMessage(content=reply.content, tool_calls=tool_calls)]}

    def tools_node(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        outputs: list[AnyMessage] = []
        count = state["tool_calls"]
        for call in last.tool_calls:
            count += 1
            outputs.append(_run_tool(deps, runtime, call, count))
            _flush_events(deps)
        return {
            "messages": outputs,
            "tool_calls": count,
            "retrieved": [fragment.model_dump() for fragment in deps.turn.retrieved],
            "diagnosis": deps.turn.diagnosis,
        }

    def finalize(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        text = str(last.content)
        check = check_answer(text, deps.turn.fetched_now)
        if not check.ok:
            text = _regenerate(deps, state, check.problems)
            check = check_answer(text, deps.turn.fetched_now)
        if not check.ok:
            text = sanitize_answer(text, deps.turn.fetched_now)
        deps.record(
            StepRecord(
                run_id=deps.run_id,
                n=deps.next_step(),
                kind="guardrail",
                name="citation_check",
                output={"ok": check.ok, "problems": check.problems},
            )
        )
        return {"messages": [AIMessage(id=last.id, content=text)]}

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "finalize"

    builder = StateGraph(AgentState)
    builder.add_node("prepare", prepare)
    builder.add_node("agent", agent)
    builder.add_node("tools", tools_node)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "agent")
    builder.add_conditional_edges(
        "agent", route_after_agent, {"tools": "tools", "finalize": "finalize"}
    )
    builder.add_edge("tools", "agent")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def to_openai(messages: list[AnyMessage]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            converted.append({"role": "user", "content": str(message.content)})
        elif isinstance(message, AIMessage):
            item: dict[str, Any] = {"role": "assistant", "content": str(message.content or "")}
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["args"], ensure_ascii=False),
                        },
                    }
                    for call in message.tool_calls
                ]
            converted.append(item)
        elif isinstance(message, ToolMessage):
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": str(message.content),
                }
            )
        elif isinstance(message, SystemMessage):
            converted.append({"role": "system", "content": str(message.content)})
    return converted


def _run_tool(deps: AgentDeps, runtime: Runtime, call: dict[str, Any], count: int) -> ToolMessage:
    name = call["name"]
    spec = deps.registry.get(name)
    if spec is None:
        result: dict[str, Any] = {"ok": False, "error": "Такого инструмента нет."}
        error = "unknown_tool"
    else:
        result, error = _execute(spec, runtime, call["args"])
    payload = json.dumps(result, ensure_ascii=False, default=str)
    markers = find_injection_markers(payload)
    if markers:
        deps.record(
            StepRecord(
                run_id=deps.run_id,
                n=deps.next_step(),
                kind="guardrail",
                name="prompt_injection_detected",
                output={"tool": name, "markers": markers},
            )
        )
    deps.record(
        StepRecord(
            run_id=deps.run_id,
            n=deps.next_step(),
            kind="tool",
            name=name,
            input=call["args"],
            output=result,
            error=error,
        )
    )
    return ToolMessage(content=wrap_tool_data(payload), tool_call_id=call["id"], name=name)


def _execute(
    spec: ToolSpec, runtime: Runtime, raw_args: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    try:
        args = spec.args.model_validate(raw_args)
    except ValidationError as exc:
        return {"ok": False, "error": f"неверные аргументы: {exc.errors()[0]['msg']}"}, "bad_args"
    try:
        return spec.run(runtime, args), None
    except Exception:  # граница инструмента: модель получает текст, а не трассу
        logger.exception("инструмент %s упал", spec.name)
        return {"ok": False, "error": "Инструмент временно недоступен, повторите."}, "tool_error"


def _flush_events(deps: AgentDeps) -> None:
    for name, data in deps.turn.events:
        deps.emit(name, data)
    deps.turn.events.clear()


def _regenerate(deps: AgentDeps, state: AgentState, problems: list[str]) -> str:
    """Одна перегенерация при нарушении цитат (ТЗ §6.4 п.1). Без стрима: текст заменим целиком."""
    note = (
        "Ответ содержит цифры или ссылки без подтверждения фрагментами: "
        + "; ".join(problems)
        + ". Перепиши ответ: используй только фрагменты search_manual этого диалога, "
        "у каждой цифры с единицей ставь ссылку [обозначение, стр. N]."
    )
    messages = [{"role": "system", "content": deps.system_prompt}]
    messages += to_openai(state["messages"])
    messages.append({"role": "user", "content": note})
    reply = deps.llm.complete(messages, None, None, MIN_CALL_TIMEOUT_S)
    _count_llm(deps, reply)
    return reply.content


def _count_llm(deps: AgentDeps, reply: Any) -> None:
    stats = deps.stats
    stats.prompt_tokens += reply.prompt_tokens
    stats.completion_tokens += reply.completion_tokens
    stats.model = reply.model
    if stats.ttft_ms is None:
        stats.ttft_ms = reply.ttft_ms
    stats.tok_per_s = reply.tok_per_s
    deps.record(
        StepRecord(
            run_id=deps.run_id,
            n=deps.next_step(),
            kind="llm",
            name="chat",
            ms=reply.ms,
            ttft_ms=reply.ttft_ms,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
            tok_per_s=reply.tok_per_s,
            model=reply.model,
            output={"tool_calls": [call.name for call in reply.tool_calls]},
        )
    )


def _parse_args(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"__raw__": raw}
    return value if isinstance(value, dict) else {"__raw__": raw}
