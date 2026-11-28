"""Прогон эталонов по руководствам и отчёт eval/rag_report.md (фаза 03).

Метрики:
- hit@5 по странице: среди топ-5 есть фрагмент нужного руководства на эталонной странице PDF;
- цифра найдена: во фрагменте этой страницы есть все ключевые цифры эталона;
- «нет инструкции»: ни один фрагмент не прошёл порог RAG_MIN_SCORE
  (иначе агенту пришлось бы цитировать чужую процедуру).
Сырые rerank score показываем всегда, чтобы подобрать порог по первому прогону.
"""

from datetime import datetime
from pathlib import Path

import psycopg
import yaml
from pydantic import BaseModel, Field, model_validator

from app.config import Settings
from app.db.eval_runs import EvalCase, EvalResult
from app.rag.embeddings import EmbeddingClient
from app.rag.rerank import RerankClient
from app.rag.search import Fragment, search

EVAL_TOP_K = 5
SNIPPET_CHARS = 150
NO_CUT = float("-inf")


class EvalQuestion(BaseModel):
    id: str = Field(pattern=r"^[QN]\d{2}$")
    question: str = Field(min_length=5)
    engine_model: str = Field(min_length=1)
    expected_manual: str | None = None
    expected_page: int | None = Field(default=None, ge=1)
    key_numbers: list[str] = Field(default_factory=list)
    no_data: bool = False

    @model_validator(mode="after")
    def _check_expectation(self) -> "EvalQuestion":
        if self.no_data:
            if self.expected_manual or self.expected_page or self.key_numbers:
                raise ValueError("у вопроса «нет инструкции» не должно быть эталонной страницы")
        elif not (self.expected_manual and self.expected_page):
            raise ValueError("у вопроса нужны expected_manual и expected_page")
        return self


class EvalQuestionFile(BaseModel):
    questions: list[EvalQuestion] = Field(min_length=1)


class Judgement(BaseModel):
    hit_at_5: bool | None = None
    number_found: bool | None = None
    no_data_ok: bool | None = None


class EvalItem(BaseModel):
    question: EvalQuestion
    fragments: list[Fragment]
    judgement: Judgement


def load_questions(path: Path) -> list[EvalQuestion]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return EvalQuestionFile.model_validate(raw).questions


def judge(question: EvalQuestion, fragments: list[Fragment], min_score: float) -> Judgement:
    if question.no_data:
        above = [fragment for fragment in fragments if fragment.score >= min_score]
        return Judgement(no_data_ok=not above)
    on_page = [
        fragment
        for fragment in fragments
        if fragment.manual_id == question.expected_manual
        and fragment.pdf_page == question.expected_page
    ]
    number_found = any(
        all(_has_number(fragment.text, key) for key in question.key_numbers) for fragment in on_page
    )
    return Judgement(hit_at_5=bool(on_page), number_found=bool(on_page) and number_found)


def run_eval(
    conn: psycopg.Connection,
    questions: list[EvalQuestion],
    embedder: EmbeddingClient,
    reranker: RerankClient,
    min_score: float,
) -> list[EvalItem]:
    items: list[EvalItem] = []
    for question in questions:
        # Без отсечки: нужны сырые оценки топ-5, порог применяем в судейке.
        fragments = search(
            conn,
            question.question,
            question.engine_model,
            embedder,
            reranker,
            top_k=EVAL_TOP_K,
            min_score=NO_CUT,
        )
        items.append(
            EvalItem(
                question=question,
                fragments=fragments,
                judgement=judge(question, fragments, min_score),
            )
        )
    return items


def run_eval_result(settings: Settings) -> EvalResult:
    """Полный прогон из настроек приложения: отчёт в Markdown и сводка для eval_runs.

    Критерий «пройдено»: для вопроса с эталоном — hit@5 по странице, для «нет инструкции» —
    порог отсёк выдачу.
    """
    questions = load_questions(settings.eval_questions_path)
    embedder = EmbeddingClient(
        settings.neuraldeep_api_key, settings.neuraldeep_base_url, settings.embed_model
    )
    reranker = RerankClient(
        settings.neuraldeep_api_key, settings.neuraldeep_base_url, settings.rerank_model
    )
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        items = run_eval(conn, questions, embedder, reranker, settings.rag_min_score)
    options = {
        "generated_at": datetime.now(),
        "embed_model": settings.embed_model,
        "rerank_model": settings.rerank_model,
        "min_score": settings.rag_min_score,
    }
    return EvalResult(
        report_md=render_report(items, details=False, **options),
        report_full_md=render_report(items, details=True, **options),
        passed=sum(1 for item in items if _item_passed(item)),
        total=len(items),
        cases=[_item_case(item) for item in items],
    )


def _item_passed(item: EvalItem) -> bool:
    if item.question.no_data:
        return bool(item.judgement.no_data_ok)
    return bool(item.judgement.hit_at_5)


def _item_case(item: EvalItem) -> EvalCase:
    if item.question.no_data:
        note = "порог отсёк выдачу" if item.judgement.no_data_ok else "выше порога есть фрагменты"
    else:
        note = f"hit@5: {'да' if item.judgement.hit_at_5 else 'нет'}, цифра: " + (
            "да" if item.judgement.number_found else "нет"
        )
    return EvalCase(id=item.question.id, passed=_item_passed(item), note=note)


def render_report(
    items: list[EvalItem],
    *,
    generated_at: datetime,
    embed_model: str,
    rerank_model: str,
    min_score: float,
    details: bool = False,
) -> str:
    """Отчёт по набору. details=False — только метрики (для eval/*.md и git, п. 9.1).

    details=True добавляет фрагменты руководств (раздел и начало текста): такой отчёт хранится
    только в БД и показывается в /admin/logs.
    """
    page_items = [item for item in items if not item.question.no_data]
    no_data_items = [item for item in items if item.question.no_data]
    hits = sum(1 for item in page_items if item.judgement.hit_at_5)
    numbers = sum(1 for item in page_items if item.judgement.number_found)
    no_data_ok = sum(1 for item in no_data_items if item.judgement.no_data_ok)
    lines = [
        "# Отчёт проверки поиска по руководствам (RAG)",
        "",
        f"Дата: {generated_at:%Y-%m-%d %H:%M}. Эмбеддинги: `{embed_model}`, "
        f"реранк: `{rerank_model}`, "
        f"порог RAG_MIN_SCORE: {min_score}.",
        "",
        "## Итог по набору",
        "",
        "| Показатель | Результат |",
        "|---|---|",
        f"| hit@5 по странице (вопросы с эталоном) | {hits}/{len(page_items)} |",
        f"| цифра найдена на эталонной странице | {numbers}/{len(page_items)} |",
        f"| «нет инструкции»: порог отсёк выдачу | {no_data_ok}/{len(no_data_items)} |",
        "",
        "Проверка цитат в фазе 03 не применяется: агент ещё не формирует ответы.",
        "",
    ]
    for item in items:
        lines += _render_item(item, min_score, details)
    return "\n".join(lines) + "\n"


def _render_item(item: EvalItem, min_score: float, details: bool) -> list[str]:
    question = item.question
    lines = [f"## {question.id}. {question.question}", "", f"Двигатель: `{question.engine_model}`."]
    if question.no_data:
        verdict = "да" if item.judgement.no_data_ok else "нет, выше порога есть фрагменты"
        lines += [f"Тип: нет инструкции. Порог отсёк выдачу: {verdict}.", ""]
    else:
        hit = "да" if item.judgement.hit_at_5 else "нет"
        number = "да" if item.judgement.number_found else "нет"
        lines += [
            f"Эталон: `{question.expected_manual}`, стр. {question.expected_page}, "
            f"цифры {', '.join(question.key_numbers) or '—'}.",
            f"hit@5: {hit}. Цифра найдена: {number}.",
            "",
        ]
    if not item.fragments:
        lines += ["Фрагментов нет.", ""]
        return lines
    if details:
        lines += [
            "| # | Руководство | Стр. PDF | Раздел | Rerank score | Выше порога | Эталон "
            "| Начало фрагмента |",
            "|---|---|---|---|---|---|---|---|",
        ]
    else:
        lines += [
            "| # | Руководство | Стр. PDF | Rerank score | Выше порога | Эталон |",
            "|---|---|---|---|---|---|",
        ]
    for rank, fragment in enumerate(item.fragments, start=1):
        expected = "✓" if _is_expected_page(question, fragment) else ""
        above = "да" if fragment.score >= min_score else "нет"
        head = f"| {rank} | {_cell(fragment.manual)} | {fragment.pdf_page} "
        if details:
            section = _cell(fragment.section or "—")
            snippet = _cell(_snippet(fragment.text))
            lines.append(
                f"{head}| {section} | {fragment.score:.3f} | {above} | {expected} | {snippet} |"
            )
        else:
            lines.append(f"{head}| {fragment.score:.3f} | {above} | {expected} |")
    lines.append("")
    return lines


def _is_expected_page(question: EvalQuestion, fragment: Fragment) -> bool:
    return (
        not question.no_data
        and fragment.manual_id == question.expected_manual
        and fragment.pdf_page == question.expected_page
    )


def _has_number(text: str, key: str) -> bool:
    return _normalize_number(key) in _normalize_number(text)


def _normalize_number(value: str) -> str:
    return value.lower().replace(",", ".").replace(" ", "")


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat[:SNIPPET_CHARS] + ("…" if len(flat) > SNIPPET_CHARS else "")


def _cell(value: str) -> str:
    return value.replace("|", "/")
