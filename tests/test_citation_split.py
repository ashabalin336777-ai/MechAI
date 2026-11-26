"""Разбиение ответа на фразы не режет по сокращениям, скобкам и «ёлочкам» (проверка цитат).

Логика check_citations не меняется: проверяем, что фраза с «стр. N» остаётся целой.
"""

from app.rag.citations import check_citations, split_sentences
from app.rag.search import Fragment


def _fragment(page: int, text: str) -> Fragment:
    return Fragment(
        manual_id="yamz236_rk",
        manual="236.01.01 РК",
        pdf_page=page,
        section=None,
        text=text,
        score=1.0,
    )


def test_reference_after_page_abbreviation_stays_in_one_phrase() -> None:
    answer = "Давление 400-700 кПа (см. стр. 267) [236.01.01 РК, стр. 267]."
    fragments = [_fragment(267, "Давление 400-700 кПа (4-7 кгс/см2) при номинальной частоте.")]
    assert split_sentences(answer) == [answer]
    assert check_citations(answer, fragments).ok


def test_quoted_formulation_with_page_does_not_become_a_fragment() -> None:
    answer = (
        "Формулировка 2 — «236.01.01 РК», стр. 276: «Проверку регулировки зазоров производить "
        "на холодном двигателе или не ранее, чем через 15 минут после его остановки.» "
        "[236.01.01 РК, стр. 276]."
    )
    fragments = [
        _fragment(
            276,
            "Проверку регулировки зазоров производить на холодном двигателе или не ранее, "
            "чем через 15 минут после его остановки.",
        )
    ]
    assert split_sentences(answer) == [answer]
    assert check_citations(answer, fragments).ok


def test_number_without_citation_still_fails() -> None:
    answer = "Давление 400-700 кПа без ссылки."
    result = check_citations(answer, [_fragment(267, "Давление 400-700 кПа.")])
    assert not result.ok
    assert any("700 кПа" in problem for problem in result.problems)


def test_real_sentence_boundaries_are_kept() -> None:
    answer = "Регулировать клапаны. См. стр. 31 для деталей. Далее порядок."
    assert split_sentences(answer) == [
        "Регулировать клапаны.",
        "См. стр. 31 для деталей.",
        "Далее порядок.",
    ]


def test_abbreviations_list_does_not_split_phrase() -> None:
    answer = "Проверить т.е. давление и т.д. зазоры, см. табл. 2, гл. 5, п. 11.5 [РК, стр. 31]."
    assert split_sentences(answer) == [answer]
