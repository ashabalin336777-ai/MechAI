"""Сценарии проверки агента: загрузка из eval/agent_scenarios.yaml и судейка (ТЗ §8.1, §8.3).

Судейка — чистые функции: по зафиксированному исходу хода решаем PASS/FAIL по каждой проверке.
Модель и БД сюда не входят, поэтому правила проверяются юнит-тестами без сети.
"""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

CONDITION_FIELDS = (
    "light_in",
    "urgency",
    "tools_include",
    "tools_exclude",
    "answer_matches",
    "answer_not_matches",
    "journal_contains",
    "citation_ok",
    "no_draft",
)


class Check(BaseModel):
    name: str = Field(min_length=3)
    light_in: list[Literal["green", "yellow", "orange", "red", "grey"]] | None = None
    urgency: Literal["low", "medium", "high"] | None = None
    tools_include: list[str] | None = None
    tools_exclude: list[str] | None = None
    answer_matches: list[str] | None = None
    answer_not_matches: list[str] | None = None
    journal_contains: str | None = None
    citation_ok: bool | None = None
    no_draft: bool | None = None

    @model_validator(mode="after")
    def _needs_a_condition(self) -> "Check":
        if all(getattr(self, field) is None for field in CONDITION_FIELDS):
            raise ValueError(f"проверка «{self.name}» без условий")
        for pattern in (self.answer_matches or []) + (self.answer_not_matches or []):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"битое регулярное выражение «{pattern}»: {exc}") from exc
        return self


class Scenario(BaseModel):
    id: str = Field(min_length=2)
    title: str = Field(min_length=3)
    vehicle_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=3)
    checks: list[Check] = Field(min_length=1)


class ScenarioFile(BaseModel):
    scenarios: list[Scenario] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "ScenarioFile":
        ids = [scenario.id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("id сценариев должны быть уникальными")
        return self


class TurnOutcome(BaseModel):
    """Зафиксированный исход хода: всё, что нужно судейке, без ссылок на сервисы."""

    light: str | None = None
    urgency: str | None = None
    tools: list[str] = Field(default_factory=list)
    journal: list[str] = Field(default_factory=list)
    answer: str = ""
    # Текст модели до правок кодом (шаг raw_answer): из него берём примеры ошибок цитат модели.
    raw_answer: str = ""
    # Итог проверки цитат по финальному ответу (то, что видит механик): проверка сценария.
    citation_ok: bool | None = None
    citation_problems: list[str] = Field(default_factory=list)
    # Ошибки цитат самой модели (до правок кода) и сколько из них код исправил. Сценарий не валят.
    model_problems: list[str] = Field(default_factory=list)
    model_fixed: int = 0
    tool_errors: list[str] = Field(default_factory=list)
    draft: bool = False
    error: str | None = None
    # Метрики кода (этап 07a): блоки с числами вырезаны, фразы про специалиста убраны.
    general_cut: int = 0
    consult_removed: int = 0


class CheckResult(BaseModel):
    name: str
    ok: bool
    detail: str


def load_scenarios(path: Path) -> list[Scenario]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ScenarioFile.model_validate(raw).scenarios


def judge(scenario: Scenario, outcome: TurnOutcome) -> list[CheckResult]:
    return [_judge_check(check, outcome) for check in scenario.checks]


def _judge_check(check: Check, outcome: TurnOutcome) -> CheckResult:
    problems: list[str] = []
    if outcome.error is not None:
        problems.append(f"ошибка хода: {outcome.error}")
    if check.light_in is not None and outcome.light not in check.light_in:
        problems.append(f"вердикт {outcome.light}, ожидали {'/'.join(check.light_in)}")
    if check.urgency is not None and outcome.urgency != check.urgency:
        problems.append(f"приоритет {outcome.urgency}, ожидали {check.urgency}")
    if check.tools_include:
        missing = [name for name in check.tools_include if name not in outcome.tools]
        if missing:
            problems.append(f"не вызваны инструменты: {', '.join(missing)}")
    if check.tools_exclude:
        called = [name for name in check.tools_exclude if name in outcome.tools]
        if called:
            problems.append(f"вызваны запрещённые инструменты: {', '.join(called)}")
    for pattern in check.answer_matches or []:
        if not re.search(pattern, outcome.answer, re.IGNORECASE):
            problems.append(f"в ответе нет: {pattern}")
    for pattern in check.answer_not_matches or []:
        if re.search(pattern, outcome.answer, re.IGNORECASE):
            problems.append(f"в ответе запрещённое: {pattern}")
    if check.journal_contains is not None and check.journal_contains not in outcome.journal:
        problems.append(f"в журнале нет шага {check.journal_contains}")
    if check.citation_ok is not None and outcome.citation_ok != check.citation_ok:
        detail = "; ".join(outcome.citation_problems) or "нет данных"
        problems.append(f"проверка цитат {outcome.citation_ok}: {detail}")
    if check.no_draft and outcome.draft:
        problems.append("создан черновик заявки")
    return CheckResult(
        name=check.name,
        ok=not problems,
        detail="; ".join(problems) if problems else "ок",
    )
