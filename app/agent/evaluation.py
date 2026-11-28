"""Прогон сценариев агента на живой модели и отчёт eval/agent_report.md (ТЗ §8.3, фаза 06).

Каждый сценарий идёт на своих копиях сервисов: журнал в памяти, черновики и заявки в памяти,
checkpointer новый. Поэтому прогон ничего не пишет в Postgres и не отправляет заявку в ТОиР.
Подтверждение заявки в прогоне не вызывается: черновик показываем, но не отправляем.
"""

import re
from collections import Counter
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
    options = {"generated_at": datetime.now(), "model": model, "min_score": min_score}
    costs = [run.cost_rub for run in runs]
    # ₽ прогона — сумма по сценариям; если хотя бы у одного сценария цены нет, прогон без ₽.
    cost = None if any(item is None for item in costs) else sum(costs, Decimal(0))
    return EvalResult(
        report_md=render_report(runs, details=False, **options),
        report_full_md=render_report(runs, details=True, **options),
        passed=sum(1 for run in runs if run.passed),
        total=len(runs),
        cases=[_run_case(run) for run in runs],
        model=model,
        cost_rub=cost,
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
    for step in steps:
        if step.name == "no_data_format":
            outcome.general_cut += int((step.output or {}).get("general_cut", 0))
        if step.name == "consult_removed":
            outcome.consult_removed += len((step.output or {}).get("removed", []))
    outcome.tool_errors = [
        f"{step.name}: {step.error}" for step in steps if step.kind == "tool" and step.error
    ]
    citations = [step for step in steps if step.name == "citation_check"]
    if citations:
        result = citations[-1].output or {}
        outcome.citation_ok = result.get("ok")
        outcome.citation_problems = list(result.get("problems", []))
        outcome.model_problems = list(result.get("model_problems", []))
        outcome.model_fixed = fixed_by_code(outcome.model_problems, outcome.citation_problems)
    raw = [step for step in steps if step.name == "raw_answer"]
    if raw:
        outcome.raw_answer = str((raw[-1].output or {}).get("text", ""))
    summary = journal.runs.get(run_id) if run_id is not None else None
    return outcome, meta, summary.cost_rub if summary else None


def render_report(
    runs: list[ScenarioRun],
    *,
    generated_at: datetime,
    model: str,
    min_score: float,
    details: bool = False,
) -> str:
    """Отчёт по сценариям. details=False — только метрики (для eval/*.md и git, п. 9.1).

    details=True добавляет ответы агента и фрагменты примеров ошибок: такой отчёт хранится
    только в БД и показывается в /admin/logs.
    """
    passed = sum(1 for run in runs if run.passed)
    general_cut = sum(run.outcome.general_cut for run in runs)
    consult = sum(run.outcome.consult_removed for run in runs)
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
        f"Общих сведений вырезано кодом: {general_cut}. "
        f"Фраз про специалиста вырезано кодом: {consult}.",
        "",
        "## Сводка",
        "",
        "| Сценарий | Вердикт | Вызовы инструментов | Цитаты | ttft, мс | ток/с | ₽ | Результат |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += [_summary_row(run) for run in runs]
    lines += _model_errors_section(runs, details)
    lines += ["", "## Детали", ""]
    for run in runs:
        lines += _details(run, details)
    return "\n".join(lines) + "\n"


def fixed_by_code(model_problems: list[str], final_problems: list[str]) -> int:
    """Сколько ошибок цитат модели код убрал: ошибка модели, которой нет в финальном ответе."""
    still_there = sum((Counter(model_problems) & Counter(final_problems)).values())
    return len(model_problems) - still_there


def _model_errors_section(runs: list[ScenarioRun], details: bool) -> list[str]:
    found = sum(len(run.outcome.model_problems) for run in runs)
    fixed = sum(run.outcome.model_fixed for run in runs)
    lines = [
        "",
        "## Ошибки цитат модели",
        "",
        f"Ошибок цитат модели, исправлено кодом: {fixed} (выявлено всего: {found}). "
        "Сценарий эти ошибки не валят: проверка идёт по финальному ответу.",
    ]
    if not details:
        return lines
    pairs = [
        (run.scenario.id, pair)
        for run in runs
        for pair in violation_excerpts(run.outcome.raw_answer, run.outcome.model_problems)
    ]
    shown = pairs[:VIOLATION_LIMIT]
    if shown:
        lines += ["", f"Первые {len(shown)} примера (сырой ответ модели до правок кодом):", ""]
    for scenario_id, (problem, excerpt) in shown:
        phrase = f"«{excerpt}»" if excerpt else "не найдена в сыром тексте"
        lines += [f"- {scenario_id}: {problem}", f"  фраза: {phrase}"]
    return lines


def _summary_row(run: ScenarioRun) -> str:
    outcome = run.outcome
    verdict = f"{outcome.light or '—'}, приоритет {outcome.urgency or '—'}"
    tools = ", ".join(dict.fromkeys(outcome.tools)) or "нет"
    citations = {True: "ок", False: "нарушено", None: "—"}[outcome.citation_ok]
    if outcome.model_fixed:
        citations += f" (модель: исправлено кодом {outcome.model_fixed})"
    cost = "—" if run.cost_rub is None else f"{run.cost_rub:.4f}"
    result = "PASS" if run.passed else "FAIL"
    return (
        f"| {run.scenario.id} | {verdict} | {tools} | {citations} | "
        f"{_or_dash(run.ttft_ms)} | {_or_dash(run.tok_per_s)} | {cost} | {result} |"
    )


def _details(run: ScenarioRun, details: bool) -> list[str]:
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
    if outcome.model_problems:
        lines.append(
            f"Ошибки цитат модели: {len(outcome.model_problems)}, "
            f"исправлено кодом: {outcome.model_fixed}."
        )
    if outcome.citation_problems:
        lines += ["", "Нарушения цитат в финальном ответе:"]
        lines += [f"- {problem}" for problem in outcome.citation_problems]
    if not details:
        lines += ["", f"Длина ответа: {len(outcome.answer.strip())} символов (текст в БД)."]
        lines.append("")
        return lines
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


EXCERPT_RADIUS = 200


def _line_with(raw: str, claim: str) -> str:
    """Строка сырого ответа с цифрой; длинная строка сокращается окном вокруг цифры."""
    index = raw.find(claim)
    if not claim or index < 0:
        return ""
    start = raw.rfind("\n", 0, index) + 1
    end = raw.find("\n", index)
    segment = raw[start : end if end >= 0 else len(raw)]
    line = segment.strip()
    local = index - start - (len(segment) - len(segment.lstrip()))
    if len(line) <= 2 * EXCERPT_RADIUS + len(claim):
        return line
    left = max(0, local - EXCERPT_RADIUS)
    right = min(len(line), local + len(claim) + EXCERPT_RADIUS)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(line) else ""
    return prefix + line[left:right] + suffix
