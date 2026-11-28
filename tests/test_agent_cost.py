"""₽ в журнале: стоимость шагов LLM, эмбеддингов и реранка, ₽ хода и итог прогона (ТЗ §14).

Модель и сервисы подменены: сети нет. Цены берём из app/obs/prices.py тем же вызовом, что и код.
"""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx

from app.agent.evaluation import run_agent_result
from app.agent.llm import LlmReply
from app.agent.runner import TurnRequest, load_base_prompt, run_turn
from app.obs.prices import cost_rub
from app.obs.usage import UsageEvent, record_usage, take_usage, usage_sink
from app.rag.embeddings import EmbeddingClient
from app.rag.rerank import RerankClient
from app.rag.search import Fragment
from tests.agent_helpers import (
    DIAG_SESSION,
    DIAG_VEHICLE,
    ScriptedChat,
    load_fixture_scenarios,
    make_services,
    manual_fragment,
    reply,
)

QWEN = "qwen3.8-flash-next-ru-noreason"


def _priced(content: str = "", calls: list[tuple[str, dict[str, Any]]] | None = None) -> LlmReply:
    """Ответ модели с тарифицируемым именем: reply() даёт 100 входных и 20 выходных токенов."""
    return reply(content=content, calls=calls).model_copy(update={"model": QWEN})


def _turn(message: str = "Что с машиной?") -> TurnRequest:
    return TurnRequest(
        vehicle_id=DIAG_VEHICLE,
        session_id=DIAG_SESSION,
        message=message,
        user_action=None,
        ui_mode="standard",
        lang="ru",
    )


def _run(services: Any, request: TurnRequest) -> None:
    run_turn(services, request, load_base_prompt(), lambda name, data: None)


def _run_id(services: Any) -> int:
    return next(iter(services.journal.runs))


def _search_with_usage(query: str, engine: str, top_k: int) -> list[Fragment]:
    """Поиск, который ведёт себя как настоящий: эмбеддинг запроса и реранк пишут расход в мешок."""
    record_usage("embed", "bge-m3", 42, 80)
    record_usage("rerank", "bge-reranker", None, 30)
    return [manual_fragment()]


class _EchoChat:
    """Модель, которая всегда отвечает без цифр; имя модели задаём сами."""

    def __init__(self, model: str) -> None:
        self._model = model

    def complete(self, messages: Any, tools: Any, on_token: Any, timeout_s: float) -> LlmReply:
        return reply(content="Ответ без цифр.").model_copy(update={"model": self._model})


def test_llm_step_and_run_carry_the_price() -> None:
    services = make_services(ScriptedChat([_priced("Вердикт: норма.")]))

    _run(services, _turn())

    expected = cost_rub(QWEN, 100, 20)
    llm_step = next(step for step in services.journal.steps if step.kind == "llm")
    assert llm_step.cost_rub == expected
    assert services.journal.runs[_run_id(services)].cost_rub == expected


def test_embedding_and_rerank_steps_are_journaled_and_only_embedding_is_priced() -> None:
    services = make_services(
        ScriptedChat(
            [
                _priced(
                    calls=[
                        (
                            "search_manual",
                            {"query": "давление масла", "vehicle_id": DIAG_VEHICLE, "top_k": 3},
                        )
                    ]
                ),
                _priced("Ответ."),
            ]
        )
    )
    services.deps.search = _search_with_usage

    _run(services, _turn())

    names = [step.kind for step in services.journal.steps]
    embed = next(step for step in services.journal.steps if step.kind == "embed")
    rerank = next(step for step in services.journal.steps if step.kind == "rerank")
    assert names.index("embed") < names.index("rerank")
    assert embed.name == "bge-m3" and embed.prompt_tokens == 42
    assert embed.cost_rub == cost_rub("bge-m3", 42, 0)
    assert rerank.cost_rub is None and rerank.prompt_tokens is None
    # ₽ хода: два вызова модели и эмбеддинг; реранк без токенов в сумму не входит, ₽ не «—».
    expected = cost_rub(QWEN, 100, 20) * 2 + cost_rub("bge-m3", 42, 0)
    assert services.journal.runs[_run_id(services)].cost_rub == expected


def test_unpriced_model_makes_the_price_unknown_not_zero() -> None:
    services = make_services(ScriptedChat([reply(content="Ответ без цены.")]))

    _run(services, _turn())

    llm_step = next(step for step in services.journal.steps if step.kind == "llm")
    assert llm_step.cost_rub is None
    assert services.journal.runs[_run_id(services)].cost_rub is None


def test_usage_outside_a_turn_is_dropped() -> None:
    record_usage("embed", "bge-m3", 5, 1)

    assert take_usage() == []


def test_usage_sink_collects_events_of_one_turn() -> None:
    with usage_sink() as events:
        record_usage("embed", "bge-m3", 5, 1)
        record_usage("rerank", "bge-reranker", None, 2)

    assert events == [
        UsageEvent(kind="embed", model="bge-m3", prompt_tokens=5, ms=1),
        UsageEvent(kind="rerank", model="bge-reranker", prompt_tokens=None, ms=2),
    ]


def test_embedding_client_reports_prompt_tokens_from_usage() -> None:
    client = EmbeddingClient("test-key", "https://api.example.invalid/v1", "bge-m3")
    response = SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=[0.0] * 1024)],
        usage=SimpleNamespace(prompt_tokens=7),
    )
    client._client = SimpleNamespace(  # type: ignore[assignment]
        embeddings=SimpleNamespace(create=lambda **_: response)
    )

    with usage_sink() as events:
        vectors = client.embed(["зазор клапанов"])

    assert len(vectors) == 1
    assert [(event.kind, event.model, event.prompt_tokens) for event in events] == [
        ("embed", "bge-m3", 7)
    ]


def test_rerank_client_reports_the_call_without_tokens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}]})

    client = RerankClient(
        "test-key",
        "https://api.example.invalid/v1",
        "bge-reranker",
        transport=httpx.MockTransport(handler),
    )

    with usage_sink() as events:
        pairs = client.rerank("давление масла", ["фрагмент"])

    assert pairs == [(0, 0.9)]
    assert [(event.kind, event.model, event.prompt_tokens) for event in events] == [
        ("rerank", "bge-reranker", None)
    ]


def test_eval_result_carries_agent_model_and_total_price() -> None:
    template = replace(make_services(ScriptedChat([])), llm=_EchoChat(QWEN))
    template.deps.search = lambda query, engine, top_k: [manual_fragment()]

    result = run_agent_result(
        template, load_fixture_scenarios()[:2], load_base_prompt(), model=QWEN, min_score=0.8
    )

    assert result.model == QWEN
    assert result.cost_rub is not None and result.cost_rub > Decimal(0)
    assert isinstance(result.summary()["cost_rub"], str)


def test_eval_result_without_price_has_no_total() -> None:
    template = replace(make_services(ScriptedChat([])), llm=_EchoChat("stub-model"))
    template.deps.search = lambda query, engine, top_k: [manual_fragment()]

    result = run_agent_result(
        template,
        load_fixture_scenarios()[:2],
        load_base_prompt(),
        model="stub-model",
        min_score=0.8,
    )

    assert result.cost_rub is None
