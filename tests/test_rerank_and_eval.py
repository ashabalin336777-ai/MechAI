"""Реранк-клиент против MockTransport: тело запроса, сортировка, ошибки. Без сети."""

import json

import httpx
import pytest

from app.rag.rerank import RerankClient, RerankError


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
