"""Манифест руководств: соответствие ТЗ §3.2, двигатели из заглушки ТС, sha256 локальных файлов."""

import json
from pathlib import Path

import pytest

from app.rag.manifest import Manifest, load_manifest
from app.rag.manuals import sha256_of
from tests.helpers import REPO_ROOT, VEHICLES_PATH

MANIFEST_PATH = REPO_ROOT / "data" / "manuals" / "manifest.yaml"
MANUALS_DIR = REPO_ROOT / "data" / "manuals"


def _manifest() -> Manifest:
    return load_manifest(MANIFEST_PATH)


def test_manifest_lists_six_manuals_with_total_pages_from_tz() -> None:
    manifest = _manifest()
    assert len(manifest.manuals) == 6
    assert len({entry.id for entry in manifest.manuals}) == 6
    assert sum(entry.pages for entry in manifest.manuals) == 1743


def test_every_vehicle_engine_has_a_manual() -> None:
    vehicles = json.loads(VEHICLES_PATH.read_text(encoding="utf-8"))["vehicles"]
    engines = {vehicle["engine_model"] for vehicle in vehicles}
    covered = {engine for entry in _manifest().manuals for engine in entry.engine_models}
    assert engines <= covered


def test_zmz_40904_and_40905_share_one_manual() -> None:
    matches = [entry for entry in _manifest().manuals if "ЗМЗ-40904.10" in entry.engine_models]
    assert len(matches) == 1
    assert set(matches[0].engine_models) == {"ЗМЗ-40904.10", "ЗМЗ-40905.10"}


def test_only_536_rk_is_downloaded_from_yandex() -> None:
    with_url = [entry.id for entry in _manifest().manuals if entry.yandex_url]
    assert with_url == ["yamz536_rk"]


@pytest.mark.parametrize("entry_id", [entry.id for entry in _manifest().manuals])
def test_local_file_matches_sha256_when_present(entry_id: str) -> None:
    entry = next(item for item in _manifest().manuals if item.id == entry_id)
    path: Path = MANUALS_DIR / entry.file
    if not path.exists():
        pytest.skip(f"{entry.file} нет локально: скачивается при ingest")
    assert sha256_of(path) == entry.sha256
