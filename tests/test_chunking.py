"""Чанки руководств: границы страницы, перекрытие, заголовки, «только рисунок»."""

from pathlib import Path

import pymupdf
import pytest

from app.rag.chunking import (
    HARD_CHARS,
    OVERLAP_CHARS,
    build_manual_text,
    is_heading,
    linearize_rows,
    split_lines,
    table_lines,
)


def test_short_page_is_one_chunk_with_given_section() -> None:
    chunks, heading = split_lines(["Короткая строка"], "3 СМАЗКА")
    assert chunks == [("3 СМАЗКА", "Короткая строка")]
    assert heading == "3 СМАЗКА"


def test_long_page_is_split_within_limits_and_covers_all_lines() -> None:
    lines = [f"строка {number:03d} " + "x" * 190 for number in range(60)]
    chunks, _ = split_lines(lines, None)
    assert len(chunks) > 1
    assert all(len(text) <= HARD_CHARS for _, text in chunks)
    covered = [line for _, text in chunks for line in text.split("\n")]
    assert set(covered) == set(lines)


def test_consecutive_chunks_overlap_by_about_overlap_chars() -> None:
    lines = [f"строка {number:03d} " + "x" * 190 for number in range(60)]
    chunks, _ = split_lines(lines, None)
    first_lines = chunks[0][1].split("\n")
    second_lines = chunks[1][1].split("\n")
    shared = [line for line in second_lines if line in first_lines]
    assert shared
    assert sum(len(line) + 1 for line in shared) <= OVERLAP_CHARS


def test_numbered_and_uppercase_headings_are_detected() -> None:
    assert is_heading("3.2 Система смазки")
    assert is_heading("ПОРЯДОК ЗАТЯЖКИ КРЫШЕК")
    assert not is_heading("Затяните гайки крепления крышки равномерно в два приёма.")


def test_section_follows_nearest_heading() -> None:
    lines = (
        ["1 ОБЩИЕ СВЕДЕНИЯ", "текст раздела один"]
        + ["y" * 300] * 15
        + ["2.1 Давление масла", "текст"]
    )
    chunks, heading = split_lines(lines, None)
    assert chunks[0][0] == "1 ОБЩИЕ СВЕДЕНИЯ"
    assert chunks[-1][0] == "2.1 Давление масла"
    assert heading == "2.1 Давление масла"


def test_pdf_chunks_never_cross_page_and_blank_pages_are_marked(tmp_path: Path) -> None:
    path = tmp_path / "sample.pdf"
    document = pymupdf.open()
    dense = "\n".join(f"Line {number} torque 25 Nm inspect the bearing cap" for number in range(40))
    for text in (dense, "x", "Second page with enough text to be indexed as a separate page. " * 3):
        page = document.new_page()
        if text != "x":
            page.insert_textbox(pymupdf.Rect(40, 40, 555, 800), text, fontsize=8)
    document.save(path)
    document.close()

    manual = build_manual_text(path)

    assert manual.pages_total == 3
    assert manual.image_only_pages == [2]
    assert {chunk.pdf_page for chunk in manual.chunks} == {1, 3}
    assert all(chunk.text for chunk in manual.chunks)


RE_236 = Path(__file__).resolve().parents[1] / "data" / "manuals" / "yamz-236_re_2010.pdf"
RK_236 = Path(__file__).resolve().parents[1] / "data" / "manuals" / "yamz-236_rk_2014.pdf"


def test_table_row_binds_value_to_engine_column_and_section_unit() -> None:
    rows = [
        ["Показатели", "ЯМЗ-236М2", "ЯМЗ-238М2"],
        ["", "Заправочные емкости, л", ""],
        ["Система смазки", "21", "29"],
    ]
    assert linearize_rows(rows) == [
        "Заправочные емкости, л",
        "Система смазки: ЯМЗ-236М2 21 л; ЯМЗ-238М2 29 л",
    ]


def test_real_page_gives_oil_capacity_with_its_unit() -> None:
    if not RE_236.exists():
        pytest.skip("руководство ЯМЗ-236М2 (РЭ) не найдено в data/manuals")
    with pymupdf.open(RE_236) as document:
        page = document[10]  # стр. 11 PDF: «Заправочные емкости, л»
        lines = table_lines(page, page.get_text("text"))
    assert any(line.startswith("Система смазки (без радиатора): ЯМЗ–236М2 21 л") for line in lines)


def test_rotated_table_with_reversed_text_is_not_linearized() -> None:
    if not RK_236.exists():
        pytest.skip("руководство ЯМЗ-236М2 (РК) не найдено в data/manuals")
    with pymupdf.open(RK_236) as document:
        page = document[11]  # стр. 12 PDF: таблица давления, PyMuPDF читает её задом наперёд
        assert table_lines(page, page.get_text("text")) == []
