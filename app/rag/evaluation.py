"""Прогон набора вопросов по руководствам и отчёт eval/rag_report.md (ТЗ §8.3, фаза 03)."""

from datetime import datetime
from pathlib import Path

import psycopg
import yaml
from pydantic import BaseModel, Field

from app.config import Settings
from app.rag.embeddings import EmbeddingClient
from app.rag.rerank import RerankClient
from app.rag.search import Fragment, search

EVAL_TOP_K = 5
SNIPPET_CHARS = 150


class EvalQuestion(BaseModel):
    id: str = Field(pattern=r"^Q\d{2}$")
    question: str = Field(min_length=5)
    engine_model: str = Field(min_length=1)


class EvalQuestionFile(BaseModel):
    questions: list[EvalQuestion] = Field(min_length=1)


class EvalItem(BaseModel):
    question: EvalQuestion
    fragments: list[Fragment]


def load_questions(path: Path) -> list[EvalQuestion]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return EvalQuestionFile.model_validate(raw).questions


def run_eval(
    conn: psycopg.Connection,
    questions: list[EvalQuestion],
    embedder: EmbeddingClient,
    reranker: RerankClient,
    min_score: float,
) -> list[EvalItem]:
    items: list[EvalItem] = []
    for question in questions:
        fragments = search(
            conn,
            question.question,
            question.engine_model,
            embedder,
            reranker,
            top_k=EVAL_TOP_K,
            min_score=min_score,
        )
        items.append(EvalItem(question=question, fragments=fragments))
    return items


def run_eval_report(settings: Settings) -> str:
    """Полный прогон из настроек приложения. Возвращает отчёт в Markdown."""
    questions = load_questions(settings.eval_questions_path)
    embedder = EmbeddingClient(
        settings.neuraldeep_api_key, settings.neuraldeep_base_url, settings.embed_model
    )
    reranker = RerankClient(
        settings.neuraldeep_api_key, settings.neuraldeep_base_url, settings.rerank_model
    )
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        items = run_eval(conn, questions, embedder, reranker, settings.rag_min_score)
    return render_report(
        items,
        generated_at=datetime.now(),
        embed_model=settings.embed_model,
        rerank_model=settings.rerank_model,
        min_score=settings.rag_min_score,
    )


def render_report(
    items: list[EvalItem],
    *,
    generated_at: datetime,
    embed_model: str,
    rerank_model: str,
    min_score: float,
) -> str:
    lines = [
        "# Отчёт проверки поиска по руководствам (RAG)",
        "",
        f"Дата: {generated_at:%Y-%m-%d %H:%M}. Вопросов: {len(items)}. "
        f"Эмбеддинги: `{embed_model}`, реранк: `{rerank_model}`, порог RAG_MIN_SCORE: {min_score}.",
        "",
        "Проверка цитат: ответа агента в фазе 03 ещё нет, поэтому проверка цитат не применяется. "
        "Появится в фазе 04, когда агент будет формировать ответ.",
        "",
    ]
    for item in items:
        question = item.question
        lines += [
            f"## {question.id}. {question.question}",
            "",
            f"Двигатель: `{question.engine_model}`.",
            "",
        ]
        if not item.fragments:
            lines += [
                f"Фрагментов выше порога нет: в руководстве на {question.engine_model} "
                "этих данных нет. Рекомендуется дефектовка.",
                "",
            ]
            continue
        lines += [
            "| # | Руководство | Стр. PDF | Раздел | Оценка | Начало фрагмента |",
            "|---|---|---|---|---|---|",
        ]
        for rank, fragment in enumerate(item.fragments, start=1):
            lines.append(
                f"| {rank} | {_cell(fragment.manual)} | {fragment.pdf_page} "
                f"| {_cell(fragment.section or '—')} "
                f"| {fragment.score:.3f} | {_cell(_snippet(fragment.text))} |"
            )
        lines += ["", "Проверка цитат: не применяется (ответа ещё нет).", ""]
    return "\n".join(lines) + "\n"


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat[:SNIPPET_CHARS] + ("…" if len(flat) > SNIPPET_CHARS else "")


def _cell(value: str) -> str:
    return value.replace("|", "/")
