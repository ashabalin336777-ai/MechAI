"""Клиент эмбеддингов: батчи по 32, порядок, размерность, ошибки API. Без сети."""

from types import SimpleNamespace

import pytest
from openai import OpenAIError

from app.rag.embeddings import BATCH_SIZE, EMBED_DIM, EmbeddingClient, EmbeddingError


class FakeEmbeddings:
    def __init__(self, dim: int = EMBED_DIM, fail: bool = False, reverse: bool = False) -> None:
        self.dim = dim
        self.fail = fail
        self.reverse = reverse
        self.batches: list[int] = []

    def create(self, model: str, input: list[str]) -> SimpleNamespace:
        if self.fail:
            raise OpenAIError("сервис недоступен")
        self.batches.append(len(input))
        data = [
            SimpleNamespace(index=index, embedding=[float(index)] * self.dim)
            for index in range(len(input))
        ]
        if self.reverse:
            data.reverse()
        return SimpleNamespace(data=data)


def _client(fake: FakeEmbeddings) -> EmbeddingClient:
    client = EmbeddingClient("test-key", "https://example.invalid/v1", "bge-m3")
    client._client = SimpleNamespace(embeddings=fake)
    return client


def test_texts_are_sent_in_batches_of_32_and_order_is_kept() -> None:
    fake = FakeEmbeddings(reverse=True)
    vectors = _client(fake).embed([f"t{n}" for n in range(70)])
    assert fake.batches == [BATCH_SIZE, BATCH_SIZE, 6]
    assert len(vectors) == 70
    assert vectors[0][0] == 0.0 and vectors[31][0] == 31.0 and vectors[32][0] == 0.0


def test_wrong_dimension_is_an_error() -> None:
    with pytest.raises(EmbeddingError, match="размерность"):
        _client(FakeEmbeddings(dim=768)).embed(["текст"])


def test_api_error_becomes_embedding_error() -> None:
    with pytest.raises(EmbeddingError, match="недоступны"):
        _client(FakeEmbeddings(fail=True)).embed(["текст"])
