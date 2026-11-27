"""Рендер страницы руководства в PNG для распознавания растровых страниц (OCR)."""

from pathlib import Path

import pymupdf

OCR_DPI = 200


def page_count(path: Path) -> int:
    doc = pymupdf.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def render_page_png(path: Path, page_no: int, dpi: int = OCR_DPI) -> bytes:
    """PNG страницы с номером page_no (считая с 1) при заданном разрешении."""
    doc = pymupdf.open(path)
    try:
        return doc[page_no - 1].get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()
