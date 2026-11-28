"""Граф агента LangGraph (ТЗ §6.1): цикл agent ↔ tools, затем проверка цитат.

Выбор инструмента делает модель. Код только исполняет вызовы, ограничивает их число
и проверяет ответ guardrails (ТЗ §6.4). Состояние диалога хранит checkpointer (Postgres в проде).
"""

import contextvars
import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from app.agent.guards import (
    apply_conflict_block,
    check_answer,
    find_injection_markers,
    raw_answer_snapshot,
    redact_injection,
    sanitize_answer,
    strip_consult,
    tidy_answer,
    wrap_tool_data,
)
from app.agent.llm import ChatModel, root_cause
from app.agent.no_data import format_no_data, needs_no_data_format
from app.obs.failure import Failure, describe_failure
from app.obs.journal import Journal, StepRecord
from app.obs.prices import cost_rub
from app.obs.retry import take_retries
from app.obs.usage import UsageEvent, take_usage
from app.rag.citations import fix_citations, has_verified_citation
from app.rag.search import Fragment
from app.tools.registry import ToolSpec, openai_tools
from app.tools.runtime import Runtime, ToolDeps, TurnContext

logger = logging.getLogger("app.agent")

TIMEOUT_TEXT = "Ответ занимает слишком много времени. Повторите вопрос."
NO_TOOLS_LEFT_NOTE = (
    "Лимит вызовов инструментов исчерпан: ответь механику по уже полученным данным."
)
MIN_CALL_TIMEOUT_S = 15.0  # ниже этого модель не успевает ответить на промпт около 6k токенов
# Данные машины грузим кодом параллельно до первого вызова модели: результаты уже в контексте.
PREFETCH_TOOLS = ("get_vehicle", "get_diagnosis", "get_history")
# Инструмент, который можно вызвать не больше N раз за ход (остальное — текст отказа модели).
MAX_CALLS_PER_TOOL = {"search_manual": 3}
# В модель уходят только последние ходы сессии: иначе контекст растёт до ~140k токенов, и старые
# ответы «нет данных» модель начинает копировать. Полная история остаётся в чекпойнте.
HISTORY_TURNS = 4
PREFETCHED_TEXT = "Этот инструмент уже вызван в начале хода: его данные есть в контексте."
LIMIT_TEXT = "Лимит вызовов этого инструмента в ходе исчерпан: ответь по уже полученным данным."


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    retrieved: list[dict[str, Any]]
    diagnosis: dict[str, Any] | None
    tool_calls: int
    tool_usage: dict[str, int]
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
    cost_total: Decimal = Decimal(0)
    unpriced: bool = False  # есть платный вызов без цены в прайсе: ₽ хода неизвестен

    def add_cost(self, cost: Decimal | None) -> None:
        """Складывает ₽ платного вызова. None — цены нет: ₽ хода станет неизвестным."""
        if cost is None:
            self.unpriced = True
        else:
            self.cost_total += cost

    def cost_rub(self) -> Decimal | None:
        """₽ хода: сумма по шагам; None, если хотя бы один платный шаг без цены."""
        return None if self.unpriced else self.cost_total


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

    def prefetch(state: AgentState) -> dict[str, Any]:
        vehicle_id = deps.turn.vehicle_id
        session_id = deps.turn.session_id
        calls = [
            _call("get_vehicle", {"vehicle_id": vehicle_id}, "prefetch_vehicle"),
            _call(
                "get_diagnosis",
                {"vehicle_id": vehicle_id, "session_id": session_id},
                "prefetch_diagnosis",
            ),
            _call("get_history", {"vehicle_id": vehicle_id}, "prefetch_history"),
        ]
        # Каждый вызов в своём копии контекста: мешок повторов хода виден и в потоке.
        jobs = [(contextvars.copy_context(), call) for call in calls]
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            outcomes = list(
                pool.map(lambda job: job[0].run(_call_tool, deps, runtime, job[1]), jobs)
            )
        messages: list[AnyMessage] = [AIMessage(content="", tool_calls=calls)]
        messages += [
            _finish_tool(deps, call, result, error, failure)
            for call, (result, error, failure) in zip(calls, outcomes, strict=True)
        ]
        _flush_events(deps)
        return {"messages": messages, "diagnosis": deps.turn.diagnosis}

    def agent(state: AgentState) -> dict[str, Any]:
        elapsed = time.monotonic() - state["started_at"]
        if elapsed >= timeout_s:
            return {"messages": [AIMessage(content=TIMEOUT_TEXT)]}
        calls = state["tool_calls"]
        usage = state.get("tool_usage") or {}
        messages = [{"role": "system", "content": deps.system_prompt}]
        if calls >= deps.max_tool_calls:
            messages.append({"role": "system", "content": NO_TOOLS_LEFT_NOTE})
        messages += to_openai(recent_messages(state["messages"]))
        offered = {
            name: spec for name, spec in deps.registry.items() if _refusal(name, usage) is None
        }
        tools = openai_tools(offered) if calls < deps.max_tool_calls and offered else None
        call_timeout = max(MIN_CALL_TIMEOUT_S, timeout_s - elapsed)
        logger.info("вызов модели агента: timeout_s=%.1f, прошло=%.1f с", call_timeout, elapsed)
        try:
            reply = deps.llm.complete(
                messages,
                tools,
                lambda text: deps.emit("token", {"text": text}),
                call_timeout,
            )
        except Exception as exc:
            record_error(deps, "chat", exc, output=_timing(call_timeout, elapsed))
            raise
        _count_llm(deps, reply, call_timeout, elapsed)
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
        usage = dict(state.get("tool_usage") or {})
        for call in last.tool_calls:
            count += 1
            refusal = _refusal(call["name"], usage)
            if refusal is not None:
                result, error, failure = {"ok": False, "error": refusal}, "tool_refused", None
            else:
                usage[call["name"]] = usage.get(call["name"], 0) + 1
                result, error, failure = _call_tool(deps, runtime, call)
            outputs.append(_finish_tool(deps, call, result, error, failure))
            _flush_events(deps)
        return {
            "messages": outputs,
            "tool_calls": count,
            "tool_usage": usage,
            "retrieved": [fragment.model_dump() for fragment in deps.turn.retrieved],
            "diagnosis": deps.turn.diagnosis,
        }

    def finalize(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        model_text = str(last.content)
        fragments = deps.turn.fetched_now
        # Ответ модели до правок кодом: по нему eval считает ошибки цитат самой модели.
        deps.record(
            StepRecord(
                run_id=deps.run_id,
                n=deps.next_step(),
                kind="guardrail",
                name="raw_answer",
                output=raw_answer_snapshot(model_text),
            )
        )
        text = model_text
        check = check_answer(text, fragments)
        regenerated = False
        if not check.ok:
            text = _fix_citations_step(deps, text)
            check = check_answer(text, fragments)
        if not check.ok:
            text = _regenerate(deps, state, check.problems)
            regenerated = True
            text = _fix_citations_step(deps, text)
            check = check_answer(text, fragments)
        if not check.ok:
            text = sanitize_answer(text, fragments)
        text, consult_removed = strip_consult(text)
        if consult_removed:
            deps.record(
                StepRecord(
                    run_id=deps.run_id,
                    n=deps.next_step(),
                    kind="guardrail",
                    name="consult_removed",
                    output={"removed": consult_removed},
                )
            )
        text = tidy_answer(text, [conflict.topic for conflict in deps.tools.conflicts])
        no_data_turn = deps.turn.no_data_reported and not deps.turn.retrieved
        # Ответ со ссылкой на найденную в этом ходе страницу не переписываем под «нет данных»:
        # фраза про один подвопрос не отменяет фрагмент, который модель уже процитировала.
        grounded = (
            bool(fragments)
            and has_verified_citation(text, fragments)
            and check_answer(text, fragments).ok
        )
        if needs_no_data_format(text, no_data_turn) and not grounded:
            formatted = format_no_data(text, _engine_model(deps))
            text = formatted.text
            deps.record(
                StepRecord(
                    run_id=deps.run_id,
                    n=deps.next_step(),
                    kind="guardrail",
                    name="no_data_format",
                    output={
                        "general_cut": formatted.general_cut,
                        "next_step_added": formatted.next_step_added,
                    },
                )
            )
        # Итог — по тексту для механика; блок противоречия собирает код после этой проверки.
        final = check_answer(text, fragments)
        deps.record(
            StepRecord(
                run_id=deps.run_id,
                n=deps.next_step(),
                kind="guardrail",
                name="citation_check",
                output={
                    "ok": final.ok,
                    "problems": final.problems,
                    "model_problems": check_answer(model_text, fragments).problems,
                    "regenerated": regenerated,
                },
            )
        )
        if deps.turn.conflicts:
            block = apply_conflict_block(text, deps.turn.conflicts)
            text = block.text
            deps.record(
                StepRecord(
                    run_id=deps.run_id,
                    n=deps.next_step(),
                    kind="guardrail",
                    name="conflict_notice",
                    output={
                        "notices": [notice.id for notice in deps.turn.conflicts],
                        "trigger": {notice.id: notice.trigger for notice in deps.turn.conflicts},
                        "removed": block.removed,
                        "consult_removed": block.consult_removed,
                    },
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
    builder.add_node("prefetch", prefetch)
    builder.add_node("agent", agent)
    builder.add_node("tools", tools_node)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "prefetch")
    builder.add_edge("prefetch", "agent")
    builder.add_conditional_edges(
        "agent", route_after_agent, {"tools": "tools", "finalize": "finalize"}
    )
    builder.add_edge("tools", "agent")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def recent_messages(messages: list[AnyMessage], turns: int = HISTORY_TURNS) -> list[AnyMessage]:
    """Последние `turns` ходов. Ход начинается с HumanMessage, поэтому пары tool_calls не рвутся."""
    starts = [index for index, message in enumerate(messages) if isinstance(message, HumanMessage)]
    if len(starts) <= turns:
        return messages
    return messages[starts[-turns] :]


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


def _call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id}


def _engine_model(deps: AgentDeps) -> str:
    """Двигатель машины диалога для формулировки «нет в руководстве» (запасной вариант — общий)."""
    vehicle = deps.tools.vehicles.get(deps.turn.vehicle_id)
    return vehicle.engine_model if vehicle is not None else "этот двигатель"


def _refusal(name: str, usage: dict[str, int]) -> str | None:
    """Текст отказа, если инструмент уже получен в начале хода или исчерпан лимит."""
    if name in PREFETCH_TOOLS:
        return PREFETCHED_TEXT
    limit = MAX_CALLS_PER_TOOL.get(name)
    if limit is not None and usage.get(name, 0) >= limit:
        return LIMIT_TEXT
    return None


def _call_tool(
    deps: AgentDeps, runtime: Runtime, call: dict[str, Any]
) -> tuple[dict[str, Any], str | None, Failure | None]:
    spec = deps.registry.get(call["name"])
    if spec is None:
        return {"ok": False, "error": "Такого инструмента нет."}, "unknown_tool", None
    return _execute(spec, runtime, call["args"])


def _finish_tool(
    deps: AgentDeps,
    call: dict[str, Any],
    result: dict[str, Any],
    error: str | None,
    failure: Failure | None = None,
) -> ToolMessage:
    """Журнал и ответ модели: команды из данных вырезаем до показа модели (ТЗ §6.4, п.5)."""
    _flush_external(deps)
    name = call["name"]
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
        payload = redact_injection(payload)
    deps.record(
        StepRecord(
            run_id=deps.run_id,
            n=deps.next_step(),
            kind="tool",
            name=name,
            input=call["args"],
            output=result,
            error=error,
            error_class=failure.error_class if failure else None,
            error_message=failure.error_message if failure else None,
        )
    )
    return ToolMessage(content=wrap_tool_data(payload), tool_call_id=call["id"], name=name)


def _execute(
    spec: ToolSpec, runtime: Runtime, raw_args: dict[str, Any]
) -> tuple[dict[str, Any], str | None, Failure | None]:
    try:
        args = spec.args.model_validate(raw_args)
    except ValidationError as exc:
        message = f"неверные аргументы: {exc.errors()[0]['msg']}"
        return {"ok": False, "error": message}, "bad_args", None
    try:
        return spec.run(runtime, args), None, None
    except Exception as exc:  # граница инструмента: модель получает текст, а не трассу
        logger.exception("инструмент %s упал", spec.name)
        failure = describe_failure(exc)
        error = f"tool_error: {failure.error_class}: {failure.error_message}"
        return {"ok": False, "error": "Инструмент временно недоступен, повторите."}, error, failure


def record_error(
    deps: AgentDeps, name: str, exc: BaseException, output: dict[str, Any] | None = None
) -> None:
    """Шаг журнала kind=error: класс и краткий текст исходной ошибки, без секретов."""
    _flush_external(deps)
    failure = describe_failure(root_cause(exc))
    deps.record(
        StepRecord(
            run_id=deps.run_id,
            n=deps.next_step(),
            kind="error",
            name=name,
            output=output,
            error_class=failure.error_class,
            error_message=failure.error_message,
        )
    )


def _flush_external(deps: AgentDeps) -> None:
    """Повторы и расход внешних сервисов, накопленные с прошлого шага, пишем до очередного шага."""
    for event in take_retries():
        deps.record(
            StepRecord(
                run_id=deps.run_id,
                n=deps.next_step(),
                kind="retry",
                name=event.service,
                output={"attempt": event.attempt, "pause_s": event.pause_s},
                error_class=event.error_class,
                error_message=event.error_message,
            )
        )
    for usage in take_usage():
        cost = _usage_cost(usage)
        if usage.kind != "rerank":  # реранк в ₽ не входит: сервис не отдаёт число токенов
            deps.stats.add_cost(cost)
        deps.record(
            StepRecord(
                run_id=deps.run_id,
                n=deps.next_step(),
                kind=usage.kind,
                name=usage.model,
                ms=usage.ms,
                prompt_tokens=usage.prompt_tokens,
                model=usage.model,
                cost_rub=cost,
            )
        )


def _usage_cost(usage: UsageEvent) -> Decimal | None:
    if usage.prompt_tokens is None:
        return None
    return cost_rub(usage.model, usage.prompt_tokens, 0)


def _timing(timeout_s: float, elapsed_s: float) -> dict[str, float]:
    return {"timeout_s": round(timeout_s, 1), "elapsed_s": round(elapsed_s, 1)}


def _flush_events(deps: AgentDeps) -> None:
    for name, data in deps.turn.events:
        if name == "verdict" and not deps.turn.show_verdict:
            continue
        deps.emit(name, data)
    deps.turn.events.clear()


def _fix_citations_step(deps: AgentDeps, text: str) -> str:
    """Замена неверных ссылок кодом; каждая замена — шаг citation_fixed (from → to)."""
    fixed = fix_citations(text, deps.turn.fetched_now)
    if fixed.fixes:
        deps.record(
            StepRecord(
                run_id=deps.run_id,
                n=deps.next_step(),
                kind="guardrail",
                name="citation_fixed",
                output={
                    "fixes": [
                        {"from": fix.old, "to": fix.new, "claim": fix.claim} for fix in fixed.fixes
                    ]
                },
            )
        )
    return fixed.text


def _regenerate(deps: AgentDeps, state: AgentState, problems: list[str]) -> str:
    """Одна перегенерация при нарушении цитат (ТЗ §6.4 п.1). Без стрима: текст заменим целиком."""
    note = (
        "Ответ содержит цифры или ссылки без подтверждения фрагментами: "
        + "; ".join(problems)
        + ". Перепиши ответ: используй только фрагменты search_manual этого диалога, "
        "у каждой цифры с единицей ставь ссылку [обозначение, стр. N]."
    )
    messages = [{"role": "system", "content": deps.system_prompt}]
    messages += to_openai(recent_messages(state["messages"]))
    messages.append({"role": "user", "content": note})
    # Таймаут — из бюджета хода, но не меньше MIN_CALL_TIMEOUT_S (раньше был фиксированный 5 с).
    elapsed = time.monotonic() - state["started_at"]
    call_timeout = max(MIN_CALL_TIMEOUT_S, deps.timeout_s - elapsed)
    logger.info("перегенерация ответа: timeout_s=%.1f, прошло=%.1f с", call_timeout, elapsed)
    try:
        reply = deps.llm.complete(messages, None, None, call_timeout)
    except Exception as exc:
        record_error(deps, "regenerate", exc, output=_timing(call_timeout, elapsed))
        raise
    _count_llm(deps, reply, call_timeout, elapsed)
    return reply.content


def _count_llm(deps: AgentDeps, reply: Any, timeout_s: float, elapsed_s: float) -> None:
    _flush_external(deps)
    stats = deps.stats
    stats.prompt_tokens += reply.prompt_tokens
    stats.completion_tokens += reply.completion_tokens
    stats.model = reply.model
    if stats.ttft_ms is None:
        stats.ttft_ms = reply.ttft_ms
    stats.tok_per_s = reply.tok_per_s
    cost = cost_rub(reply.model, reply.prompt_tokens, reply.completion_tokens)
    stats.add_cost(cost)
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
            cost_rub=cost,
            output={
                "tool_calls": [call.name for call in reply.tool_calls],
                **_timing(timeout_s, elapsed_s),
            },
        )
    )


def _parse_args(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"__raw__": raw}
    return value if isinstance(value, dict) else {"__raw__": raw}
