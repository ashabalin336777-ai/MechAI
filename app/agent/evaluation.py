"""Прогон сценариев агента на живой модели и отчёт eval/agent_report.md (ТЗ §8.3, фаза 06).

Каждый сценарий идёт на своих копиях сервисов: журнал в памяти, черновики и заявки в памяти,
checkpointer новый. Поэтому прогон ничего не пишет в Postgres и не отправляет заявку в ТОиР.
Подтверждение заявки в прогоне не вызывается: черновик показываем, но не отправляем.
"""

import re
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from app.agent.runner import AgentServices, TurnRequest, run_turn
from app.agent.scenarios import CheckResult, Scenario, TurnOutcome, judge
from app.db.agent_store import MemoryAgentStore
from app.db.eval_runs import EvalCase, EvalResult
from app.obs.journal import MemoryJournal

Event = tuple[str, dict[str, Any]]


class ScenarioRun(BaseModel):
    scenario: Scenario
    outcome: TurnOutcome
    checks: list[CheckResult]
    ttft_ms: int | None = None
    tok_per_s: float | None = None
    total_ms: int | None = None
    cost_rub: Decimal | None = None

    @property
    def passed(self) -> bool:
        return self.outcome.error is None and all(check.ok for check in self.checks)


def run_scenario(template: AgentServices, scenario: Scenario, base_prompt: str) -> ScenarioRun:
    journal = MemoryJournal()
    services = replace(
        template,
        deps=replace(template.deps, store=MemoryAgentStore()),
        journal=journal,
        checkpointer=InMemorySaver(),
    )
    events: list[Event] = []
    request = TurnRequest(
        vehicle_id=scenario.vehicle_id,
        session_id=scenario.session_id,
        message=scenario.message,
        user_action=None,
        ui_mode="standard",
        lang="ru",
    )
    run_turn(services, request, base_prompt, lambda name, data: events.append((name, data)))
    outcome, meta, cost = _collect(events, journal)
    return ScenarioRun(
        scenario=scenario,
        outcome=outcome,
        checks=judge(scenario, outcome),
        ttft_ms=meta.get("ttft_ms"),
        tok_per_s=meta.get("tok_per_s"),
        total_ms=meta.get("total_ms"),
        cost_rub=cost,
    )


def run_agent_result(
    template: AgentServices,
    scenarios: list[Scenario],
    base_prompt: str,
    *,
    model: str,
    min_score: float,
) -> EvalResult:
    runs = [run_scenario(template, scenario, base_prompt) for scenario in scenarios]
    return EvalResult(
        report_md=render_report(
            runs, generated_at=datetime.now(), model=model, min_score=min_score
        ),
        passed=sum(1 for run in runs if run.passed),
        total=len(runs),
        cases=[_run_case(run) for run in runs],
    )


def run_agent_report(
    template: AgentServices,
    scenarios: list[Scenario],
    base_prompt: str,
    *,
    model: str,
    min_score: float,
) -> str:
    return run_agent_result(
        template, scenarios, base_prompt, model=model, min_score=min_score
    ).report_md


def _run_case(run: ScenarioRun) -> EvalCase:
    failed = [check.name for check in run.checks if not check.ok]
    notes = list(failed)
    if run.outcome.error:
        notes.insert(0, "ход завершился ошибкой")
    return EvalCase(id=run.scenario.id, passed=run.passed, note="; ".join(notes)[:200])


def _collect(
    events: list[Event], journal: MemoryJournal
) -> tuple[TurnOutcome, dict[str, Any], Decimal | None]:
    outcome = TurnOutcome()
    meta: dict[str, Any] = {}
    for name, data in events:
        if name == "verdict":
            outcome.light = data.get("light")
            outcome.urgency = data.get("urgency")
        elif name == "answer_final":
            outcome.answer = data["text"]
        elif name == "ticket_draft":
            outcome.draft = True
        elif name == "error":
            outcome.error = data["message"]
        elif name == "meta":
            meta = data
    run_id = meta.get("run_id")
    steps = [step for step in journal.steps if step.run_id == run_id]
    outcome.tools = [step.name for step in steps if step.kind == "tool"]
    outcome.journal = [step.name for step in steps]
    outcome.tool_errors = [
        f"{step.name}: {step.error}" for step in steps if step.kind == "tool" and step.error
    ]
    citations = [step for step in steps if step.name == "citation_check"]
    if citations:
        result = citations[-1].output or {}
        outcome.citation_ok = result.get("ok")
        outcome.citation_problems = list(result.get("problems", []))
    raw = [step for step in steps if step.name == "raw_answer"]
    if raw:
        outcome.raw_answer = str((raw[-1].output or {}).get("text", ""))
    summary = journal.runs.get(run_id) if run_id is not None else None
    return outcome, meta, summary.cost_rub if summary else None


def render_report(
    runs: list[ScenarioRun], *, generated_at: datetime, model: str, min_score: float
) -> str:
    passed = sum(1 for run in runs if run.passed)
    lines = [
        "# Отчёт проверки агента на живой модели",
        "",
        f"Дата: {generated_at:%Y-%m-%d %H:%M}. Модель агента: `{model}`. "
        f"Порог RAG_MIN_SCORE: {min_score}.",
        "",
        f"Итог: {passed} из {len(runs)} PASS.",
        "",
        "Заявка не отправлялась: подтверждение в прогоне не вызывается, черновики и журнал "
        "изолированы в памяти прогона.",
        "",
        "## Сводка",
        "",
        "| Сценарий | Вердикт | Вызовы инструментов | Цитаты | ttft, мс | ток/с | ₽ | Результат |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += [_summary_row(run) for run in runs]
    lines += ["", "## Детали", ""]
    for run in runs:
        lines += _details(run)
    return "\n".join(lines) + "\n"


def _summary_row(run: ScenarioRun) -> str:
    outcome = run.outcome
    verdict = f"{outcome.light or '—'}, приоритет {outcome.urgency or '—'}"
    tools = ", ".join(dict.fromkeys(outcome.tools)) or "нет"
    citations = {True: "ок", False: "нарушено", None: "—"}[outcome.citation_ok]
    cost = "—" if run.cost_rub is None else f"{run.cost_rub:.4f}"
    result = "PASS" if run.passed else "FAIL"
    return (
        f"| {run.scenario.id} | {verdict} | {tools} | {citations} | "
        f"{_or_dash(run.ttft_ms)} | {_or_dash(run.tok_per_s)} | {cost} | {result} |"
    )


def _details(run: ScenarioRun) -> list[str]:
    scenario = run.scenario
    outcome = run.outcome
    lines = [
        f"### {scenario.id}. {scenario.title}",
        "",
        f"Машина `{scenario.vehicle_id}`, проверка `{scenario.session_id}`. "
        f"Запрос механика: «{scenario.message}»",
        "",
        f"Результат: **{'PASS' if run.passed else 'FAIL'}**. "
        f"Черновик заявки: {'да' if outcome.draft else 'нет'}. "
        f"Шаги журнала: {', '.join(outcome.journal) or '—'}.",
        "",
    ]
    if outcome.error:
        lines += [f"Ошибка хода: {outcome.error}", ""]
    if outcome.tool_errors:
        lines += [f"Ошибки инструментов: {'; '.join(outcome.tool_errors)}", ""]
    lines.append("Проверки:")
    for check in run.checks:
        status = "PASS" if check.ok else "FAIL"
        suffix = "" if check.ok else f" — {check.detail}"
        lines.append(f"- [{status}] {check.name}{suffix}")
    if outcome.citation_problems:
        lines += ["", "Первые нарушения цитат (строка ответа модели до правок кодом):"]
        for problem, excerpt in violation_excerpts(outcome.raw_answer, outcome.citation_problems):
            lines.append(f"- {problem}")
            lines.append(
                f"  фраза: «{excerpt}»" if excerpt else "  фраза: не найдена в сыром тексте"
            )
    lines += ["", "Ответ агента:", ""]
    answer = outcome.answer.strip() or "_пусто_"
    lines += [f"> {line}" if line else ">" for line in answer.splitlines()]
    lines.append("")
    return lines


def _or_dash(value: int | float | None) -> str:
    return "—" if value is None else str(value)


VIOLATION_LIMIT = 3
QUOTED_RE = re.compile(r"«([^»]+)»")


def violation_excerpts(
    raw: str, problems: list[str], limit: int = VIOLATION_LIMIT
) -> list[tuple[str, str]]:
    """Первые нарушения и строка сырого ответа, где нашлась проверяемая цифра из кавычек."""
    excerpts: list[tuple[str, str]] = []
    for problem in problems[:limit]:
        match = QUOTED_RE.search(problem)
        excerpts.append((problem, _line_with(raw, match.group(1)) if match else ""))
    return excerpts


def _line_with(raw: str, claim: str) -> str:
    index = raw.find(claim)
    if not claim or index < 0:
        return ""
    start = raw.rfind("\n", 0, index) + 1
    end = raw.find("\n", index)
    line = raw[start : end if end >= 0 else len(raw)].strip()
    return line[:300]
