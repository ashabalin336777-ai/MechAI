"""Гибридный поиск по руководствам (ТЗ §3.4, раздел 6.4).

pgvector (top 30) ∪ полнотекст tsvector('russian') (top 30) → RRF → реранк → top_k.
Фильтр по двигателю зашит в SQL: `engine_models @> [engine_model]`. Модель его снять не может.
"""

from dataclasses import dataclass
from typing import Protocol

import psycopg
from pydantic import BaseModel

from app.rag.embeddings import vector_literal

TENANT_ID = "demo"
VECTOR_LIMIT = 30
FULLTEXT_LIMIT = 30
RRF_K = 60
# Реранк принимает до 105 600 символов на запрос; 20 чанков по ≤3600 символов влезают с запасом.
RERANK_POOL = 20


class Fragment(BaseModel):
    manual_id: str
    manual: str
    pdf_page: int
    section: str | None
    text: str
    score: float


@dataclass(frozen=True)
class Candidate:
    id: int
    manual_id: str
    manual: str
    pdf_page: int
    section: str | None
    text: str


class EmbeddingsPort(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class RerankPort(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]: ...


def search(
    conn: psycopg.Connection,
    query: str,
    engine_model: str,
    embedder: EmbeddingsPort,
    reranker: RerankPort,
    *,
    top_k: int,
    min_score: float,
    tenant_id: str = TENANT_ID,
) -> list[Fragment]:
    """Фрагменты руководства этого двигателя с оценкой реранка не ниже min_score."""
    vector = embedder.embed([query])[0]
    by_vector = _vector_candidates(conn, tenant_id, engine_model, vector)
    by_text = _fulltext_candidates(conn, tenant_id, engine_model, query)
    pool = reciprocal_rank_fusion([by_vector, by_text])[:RERANK_POOL]
    if not pool:
        return []
    fragments: list[Fragment] = []
    for index, score in reranker.rerank(query, [candidate.text for candidate in pool]):
        if score < min_score:
            break  # пары отсортированы по убыванию: дальше только хуже
        found = pool[index]
        fragments.append(
            Fragment(
                manual_id=found.manual_id,
                manual=found.manual,
                pdf_page=found.pdf_page,
                section=found.section,
                text=found.text,
                score=score,
            )
        )
        if len(fragments) == top_k:
            break
    return fragments


def reciprocal_rank_fusion(rankings: list[list[Candidate]]) -> list[Candidate]:
    """Слияние списков по сумме 1/(RRF_K + rank). Каждый чанк учитывается один раз."""
    scores: dict[int, float] = {}
    by_id: dict[int, Candidate] = {}
    for ranking in rankings:
        for rank, candidate in enumerate(ranking, start=1):
            scores[candidate.id] = scores.get(candidate.id, 0.0) + 1.0 / (RRF_K + rank)
            by_id.setdefault(candidate.id, candidate)
    return [by_id[chunk_id] for chunk_id in sorted(scores, key=lambda chunk_id: -scores[chunk_id])]


_SELECT = (
    "SELECT c.id, c.manual_id, m.designation, c.pdf_page, c.section, c.text "
    "FROM chunks c JOIN manuals m ON m.tenant_id = c.tenant_id AND m.id = c.manual_id "
)


def _vector_candidates(
    conn: psycopg.Connection, tenant_id: str, engine_model: str, vector: list[float]
) -> list[Candidate]:
    literal = vector_literal(vector)
    rows = conn.execute(
        _SELECT
        + "WHERE c.tenant_id = %s AND c.engine_models @> %s::text[] "
        + "ORDER BY c.embedding <=> %s::vector LIMIT %s",
        (tenant_id, [engine_model], literal, VECTOR_LIMIT),
    ).fetchall()
    return [_candidate(row) for row in rows]


def _fulltext_candidates(
    conn: psycopg.Connection, tenant_id: str, engine_model: str, query: str
) -> list[Candidate]:
    rows = conn.execute(
        _SELECT
        + "WHERE c.tenant_id = %s AND c.engine_models @> %s::text[] "
        + "AND c.tsv @@ plainto_tsquery('russian', %s) "
        + "ORDER BY ts_rank_cd(c.tsv, plainto_tsquery('russian', %s)) DESC LIMIT %s",
        (tenant_id, [engine_model], query, query, FULLTEXT_LIMIT),
    ).fetchall()
    return [_candidate(row) for row in rows]


def _candidate(row: tuple) -> Candidate:
    chunk_id, manual_id, designation, pdf_page, section, text = row
    return Candidate(
        id=chunk_id,
        manual_id=manual_id,
        manual=designation,
        pdf_page=pdf_page,
        section=section,
        text=text,
    )
