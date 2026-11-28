"""Реранк через Neuraldeep: POST /v1/rerank (формат Cohere/Jina, модель RERANK_MODEL)."""

import time
from collections.abc import Sequence

import httpx

from app.obs.usage import record_usage

RERANK_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class RerankError(Exception):
    """Сервис реранка недоступен или вернул неожиданный ответ."""


class RerankClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/rerank"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._transport = transport

    def rerank(self, query: str, documents: Sequence[str]) -> list[tuple[int, float]]:
        """Пары (индекс документа, relevance_score), по убыванию score."""
        if not documents:
            return []
        body = {"model": self._model, "query": query, "documents": list(documents)}
        started = time.monotonic()
        try:
            with httpx.Client(timeout=RERANK_TIMEOUT, transport=self._transport) as client:
                response = client.post(self._url, json=body, headers=self._headers)
                response.raise_for_status()
                results = response.json()["results"]
                pairs = [(int(item["index"]), float(item["relevance_score"])) for item in results]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise RerankError(f"реранкер недоступен: {type(exc).__name__}") from exc
        # Число токенов сервис не возвращает, поэтому ₽ по реранку в журнале не считаем.
        record_usage("rerank", self._model, None, int((time.monotonic() - started) * 1000))
        return sorted(pairs, key=lambda pair: -pair[1])
