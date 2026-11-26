"""Проверка цитат: цифра без ссылки, ссылка на неполученную страницу, нормализация единиц."""

from app.rag.citations import check_citations, unsupported_claims
from app.rag.search import Fragment

DESIGNATION = "536.01.02 РК"


def test_unsupported_claims_lists_numbers_missing_from_fragments() -> None:
    fragment = _fragment("Затяжка 150 Н·м")
    assert unsupported_claims("Затяжка 150 Н·м и 2 мм", [fragment]) == ["2 мм"]


def _fragment(text: str, page: int = 45, manual: str = DESIGNATION) -> Fragment:
    return Fragment(
        manual_id="yamz536_rk", manual=manual, pdf_page=page, section=None, text=text, score=0.9
    )


def test_correct_citation_with_decimal_comma_passes() -> None:
    fragments = [_fragment("Зазор впускных клапанов 0,15 мм, выпускных 0,25 мм.")]
    answer = "Зазор впускных клапанов 0.15 мм [536.01.02 РК, стр. 45]."
    result = check_citations(answer, fragments)
    assert result.ok, result.problems


def test_torque_with_space_matches_middle_dot_unit() -> None:
    fragments = [_fragment("Момент затяжки гаек 250 Н·м в два приёма.")]
    answer = "Затяните гайки моментом 250 Н м [536.01.02 РК, стр. 45]."
    assert check_citations(answer, fragments).ok


def test_number_without_citation_is_caught() -> None:
    fragments = [_fragment("Зазор 0,15 мм.")]
    result = check_citations("Зазор клапанов 0,15 мм.", fragments)
    assert not result.ok
    assert any("без ссылки" in problem for problem in result.problems)


def test_citation_to_page_not_received_is_caught() -> None:
    fragments = [_fragment("Зазор 0,15 мм.", page=45)]
    result = check_citations("Зазор 0,15 мм [536.01.02 РК, стр. 99].", fragments)
    assert not result.ok
    assert any("стр. 99" in problem for problem in result.problems)


def test_number_missing_in_cited_fragment_is_caught() -> None:
    fragments = [_fragment("Зазор 0,25 мм.")]
    result = check_citations("Зазор 0,15 мм [536.01.02 РК, стр. 45].", fragments)
    assert not result.ok
    assert any("не найдена" in problem for problem in result.problems)


def test_number_from_other_page_does_not_count() -> None:
    fragments = [_fragment("Зазор 0,15 мм.", page=45), _fragment("Зазор 0,25 мм.", page=46)]
    result = check_citations("Зазор 0,25 мм [536.01.02 РК, стр. 45].", fragments)
    assert not result.ok


def test_citation_to_other_manual_is_caught() -> None:
    fragments = [_fragment("Зазор 0,15 мм.", manual=DESIGNATION)]
    result = check_citations("Зазор 0,15 мм [236.01.01 РК, стр. 45].", fragments)
    assert not result.ok


def test_numbers_without_units_are_not_claims() -> None:
    fragments = [_fragment("Таблица 3.")]
    assert check_citations("См. раздел 3, стр. 45 без единиц.", fragments).ok


def test_sentence_with_two_claims_checks_each_one() -> None:
    fragments = [_fragment("Зазор 0,15 мм, момент 250 Н·м.")]
    good = "Зазор 0,15 мм и момент 250 Н·м [536.01.02 РК, стр. 45]."
    bad = "Зазор 0,15 мм и момент 300 Н·м [536.01.02 РК, стр. 45]."
    assert check_citations(good, fragments).ok
    assert not check_citations(bad, fragments).ok


def test_each_sentence_needs_its_own_citation() -> None:
    fragments = [_fragment("Зазор 0,15 мм.")]
    answer = "Зазор 0,15 мм [536.01.02 РК, стр. 45]. Допуск 0,15 мм."
    result = check_citations(answer, fragments)
    assert not result.ok
    assert len(result.problems) == 1
