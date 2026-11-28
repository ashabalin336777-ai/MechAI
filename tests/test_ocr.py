"""OCR страниц-рисунков: идемпотентность, source='ocr', повторы и запасная модель, цитаты, пропуски.

Без сети и БД: модель и хранилище подменены. Страница 280 рендерится из настоящего PDF.
"""

import tempfile
from pathlib import Path

import pytest

from app.clients.vision_client import VisionError, VisionResult
from app.rag.chunking import ChunkDraft, image_only_pages
from app.rag.citations import check_citations
from app.rag.manifest import Manifest, ManualEntry
from app.rag.manuals import sha256_of
from app.rag.ocr import (
    DONE_STATUSES,
    OcrError,
    OcrTask,
    clean_ocr_text,
    pending_pages,
    plan_tasks,
    process_task,
)
from app.rag.ocr_job import OcrRun
from app.rag.search import Fragment
from tests.helpers import make_scan_pdf, requires_real_materials

PAGE = 280
# Синтетический скан: 280 страниц, страница 280 — только рисунок. Настоящих PDF тесты не читают.
MANUALS_DIR = Path(tempfile.mkdtemp(prefix="mechai-ocr-test-"))
SCAN_FILE = "synthetic_scan.pdf"
_SCAN_PATH = make_scan_pdf(MANUALS_DIR / SCAN_FILE, pages=PAGE, scan_page=PAGE)
TABLE = (
    "Таблица 6.12 - ЯМЗ-236М2\n"
    "| Частота | Нагрузка, кВт | Время, мин |\n"
    "| 2000 | 147 (200) | 10 |\n"
)
MODELS = ("gemma-test", "qwen-test")


def _entry() -> ManualEntry:
    return ManualEntry(
        id="yamz236_rk",
        designation="236.01.01 РК",
        title="Синтетический скан для тестов OCR",
        year=2014,
        file=SCAN_FILE,
        sha256=sha256_of(_SCAN_PATH),
        pages=PAGE,
        engine_models=["ЯМЗ-236М2"],
    )


class FakeStore:
    def __init__(self, done: set[int] | None = None) -> None:
        self.rows: dict[tuple[str, int], list[ChunkDraft]] = {}
        self.status: dict[tuple[str, int], str] = {}
        self._done = set(done or ())

    def manual_exists(self, manual_id: str) -> bool:
        return manual_id == "yamz236_rk"

    def done_pages(self, manual_id: str) -> set[int]:
        done = {
            page
            for (manual, page), s in self.status.items()
            if manual == manual_id and s in DONE_STATUSES
        }
        return done | self._done

    def replace_page(self, entry, page, chunks, vectors, model, text_chars) -> None:  # noqa: ANN001
        self.rows[(entry.id, page)] = list(chunks)
        self.status[(entry.id, page)] = "stored"

    def mark_page(self, entry, page, status, error, model="", text_chars=0) -> None:  # noqa: ANN001
        self.status[(entry.id, page)] = status
        self.rows.pop((entry.id, page), None)


class FakeVision:
    """Ответы по моделям: строка — текст, исключение — сбой. Пустой список — сбой сети."""

    def __init__(self, script: dict[str, list]) -> None:
        self.script = script
        self.calls: list[str] = []

    def describe_page(self, png: bytes, model: str) -> VisionResult:
        assert png.startswith(b"\x89PNG")
        self.calls.append(model)
        queue = self.script.get(model, [])
        if not queue:
            raise VisionError(f"{model} недоступна")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return VisionResult(text=item, tokens_in=100, tokens_out=50, elapsed_ms=7)


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in texts]


def _task() -> OcrTask:
    return OcrTask(entry=_entry(), path=MANUALS_DIR / _entry().file, page=PAGE)


def _no_pause(_: float) -> None:
    return None


def test_clean_removes_only_trailing_page_number() -> None:
    assert clean_ocr_text(TABLE + "280\n", PAGE) == TABLE.strip()
    assert clean_ocr_text(TABLE + "**280**", PAGE) == TABLE.strip()
    # Число внутри текста и другое число в конце не трогаем.
    assert clean_ocr_text("Режим 280 мин\n" + TABLE, PAGE).startswith("Режим 280 мин")
    assert clean_ocr_text(TABLE + "281", PAGE).endswith("281")


def test_pending_pages_skip_done() -> None:
    assert pending_pages([10, 280, 300], {280}) == [10, 300]
    assert pending_pages([10], set()) == [10]


@requires_real_materials
def test_scan_page_is_image_only_in_real_pdf() -> None:
    real = Path(__file__).resolve().parent.parent / "data" / "manuals" / "yamz-236_rk_2014.pdf"
    assert PAGE in image_only_pages(real)


def test_scan_page_is_image_only_in_synthetic_pdf() -> None:
    assert PAGE in image_only_pages(MANUALS_DIR / SCAN_FILE)


def test_process_stores_ocr_chunks_with_source_and_page() -> None:
    store = FakeStore()
    vision = FakeVision({MODELS[0]: [TABLE + "280"]})
    outcome = process_task(_task(), vision, FakeEmbedder(), store, MODELS, _no_pause)

    assert outcome.status == "stored"
    assert outcome.model == MODELS[0]
    chunks = store.rows[("yamz236_rk", PAGE)]
    assert chunks
    assert all(chunk.source == "ocr" and chunk.pdf_page == PAGE for chunk in chunks)
    assert "147 (200)" in "\n".join(chunk.text for chunk in chunks)
    assert "280" not in chunks[-1].text.splitlines()[-1]


def test_second_run_creates_no_duplicates() -> None:
    store = FakeStore()
    vision = FakeVision({MODELS[0]: [TABLE, TABLE]})
    process_task(_task(), vision, FakeEmbedder(), store, MODELS, _no_pause)
    first = list(store.rows[("yamz236_rk", PAGE)])

    process_task(_task(), vision, FakeEmbedder(), store, MODELS, _no_pause)
    assert store.rows[("yamz236_rk", PAGE)] == first

    planned = plan_tasks(Manifest(manuals=[_entry()]), MANUALS_DIR, store)
    assert PAGE not in [task.page for task in planned]


def test_short_text_is_skipped_drawing_not_failed_and_not_retried() -> None:
    store = FakeStore()
    vision = FakeVision({MODELS[0]: ["280"]})
    outcome = process_task(_task(), vision, FakeEmbedder(), store, MODELS, _no_pause)

    assert outcome.status == "skipped_drawing"
    assert outcome.error == "распознано слишком мало текста"
    assert store.status[("yamz236_rk", PAGE)] == "skipped_drawing"
    assert ("yamz236_rk", PAGE) not in store.rows
    # Следующий запуск страницу не берёт в работу и модель не вызывает.
    assert PAGE not in [
        t.page for t in plan_tasks(Manifest(manuals=[_entry()]), MANUALS_DIR, store)
    ]


def test_failed_page_is_marked_failed_and_retried_next_run() -> None:
    store = FakeStore()
    vision = FakeVision({MODELS[0]: [], MODELS[1]: []})
    outcome = process_task(_task(), vision, FakeEmbedder(), store, MODELS, _no_pause)

    assert outcome.status == "failed"
    assert store.status[("yamz236_rk", PAGE)] == "failed"
    assert PAGE in [t.page for t in plan_tasks(Manifest(manuals=[_entry()]), MANUALS_DIR, store)]


def test_run_status_separates_skipped_and_failed() -> None:
    run = OcrRun(run_id=1)
    run.set_total(3)
    skipped = process_task(
        _task(), FakeVision({MODELS[0]: ["280"]}), FakeEmbedder(), FakeStore(), MODELS, _no_pause
    )
    failed = process_task(
        _task(),
        FakeVision({MODELS[0]: [], MODELS[1]: []}),
        FakeEmbedder(),
        FakeStore(),
        MODELS,
        _no_pause,
    )
    run.record(skipped)
    run.record(failed)
    status = run.snapshot()

    assert (status.done, status.stored) == (2, 0)
    assert [note.pdf_page for note in status.skipped] == [PAGE]
    assert [note.pdf_page for note in status.failed] == [PAGE]


def test_retries_then_fallback_model() -> None:
    store = FakeStore()
    pauses: list[float] = []
    vision = FakeVision(
        {
            MODELS[0]: [VisionError("таймаут"), VisionError("таймаут"), VisionError("таймаут")],
            MODELS[1]: [TABLE],
        }
    )
    outcome = process_task(_task(), vision, FakeEmbedder(), store, MODELS, pauses.append)

    assert outcome.status == "stored"
    assert outcome.model == MODELS[1]
    assert vision.calls == [MODELS[0]] * 3 + [MODELS[1]]
    assert pauses == [5.0, 15.0]


def test_empty_answer_from_all_models_is_failure() -> None:
    store = FakeStore()
    vision = FakeVision({MODELS[0]: ["", "", ""], MODELS[1]: ["  \n", " ", " "]})
    outcome = process_task(_task(), vision, FakeEmbedder(), store, MODELS, _no_pause)

    assert outcome.status == "failed"
    assert "пустой ответ" in outcome.error
    assert ("yamz236_rk", PAGE) not in store.rows


def _ocr_fragment(text: str, page: int = PAGE) -> Fragment:
    return Fragment(
        manual_id="yamz236_rk",
        manual="236.01.01 РК",
        pdf_page=page,
        section=None,
        text=text,
        score=0.9,
    )


def test_citation_check_accepts_ocr_fragment() -> None:
    fragment = _ocr_fragment("Режим 2000 мин-1: нагрузка 147 кВт (200 л.с.), время 10 мин.")
    answer = "На режиме 2000 мин-1 нагрузка 147 кВт [236.01.01 РК, стр. 280]."

    assert check_citations(answer, [fragment]).ok


def test_citation_check_rejects_ocr_number_cited_to_other_page() -> None:
    fragment = _ocr_fragment("Режим 2000 мин-1: нагрузка 147 кВт.")
    answer = "Нагрузка 147 кВт [236.01.01 РК, стр. 281]."

    result = check_citations(answer, [fragment])
    assert result.ok is False
    assert any("стр. 281" in problem for problem in result.problems)


def test_plan_requires_ingested_manual() -> None:
    class NoManualStore(FakeStore):
        def manual_exists(self, manual_id: str) -> bool:
            return False

    with pytest.raises(OcrError, match="сначала запустите ingest"):
        plan_tasks(Manifest(manuals=[_entry()]), MANUALS_DIR, NoManualStore())
