"""Чанки руководств: границы страницы, перекрытие, заголовки, «только рисунок»."""

from pathlib import Path

import pymupdf
import pytest

from app.rag.chunking import (
    HARD_CHARS,
    OVERLAP_CHARS,
    build_manual_text,
    is_heading,
    is_prose,
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


def test_numeric_header_without_caption_is_not_linearized() -> None:
    rows = [["Номинальное напряжение, В", "24"], ["Номинальная мощность, кВт", "6,5"]]
    assert linearize_rows(rows) == []


def test_numeric_size_header_with_unit_in_label_is_kept() -> None:
    rows = [
        ["Размер «под ключ», S, мм", "10", "12"],
        ["Диаметр описанной окружности, мм", "10,5", "12,7"],
    ]
    assert linearize_rows(rows) == ["Диаметр описанной окружности, мм: 10 10,5; 12 12,7"]


def test_prose_row_is_not_linearized() -> None:
    rows = [
        ["Показатели", "ЯМЗ-236М2"],
        ["Допускается установка фильтра грубой очистки вместо полнопоточного.", ""],
    ]
    assert linearize_rows(rows) == []


def test_is_prose_keeps_short_labels_and_unit_values() -> None:
    assert not is_prose("Система смазки")
    assert not is_prose("Заправочные емкости, л")
    assert not is_prose("Частота вращения, мин-1 800")
    assert is_prose("Допускается установка фильтра грубой очистки вместо полнопоточного.")


def _real_page_lines(manual: str, page_number: int) -> list[str]:
    path = Path(__file__).resolve().parents[1] / "data" / "manuals" / manual
    if not path.exists():
        pytest.skip(f"руководство {manual} не найдено в data/manuals")
    with pymupdf.open(path) as document:
        page = document[page_number - 1]
        return table_lines(page, page.get_text("text"))


def test_regression_oil_system_capacity_stays_in_re_page_11() -> None:
    lines = _real_page_lines("yamz-236_re_2010.pdf", 11)
    assert any(line.startswith("Система смазки (без радиатора): ЯМЗ–236М2 21 л") for line in lines)


def test_regression_size_table_stays_in_rk_page_35() -> None:
    lines = _real_page_lines("yamz-236_rk_2014.pdf", 35)
    assert any(line.startswith("Диаметр описанной окружности, мм: 10 10,5") for line in lines)


@pytest.mark.parametrize("page_number", [279, 281, 282])  # стр. 280 — без текстового слоя
def test_regression_test_modes_stay_in_rk_pages_279_282(page_number: int) -> None:
    lines = _real_page_lines("yamz-236_rk_2014.pdf", page_number)
    assert any("Частота вращения, мин-1" in line for line in lines)


@pytest.mark.parametrize("page_number", [117, 160])
def test_bare_numbers_without_column_caption_are_not_output(page_number: int) -> None:
    lines = _real_page_lines("yamz-236_re_2010.pdf", page_number)
    assert not any(": 24 " in line or "181 182" in line for line in lines)


def test_prose_lines_of_re_page_7_are_not_output() -> None:
    lines = _real_page_lines("yamz-236_re_2010.pdf", 7)
    assert not any("Зубчатые передачи, подшипники качения" in line for line in lines)


def test_rotated_table_with_reversed_text_is_not_linearized() -> None:
    if not RK_236.exists():
        pytest.skip("руководство ЯМЗ-236М2 (РК) не найдено в data/manuals")
    with pymupdf.open(RK_236) as document:
        page = document[11]  # стр. 12 PDF: таблица давления, PyMuPDF читает её задом наперёд
        assert table_lines(page, page.get_text("text")) == []
