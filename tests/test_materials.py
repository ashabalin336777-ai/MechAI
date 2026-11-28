"""Материалы задачи (п. 9.1): ссылка из env, архив, повторный старт без скачивания, /health.

Сеть не используется: загрузка подменяется функцией, которая отдаёт синтетические файлы из fixture.
"""

import hashlib
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import materials
from app.config import Settings
from app.main import create_app
from app.materials import MaterialsError, ensure_json_file, ensure_runtime_materials, main
from app.rag import manuals
from app.rag.manifest import ManualEntry
from app.rag.manuals import ManualFileError, ensure_manual_file
from tests.helpers import FAULT_TYPES_PATH, VEHICLES_PATH

URL = "https://example.invalid/папка"
ARCHIVE = "synthetic_pack.zip"


class FakeDownload:
    """Подмена download_public_file: отдаёт source для всех имён; error — для всех имён."""

    def __init__(self, source: Path | None = None, error: str | None = None) -> None:
        self.source = source
        self.error = error
        self.calls: list[str] = []

    def __call__(self, public_url: str, remote_name: str, target: Path) -> None:
        self.calls.append(remote_name)
        if self.error is not None:
            raise MaterialsError(self.error)
        assert self.source is not None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.source.read_bytes())


class FolderWithArchiveOnly:
    """Папка как у заказчика: отдельных JSON нет (404), есть только архив."""

    def __init__(self, archive: Path) -> None:
        self.archive = archive
        self.calls: list[str] = []

    def __call__(self, public_url: str, remote_name: str, target: Path) -> None:
        self.calls.append(remote_name)
        if remote_name != ARCHIVE:
            raise MaterialsError(f"не удалось скачать {remote_name}: код ответа 404")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.archive.read_bytes())


def _make_archive(path: Path, members: dict[str, Path]) -> Path:
    """Синтетический архив: внутри папка-обёртка, как в настоящем архиве заказчика."""
    with zipfile.ZipFile(path, "w") as bundle:
        for name, source in members.items():
            bundle.write(source, arcname=name)
    return path


@pytest.fixture
def pack_archive(tmp_path: Path) -> Path:
    return _make_archive(
        tmp_path / ARCHIVE,
        {
            "synthetic_pack/data/vehicles.json": VEHICLES_PATH,
            "synthetic_pack/data/fault_types.json": FAULT_TYPES_PATH,
        },
    )


def test_existing_valid_json_is_not_downloaded_again(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "vehicles.json"
    target.write_bytes(VEHICLES_PATH.read_bytes())
    fake = FakeDownload(error="не должно вызываться")
    monkeypatch.setattr(materials, "download_public_file", fake)
    assert ensure_json_file(target, URL, "vehicles.json", "vehicles") is None
    assert fake.calls == []


def test_missing_file_without_link_gives_clear_message(tmp_path: Path) -> None:
    problem = ensure_json_file(tmp_path / "vehicles.json", "", "vehicles.json", "vehicles")
    assert problem is not None
    assert "MATERIALS_URL" in problem


def test_json_is_taken_from_archive_when_not_in_folder(
    tmp_path: Path, monkeypatch, pack_archive: Path
) -> None:
    target = tmp_path / "data" / "vehicles.json"
    folder = FolderWithArchiveOnly(pack_archive)
    monkeypatch.setattr(materials, "download_public_file", folder)

    problem = ensure_json_file(target, URL, "vehicles.json", "vehicles", ARCHIVE)

    assert problem is None
    assert target.read_bytes() == VEHICLES_PATH.read_bytes()
    assert folder.calls == ["vehicles.json", ARCHIVE]


def test_archive_is_cached_and_not_downloaded_again(
    tmp_path: Path, monkeypatch, pack_archive: Path
) -> None:
    target = tmp_path / "data" / "vehicles.json"
    folder = FolderWithArchiveOnly(pack_archive)
    monkeypatch.setattr(materials, "download_public_file", folder)
    ensure_json_file(target, URL, "vehicles.json", "vehicles", ARCHIVE)

    target.unlink()  # следующий старт: JSON нет, архив уже в кэше
    assert ensure_json_file(target, URL, "vehicles.json", "vehicles", ARCHIVE) is None

    assert folder.calls.count(ARCHIVE) == 1
    assert target.exists()


def test_fault_types_are_taken_from_the_same_archive(
    tmp_path: Path, monkeypatch, pack_archive: Path
) -> None:
    target = tmp_path / "data" / "fault_types.json"
    monkeypatch.setattr(materials, "download_public_file", FolderWithArchiveOnly(pack_archive))
    assert ensure_json_file(target, URL, "fault_types.json", None, ARCHIVE) is None
    assert target.read_bytes() == FAULT_TYPES_PATH.read_bytes()


def test_archive_without_the_file_gives_problem_not_crash(tmp_path: Path, monkeypatch) -> None:
    empty = _make_archive(tmp_path / ARCHIVE, {"synthetic_pack/readme.txt": VEHICLES_PATH})
    monkeypatch.setattr(materials, "download_public_file", FolderWithArchiveOnly(empty))
    problem = ensure_json_file(
        tmp_path / "vehicles.json", URL, "vehicles.json", "vehicles", ARCHIVE
    )
    assert problem is not None
    assert "vehicles.json" in problem


def test_broken_archive_is_removed_from_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(materials, "download_public_file", FakeDownload(error="404"))
    cache = tmp_path / "data" / ".cache"
    cache.mkdir(parents=True)
    (cache / ARCHIVE).write_bytes("не zip".encode())
    problem = ensure_json_file(
        tmp_path / "data" / "vehicles.json", URL, "vehicles.json", "vehicles", ARCHIVE
    )
    assert problem is not None
    assert not (cache / ARCHIVE).exists()


def test_missing_file_is_downloaded_once_and_then_read(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "data" / "vehicles.json"
    fake = FakeDownload(source=VEHICLES_PATH)
    monkeypatch.setattr(materials, "download_public_file", fake)

    assert ensure_json_file(target, URL, "vehicles.json", "vehicles") is None
    assert fake.calls == ["vehicles.json"]

    # Повторный старт: файл уже читается, скачивания нет.
    assert ensure_json_file(target, URL, "vehicles.json", "vehicles") is None
    assert fake.calls == ["vehicles.json"]


def test_broken_json_is_replaced_by_download(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "vehicles.json"
    target.write_text("{не json", encoding="utf-8")
    fake = FakeDownload(source=VEHICLES_PATH)
    monkeypatch.setattr(materials, "download_public_file", fake)
    assert ensure_json_file(target, URL, "vehicles.json", "vehicles") is None
    assert fake.calls == ["vehicles.json"]


def test_download_failure_is_returned_not_raised(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        materials,
        "download_public_file",
        FakeDownload(error="не удалось скачать vehicles.json: код ответа 404"),
    )
    problem = ensure_json_file(tmp_path / "vehicles.json", URL, "vehicles.json", "vehicles")
    assert problem is not None
    assert "404" in problem


def test_runtime_materials_report_missing_without_crash(tmp_path: Path) -> None:
    status = ensure_runtime_materials(tmp_path / "v.json", tmp_path / "f.json", "")
    assert status.ok is False
    assert len(status.problems) == 2


def test_mock_cli_returns_error_code_without_link(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MATERIALS_URL", "")
    monkeypatch.setenv("MOCK_DATA_URL", "")
    assert main(["--target", str(tmp_path / "vehicles.json"), "--list-key", "vehicles"]) == 1


def test_mock_cli_accepts_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "vehicles.json"
    target.write_bytes(VEHICLES_PATH.read_bytes())
    assert main(["--target", str(target), "--list-key", "vehicles"]) == 0


def test_manual_is_downloaded_by_remote_name_and_saved_under_file(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4 synthetic")
    entry = ManualEntry(
        id="test_manual",
        designation="ТЕСТ РК",
        title="Синтетическое руководство",
        year=2020,
        file="test_manual.pdf",
        remote_name="Тестовое руководство (папка).pdf",
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        pages=1,
        engine_models=["ЯМЗ-236М2"],
    )
    fake = FakeDownload(source=source)
    monkeypatch.setattr(manuals, "download_public_file", fake)

    path = ensure_manual_file(entry, tmp_path / "manuals", URL)

    assert path.name == "test_manual.pdf"
    assert fake.calls == ["Тестовое руководство (папка).pdf"]


def test_manual_is_downloaded_only_when_missing_and_checked_by_sha256(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4 synthetic")
    entry = ManualEntry(
        id="test_manual",
        designation="ТЕСТ РК",
        title="Синтетическое руководство",
        year=2020,
        file="test_manual.pdf",
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        pages=1,
        engine_models=["ЯМЗ-236М2"],
    )
    manuals_dir = tmp_path / "manuals"
    fake = FakeDownload(source=source)
    monkeypatch.setattr(manuals, "download_public_file", fake)

    path = ensure_manual_file(entry, manuals_dir, URL)
    assert path.exists()
    assert fake.calls == ["test_manual.pdf"]
    ensure_manual_file(entry, manuals_dir, URL)
    assert fake.calls == ["test_manual.pdf"]


def test_manual_without_file_and_without_link_is_clear_error(tmp_path: Path) -> None:
    entry = ManualEntry(
        id="test_manual",
        designation="ТЕСТ РК",
        title="Синтетическое руководство",
        year=2020,
        file="test_manual.pdf",
        sha256="0" * 64,
        pages=1,
        engine_models=["ЯМЗ-236М2"],
    )
    with pytest.raises(ManualFileError, match="MATERIALS_URL"):
        ensure_manual_file(entry, tmp_path, "")


def test_health_reports_materials_missing_and_degraded(tmp_path: Path) -> None:
    from mock_ml.app import app as ml_stub
    from mock_toir.app import app as toir_stub

    from app.clients.ml_client import MlClient
    from app.clients.toir_client import ToirClient
    from tests.helpers import STUB_BASE

    app = create_app(
        Settings(vehicles_path=tmp_path / "нет.json", fault_types_path=FAULT_TYPES_PATH)
    )
    app.state.ml_client = MlClient(STUB_BASE, http=TestClient(ml_stub))
    app.state.toir_client = ToirClient(STUB_BASE, http=TestClient(toir_stub))
    body = TestClient(app).get("/health").json()
    assert body["services"]["materials"] == "missing"
    assert body["status"] == "degraded"
    assert TestClient(app).get("/").status_code == 200  # приложение живо, без 500
