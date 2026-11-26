"""Эмбеддинги через Neuraldeep (openai SDK, модель EMBED_MODEL = bge-m3, размерность 1024)."""

from collections.abc import Sequence

from openai import OpenAI, OpenAIError

EMBED_DIM = 1024
BATCH_SIZE = 32
TIMEOUT_S = 60.0


def vector_literal(vector: Sequence[float]) -> str:
    """Текст вектора для приведения к типу vector: "[0.1,0.2,...]"."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


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
            try:
                response = self._client.embeddings.create(model=self._model, input=batch)
            except OpenAIError as exc:
                raise EmbeddingError(f"эмбеддинги недоступны: {type(exc).__name__}") from exc
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
