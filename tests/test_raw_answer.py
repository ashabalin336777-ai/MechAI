"""Сырой ответ модели в журнале (шаг raw_answer) и первые нарушения цитат в отчёте eval."""

from app.agent.evaluation import fixed_by_code, violation_excerpts
from app.agent.guards import RAW_ANSWER_LIMIT_BYTES, raw_answer_snapshot


def test_raw_answer_snapshot_keeps_short_text_whole() -> None:
    snapshot = raw_answer_snapshot("Давление 400-700 кПа [РК, стр. 267].")
    assert snapshot["text"] == "Давление 400-700 кПа [РК, стр. 267]."
    assert snapshot["truncated"] is False


def test_raw_answer_snapshot_cuts_to_8_kb_without_broken_characters() -> None:
    text = "я" * 10000  # 2 байта на символ: 20000 байт
    snapshot = raw_answer_snapshot(text)
    assert snapshot["truncated"] is True
    assert snapshot["bytes"] == 20000
    assert len(snapshot["text"].encode("utf-8")) <= RAW_ANSWER_LIMIT_BYTES
    assert snapshot["text"] == "я" * (RAW_ANSWER_LIMIT_BYTES // 2)


def test_violation_excerpt_is_the_model_line_with_the_checked_number() -> None:
    raw = "Вступление.\nДавление не менее 100 кПа (см. стр. 267) [РК, стр. 267].\nКонец."
    problems = ["цифра «100 кПа» без ссылки [обозначение, стр. N] в той же фразе"]
    [(problem, excerpt)] = violation_excerpts(raw, problems)
    assert problem == problems[0]
    assert excerpt == "Давление не менее 100 кПа (см. стр. 267) [РК, стр. 267]."


def test_long_line_is_cut_to_a_window_around_the_number() -> None:
    raw = "а" * 500 + " 100 кПа " + "б" * 500
    [(_, excerpt)] = violation_excerpts(raw, ["цифра «100 кПа» без ссылки"])
    assert "100 кПа" in excerpt
    assert excerpt.startswith("…") and excerpt.endswith("…")
    assert len(excerpt) <= 2 * 200 + len("100 кПа") + 2


def test_only_first_three_violations_are_listed() -> None:
    problems = [f"цифра «{n} кПа» без ссылки" for n in range(1, 6)]
    assert len(violation_excerpts("", problems)) == 3


def test_violation_without_raw_text_has_empty_excerpt() -> None:
    [(_, excerpt)] = violation_excerpts("", ["цифра «5 мм» без ссылки"])
    assert excerpt == ""


def test_model_error_counted_as_fixed_when_final_answer_has_no_such_problem() -> None:
    model = [
        "ссылка [X, стр. 46] не соответствует полученным фрагментам",
        "цифра «1 мм» без ссылки",
    ]
    assert fixed_by_code(model, []) == 2
    assert fixed_by_code(model, ["цифра «1 мм» без ссылки"]) == 1
    assert fixed_by_code([], []) == 0
