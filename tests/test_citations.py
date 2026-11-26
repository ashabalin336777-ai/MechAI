"""Проверка цитат: цифра без ссылки, ссылка на неполученную страницу, нормализация единиц."""

from app.rag.citations import check_citations, fix_citations, unsupported_claims
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


def test_citation_moves_to_the_page_of_this_turn_that_has_the_number() -> None:
    fragments = [
        _fragment("Давление 300 кПа при номинальной частоте.", page=19, manual="РЭ 1"),
        _fragment("Не менее 100 кПа при минимальной частоте.", page=267, manual="РК 2"),
    ]
    answer = "Минимальное давление 100 кПа [РЭ 1, стр. 19]."
    fixed = fix_citations(answer, fragments)
    assert fixed.text == "Минимальное давление 100 кПа [РК 2, стр. 267]."
    assert [(fix.old, fix.new, fix.claim) for fix in fixed.fixes] == [
        ("[РЭ 1, стр. 19]", "[РК 2, стр. 267]", "100 кПа")
    ]
    assert check_citations(fixed.text, fragments).ok


def test_number_found_nowhere_in_this_turn_is_not_moved() -> None:
    fragments = [_fragment("Зазор 0,25 мм.", page=19, manual="РЭ 1")]
    answer = "Зазор 0,77 мм [РЭ 1, стр. 19]."
    fixed = fix_citations(answer, fragments)
    assert fixed.text == answer
    assert fixed.fixes == []
    assert not check_citations(answer, fragments).ok


def test_sentence_with_two_citations_is_not_guessed() -> None:
    fragments = [
        _fragment("Не менее 100 кПа.", page=267, manual="РК 2"),
        _fragment("Другое.", page=19, manual="РЭ 1"),
    ]
    answer = "Давление 100 кПа [РЭ 1, стр. 19] и [РЭ 1, стр. 7]."
    fixed = fix_citations(answer, fragments)
    assert fixed.text == answer
    assert fixed.fixes == []


def test_fix_changes_only_its_sentence() -> None:
    fragments = [
        _fragment("Зазор 0,15 мм.", page=45, manual=DESIGNATION),
        _fragment("Не менее 100 кПа.", page=46, manual=DESIGNATION),
    ]
    answer = "Зазор 0,15 мм [536.01.02 РК, стр. 45].\nМинимум 100 кПа [536.01.02 РК, стр. 99]."
    fixed = fix_citations(answer, fragments)
    assert fixed.text == (
        "Зазор 0,15 мм [536.01.02 РК, стр. 45].\nМинимум 100 кПа [536.01.02 РК, стр. 46]."
    )
    assert len(fixed.fixes) == 1
