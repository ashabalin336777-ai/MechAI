"""Эталоны и судейка: набор валиден, эталонные цифры есть на страницах PDF, отчёт и метрики."""

import json
from datetime import datetime

import pymupdf
import pytest

from app.rag.evaluation import (
    EvalItem,
    EvalQuestion,
    Judgement,
    judge,
    load_questions,
    render_report,
)
from app.rag.manifest import load_manifest
from app.rag.search import Fragment
from tests.helpers import REPO_ROOT, VEHICLES_PATH

QUESTIONS_PATH = REPO_ROOT / "eval" / "questions.yaml"
MANUALS_DIR = REPO_ROOT / "data" / "manuals"


def _fragment(manual_id: str, page: int, text: str, score: float) -> Fragment:
    return Fragment(
        manual_id=manual_id,
        manual=manual_id,
        pdf_page=page,
        section=None,
        text=text,
        score=score,
    )


def _question(**overrides) -> EvalQuestion:
    data = {
        "id": "Q01",
        "question": "Какой момент затяжки крышек коренных подшипников?",
        "engine_model": "ЯМЗ-236М2",
        "expected_manual": "yamz236_rk",
        "expected_page": 286,
        "key_numbers": ["430", "470"],
    }
    data.update(overrides)
    return EvalQuestion(**data)


def test_question_file_has_ten_engine_questions_and_three_no_data() -> None:
    questions = load_questions(QUESTIONS_PATH)
    assert sum(1 for q in questions if not q.no_data) == 10
    assert sum(1 for q in questions if q.no_data) == 3
    assert len({q.id for q in questions}) == len(questions)


def test_question_file_points_to_known_manuals_and_engines() -> None:
    manifest = {entry.id: entry for entry in load_manifest(MANUALS_DIR / "manifest.yaml").manuals}
    vehicles = json.loads(VEHICLES_PATH.read_text(encoding="utf-8"))["vehicles"]
    known_engines = {vehicle["engine_model"] for vehicle in vehicles}
    for question in load_questions(QUESTIONS_PATH):
        assert question.engine_model in known_engines
        if question.no_data:
            continue
        entry = manifest[question.expected_manual]
        assert question.expected_page <= entry.pages
        assert question.engine_model in entry.engine_models


@pytest.mark.parametrize(
    "question", [q for q in load_questions(QUESTIONS_PATH) if not q.no_data], ids=lambda q: q.id
)
def test_expected_numbers_are_on_the_expected_pdf_page(question: EvalQuestion) -> None:
    manifest = {entry.id: entry for entry in load_manifest(MANUALS_DIR / "manifest.yaml").manuals}
    path = MANUALS_DIR / manifest[question.expected_manual].file
    if not path.exists():
        pytest.skip(f"{path.name} нет локально")
    with pymupdf.open(path) as document:
        page_text = " ".join(document[question.expected_page - 1].get_text("text").split())
    normalized = page_text.lower().replace(",", ".").replace(" ", "")
    for key in question.key_numbers:
        assert key.lower().replace(",", ".").replace(" ", "") in normalized, (question.id, key)


def test_no_data_question_cannot_have_expectation() -> None:
    with pytest.raises(ValueError):
        EvalQuestion(
            id="N01",
            question="Какой турбокомпрессор?",
            engine_model="ЗМЗ-5234.10",
            no_data=True,
            expected_manual="zmz5234_rk",
            expected_page=10,
        )


def test_page_question_needs_expectation() -> None:
    with pytest.raises(ValueError):
        EvalQuestion(id="Q11", question="Какой момент затяжки?", engine_model="ЯМЗ-236М2")


def test_judge_hit_and_number_on_expected_page() -> None:
    fragments = [
        _fragment("yamz236_rk", 40, "430 470", 0.9),
        _fragment("yamz236_rk", 286, "Вертикальные 430-470 (43-47)", 0.7),
    ]
    result = judge(_question(), fragments, min_score=0.35)
    assert result == Judgement(hit_at_5=True, number_found=True)


def test_judge_page_hit_without_number() -> None:
    fragments = [_fragment("yamz236_rk", 286, "Болты крепления", 0.7)]
    result = judge(_question(), fragments, min_score=0.35)
    assert result.hit_at_5 is True and result.number_found is False


def test_judge_miss_when_other_manual_or_page() -> None:
    fragments = [
        _fragment("yamz236_re", 286, "430-470", 0.9),
        _fragment("yamz236_rk", 285, "430-470", 0.8),
    ]
    result = judge(_question(), fragments, min_score=0.35)
    assert result == Judgement(hit_at_5=False, number_found=False)


def test_judge_no_data_passes_only_when_threshold_cuts_everything() -> None:
    no_data = EvalQuestion(
        id="N01",
        question="Какой турбокомпрессор у ЗМЗ-5234.10?",
        engine_model="ЗМЗ-5234.10",
        no_data=True,
    )
    assert judge(no_data, [_fragment("zmz5234_rk", 1, "x", 0.2)], min_score=0.35).no_data_ok is True
    assert (
        judge(no_data, [_fragment("zmz5234_rk", 1, "x", 0.5)], min_score=0.35).no_data_ok is False
    )


def test_report_shows_summary_raw_scores_and_expected_mark() -> None:
    items = [
        EvalItem(
            question=_question(),
            fragments=[_fragment("yamz236_rk", 286, "430-470", 0.812)],
            judgement=Judgement(hit_at_5=True, number_found=True),
        ),
        EvalItem(
            question=EvalQuestion(
                id="N01",
                question="Какой турбокомпрессор у ЗМЗ-5234.10?",
                engine_model="ЗМЗ-5234.10",
                no_data=True,
            ),
            fragments=[_fragment("zmz5234_rk", 9, "Наддув не предусмотрен", 0.1)],
            judgement=Judgement(no_data_ok=True),
        ),
    ]
    report = render_report(
        items,
        generated_at=datetime(2026, 11, 26, 22, 0),
        embed_model="bge-m3",
        rerank_model="bge-reranker",
        min_score=0.35,
    )
    assert "| hit@5 по странице (вопросы с эталоном) | 1/1 |" in report
    assert "| цифра найдена на эталонной странице | 1/1 |" in report
    assert "| «нет инструкции»: порог отсёк выдачу | 1/1 |" in report
    assert "| 1 | yamz236_rk | 286 | — | 0.812 | да | ✓ |" in report
    assert "| 1 | zmz5234_rk | 9 | — | 0.100 | нет |  |" in report


def test_missing_page_in_fragments_renders_no_fragments_line() -> None:
    items = [EvalItem(question=_question(), fragments=[], judgement=Judgement(hit_at_5=False))]
    report = render_report(
        items,
        generated_at=datetime(2026, 11, 26, 22, 0),
        embed_model="bge-m3",
        rerank_model="bge-reranker",
        min_score=0.35,
    )
    assert "Фрагментов нет." in report
    assert "| hit@5 по странице (вопросы с эталоном) | 0/1 |" in report
