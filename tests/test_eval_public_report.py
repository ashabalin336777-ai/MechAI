"""Отчёты прогонов: публичная версия только с метриками (п. 9.1), полная — для БД и /admin/logs.

В eval/*.md попадают метрики, ID, статусы, страницы и стоимость. Фрагменты руководств и ответы
агента в публичный отчёт не выводятся, даже если их попросили.
"""

from datetime import datetime

from app.agent.evaluation import ScenarioRun
from app.agent.evaluation import render_report as render_agent_report
from app.agent.scenarios import Check, CheckResult, Scenario, TurnOutcome
from app.rag.evaluation import EvalItem, EvalQuestion, Judgement
from app.rag.evaluation import render_report as render_rag
from app.rag.search import Fragment

SECRET_FRAGMENT = "Секретный текст руководства 430 Н·м"
SECRET_SECTION = "Раздел руководства 2.8.18"
SECRET_ANSWER = "Ответ агента с цифрой 150 кПа"
NOW = datetime(2026, 11, 28, 9, 0)


def _rag_items() -> list[EvalItem]:
    question = EvalQuestion(
        id="Q01",
        question="Какой момент затяжки болтов крышек?",
        engine_model="ЯМЗ-236М2",
        expected_manual="236.01.01 РК",
        expected_page=41,
        key_numbers=["430"],
    )
    fragment = Fragment(
        manual_id="yamz236_rk",
        manual="236.01.01 РК",
        pdf_page=41,
        section=SECRET_SECTION,
        text=SECRET_FRAGMENT,
        score=0.955,
    )
    return [
        EvalItem(
            question=question,
            fragments=[fragment],
            judgement=Judgement(hit_at_5=True, number_found=True),
        )
    ]


def test_rag_public_report_has_metrics_and_no_manual_text() -> None:
    report = render_rag(
        _rag_items(),
        generated_at=NOW,
        embed_model="bge-m3",
        rerank_model="bge-reranker",
        min_score=0.8,
    )
    assert "Q01" in report
    assert "0.955" in report
    assert "41" in report
    assert SECRET_FRAGMENT not in report
    assert SECRET_SECTION not in report
    assert "Начало фрагмента" not in report


def test_rag_full_report_keeps_fragments_for_the_journal() -> None:
    report = render_rag(
        _rag_items(),
        generated_at=NOW,
        embed_model="bge-m3",
        rerank_model="bge-reranker",
        min_score=0.8,
        details=True,
    )
    assert SECRET_FRAGMENT[:40] in report
    assert "Начало фрагмента" in report


def _agent_runs() -> list[ScenarioRun]:
    scenario = Scenario(
        id="N01_ZMZ5234_NO_DATA",
        title="Нет данных",
        vehicle_id="O819CY198",
        session_id="S-0099",
        message="Какой момент затяжки?",
        checks=[Check(name="без чеков", no_draft=True)],
    )
    outcome = TurnOutcome(
        light="yellow",
        urgency=None,
        tools=["search_manual"],
        journal=["search_manual", "no_data_format"],
        answer=SECRET_ANSWER,
        citation_ok=True,
        general_cut=2,
        consult_removed=1,
    )
    return [
        ScenarioRun(
            scenario=scenario,
            outcome=outcome,
            checks=[CheckResult(name="без чеков", ok=True, detail="ок")],
        )
    ]


def test_agent_public_report_has_metrics_and_no_answer_text() -> None:
    report = render_agent_report(_agent_runs(), generated_at=NOW, model="qwen", min_score=0.8)
    assert "Общих сведений вырезано кодом: 2" in report
    assert "Фраз про специалиста вырезано кодом: 1" in report
    assert "N01_ZMZ5234_NO_DATA" in report
    assert SECRET_ANSWER not in report
    assert "Ответ агента" not in report


def test_agent_full_report_keeps_answer_for_the_journal() -> None:
    report = render_agent_report(
        _agent_runs(), generated_at=NOW, model="qwen", min_score=0.8, details=True
    )
    assert SECRET_ANSWER in report
