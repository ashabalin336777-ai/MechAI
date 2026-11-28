"""Эмбеддинги через Neuraldeep (openai SDK, модель EMBED_MODEL = bge-m3, размерность 1024)."""

import time
from collections.abc import Sequence
from typing import Any

from openai import OpenAI, OpenAIError

from app.obs.usage import record_usage

EMBED_DIM = 1024
BATCH_SIZE = 32
TIMEOUT_S = 60.0


def vector_literal(vector: Sequence[float]) -> str:
    """Текст вектора для приведения к типу vector: "[0.1,0.2,...]"."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def _prompt_tokens(response: Any) -> int | None:
    """Число входных токенов из usage ответа; None, если сервис его не вернул."""
    value = getattr(getattr(response, "usage", None), "prompt_tokens", None)
    return value if isinstance(value, int) else None


class EmbeddingError(Exception):
    """Сервис эмбеддингов недоступен или вернул данные не той размерности."""


class EmbeddingClient:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=TIMEOUT_S, max_retries=2)
        self._model = model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Эмбеддинги в том же порядке, что и тексты. Батчи по BATCH_SIZE."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start : start + BATCH_SIZE])
            started = time.monotonic()
            try:
                response = self._client.embeddings.create(model=self._model, input=batch)
            except OpenAIError as exc:
                raise EmbeddingError(f"эмбеддинги недоступны: {type(exc).__name__}") from exc
            record_usage(
                "embed",
                self._model,
                _prompt_tokens(response),
                int((time.monotonic() - started) * 1000),
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != len(batch):
                raise EmbeddingError("эмбеддинги вернулись не полностью")
            for item in ordered:
                if len(item.embedding) != EMBED_DIM:
                    raise EmbeddingError(
                        f"размерность эмбеддинга {len(item.embedding)}, ожидалось {EMBED_DIM}"
                    )
                vectors.append(list(item.embedding))
        return vectors
