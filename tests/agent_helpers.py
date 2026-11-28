"""Заготовки для тестов агента: модель-заглушка с заранее заданными ответами и сборка сервисов.

Настоящий Neuraldeep в юнит-тестах не вызываем (AGENTS.md): модель подменяется ScriptedChat.
Инструменты ходят в настоящие заглушки mock/ через TestClient.
"""

import json
from typing import Any

import yaml
from fastapi.testclient import TestClient
from mock_ml.app import app as ml_stub
from mock_toir.app import app as toir_stub

from app.agent.llm import LlmReply, ToolCall
from app.agent.runner import AgentServices
from app.agent.scenarios import Scenario, ScenarioFile
from app.agent.services import build_agent_services
from app.clients.ml_client import MlClient
from app.clients.toir_client import Reference, ToirClient
from app.config import Settings
from app.data.vehicles import VehicleStore
from app.obs.journal import MemoryJournal
from app.rag.manifest import load_manifest
from app.rag.search import Fragment
from app.tools import draft_ticket, get_diagnosis
from app.tools.runtime import Runtime, TurnContext
from tests.helpers import REPO_ROOT, STUB_BASE, VEHICLES_PATH

MANIFEST_PATH = REPO_ROOT / "data" / "manuals" / "manifest.yaml"
STAND_SCENARIOS_PATH = REPO_ROOT / "eval" / "agent_scenarios.yaml"
# Сценарии стенда (eval/agent_scenarios.yaml) ссылаются на реальный парк заказчика. В юнит-тестах
# идентификаторы подменяются на синтетические из tests/fixtures (тот же сюжет, данные придуманы).
_STAND_TO_FIXTURE = {
    "T792HO98": "TST-A001",
    "P456AT178": "TST-A001",
    "M333YK47": "TST-B002",
    "M260EH47": "TST-C003",
    "C596XT78": "TST-C003",
    "S-0043": "S-9002",
    "S-0001": "S-9001",
    "S-0003": "S-9003",
    "S-0079": "S-9008",
    "S-0082": "S-9009",
    "S-0083": "S-9010",
}
DIAG_VEHICLE = "TST-A001"  # ЯМЗ-236М2, F02 при оценке 0,85 и уверенности 0,91 → приоритет high
DIAG_SESSION = "S-9002"
YAMZ236_RK = "236.01.01 РК"
YAMZ536_RE = "536.3902150 РЭ"


def load_fixture_scenarios() -> list[Scenario]:
    """Сценарии стенда с идентификаторами синтетического парка. Файл в репозитории не меняется."""
    text = STAND_SCENARIOS_PATH.read_text(encoding="utf-8")
    for stand_id, fixture_id in _STAND_TO_FIXTURE.items():
        text = text.replace(stand_id, fixture_id)
    return ScenarioFile.model_validate(yaml.safe_load(text)).scenarios


class ScriptedChat:
    """Модель-заглушка: отдаёт заранее заданные ответы по очереди и запоминает вызовы."""

    def __init__(self, replies: list[LlmReply]) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_token: Any,
        timeout_s: float,
    ) -> LlmReply:
        self.calls.append({"messages": messages, "tools": tools})
        if not self._replies:
            raise AssertionError("у модели-заглушки закончились заготовленные ответы")
        reply = self._replies.pop(0)
        if on_token is not None and reply.content:
            on_token(reply.content)
        return reply


def reply(content: str = "", calls: list[tuple[str, dict[str, Any]]] | None = None) -> LlmReply:
    tool_calls = [
        ToolCall(id=f"call_{index}", name=name, arguments=json.dumps(args, ensure_ascii=False))
        for index, (name, args) in enumerate(calls or [])
    ]
    return LlmReply(
        content=content,
        tool_calls=tool_calls,
        model="stub-model",
        prompt_tokens=100,
        completion_tokens=20,
        ttft_ms=120,
        tok_per_s=40.0,
        ms=500,
    )


def manual_fragment(text: str = "Момент затяжки гаек головки блока 150 Н·м") -> Fragment:
    return Fragment(
        manual_id="yamz236_rk",
        manual=YAMZ236_RK,
        pdf_page=267,
        section="Головка блока цилиндров",
        text=text,
        score=0.95,
    )


def make_services(llm: ScriptedChat, *, max_tool_calls: int = 8) -> AgentServices:
    services = build_agent_services(
        Settings(vehicles_path=VEHICLES_PATH),
        VehicleStore.load(VEHICLES_PATH),
        load_manifest(MANIFEST_PATH),
        MlClient(STUB_BASE, http=TestClient(ml_stub)),
        ToirClient(STUB_BASE, http=TestClient(toir_stub)),
    )
    services.llm = llm
    services.journal = MemoryJournal()
    services.max_tool_calls = max_tool_calls
    return services


def make_ready_draft(services: AgentServices) -> tuple[str, str]:
    """Черновик заявки по F02 и фрагменту руководства диалога. Возвращает (draft_id, token)."""
    turn = TurnContext(vehicle_id=DIAG_VEHICLE, session_id=DIAG_SESSION)
    runtime = Runtime(deps=services.deps, turn=turn)
    diagnosis = get_diagnosis.run(
        runtime, get_diagnosis.Args(vehicle_id=DIAG_VEHICLE, session_id=DIAG_SESSION)
    )
    assert diagnosis["ok"], diagnosis
    turn.remember([manual_fragment()])
    result = draft_ticket.run(
        runtime,
        draft_ticket.Args(
            vehicle_id=DIAG_VEHICLE,
            session_id=DIAG_SESSION,
            conclusion="Износ гаек головки блока, нужна дефектовка узла",
            urgency="high",
            operations=["Снять головку блока", "Проверить затяжку гаек"],
            spare_parts=[],
            references=[Reference(manual=YAMZ236_RK, pdf_page=267)],
        ),
    )
    assert result["ok"], result
    data = next(payload for name, payload in turn.events if name == "ticket_draft")
    return data["draft_id"], data["confirm_token"]
