"""Реранк-клиент (MockTransport), набор вопросов и отчёт eval — без сети."""

import json
from datetime import datetime

import httpx
import pytest

from app.rag.evaluation import EvalItem, EvalQuestion, load_questions, render_report
from app.rag.rerank import RerankClient, RerankError
from app.rag.search import Fragment
from tests.helpers import REPO_ROOT, VEHICLES_PATH


def _client(handler) -> RerankClient:
    return RerankClient(
        "test-key",
        "https://api.example.invalid/v1",
        "bge-reranker",
        transport=httpx.MockTransport(handler),
    )


def test_rerank_sends_query_and_returns_sorted_pairs() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.2},
                    {"index": 0, "relevance_score": 0.9},
                ]
            },
        )

    pairs = _client(handler).rerank("момент затяжки", ["первый", "второй"])
    assert pairs == [(0, 0.9), (1, 0.2)]
    assert seen["url"] == "https://api.example.invalid/v1/rerank"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"] == {
        "model": "bge-reranker",
        "query": "момент затяжки",
        "documents": ["первый", "второй"],
    }


def test_http_error_becomes_rerank_error() -> None:
    client = _client(lambda request: httpx.Response(500, json={"error": "boom"}))
    with pytest.raises(RerankError, match="недоступен"):
        client.rerank("q", ["d"])


def test_malformed_response_becomes_rerank_error() -> None:
    client = _client(lambda request: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(RerankError):
        client.rerank("q", ["d"])


def test_empty_documents_do_not_call_the_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("запрос не должен уйти без документов")

    assert _client(handler).rerank("q", []) == []


def test_question_file_is_valid_and_engines_are_known() -> None:
    questions = load_questions(REPO_ROOT / "eval" / "questions.yaml")
    assert len(questions) == 10
    assert len({question.id for question in questions}) == 10
    vehicles = json.loads(VEHICLES_PATH.read_text(encoding="utf-8"))["vehicles"]
    known = {vehicle["engine_model"] for vehicle in vehicles}
    assert {question.engine_model for question in questions} <= known


def test_report_lists_top_fragments_and_no_data_branch() -> None:
    fragment = Fragment(
        manual_id="yamz536_rk",
        manual="536.01.02 РК",
        pdf_page=45,
        section="Клапаны",
        text="Зазор 0,15 мм | проверка",
        score=0.812,
    )
    items = [
        EvalItem(
            question=EvalQuestion(
                id="Q01", question="Какой зазор клапанов?", engine_model="ЯМЗ-536"
            ),
            fragments=[fragment],
        ),
        EvalItem(
            question=EvalQuestion(
                id="Q02", question="Какое давление масла?", engine_model="ЯМЗ-536"
            ),
            fragments=[],
        ),
    ]
    report = render_report(
        items,
        generated_at=datetime(2026, 11, 26, 21, 0),
        embed_model="bge-m3",
        rerank_model="bge-reranker",
        min_score=0.35,
    )
    assert "| 1 | 536.01.02 РК | 45 | Клапаны | 0.812 |" in report
    assert "Зазор 0,15 мм / проверка" in report
    assert "этих данных нет" in report
    assert "Проверка цитат: не применяется" in report
