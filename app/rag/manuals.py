"""Файлы руководств: проверка sha256 и докачка недостающего PDF из публичной папки материалов.

Ссылка приходит из env (MANUALS_URL или MATERIALS_URL), в манифесте её нет. Имя файла в папке —
поле file из манифеста.
"""

import hashlib
import logging
from pathlib import Path

from app.materials import MaterialsError, download_public_file
from app.rag.manifest import ManualEntry

logger = logging.getLogger("app.rag.manuals")

_CHUNK = 1 << 20


class ManualFileError(Exception):
    """Файл руководства недоступен или не совпадает с sha256 из манифеста."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_manual_file(entry: ManualEntry, manuals_dir: Path, base_url: str = "") -> Path:
    """Путь к файлу руководства с проверенным sha256. Недостающий файл качается по base_url."""
    target = manuals_dir / entry.file
    downloaded = False
    if not target.exists() and base_url:
        logger.info("скачиваю %s из публичной папки материалов", entry.file)
        try:
            download_public_file(base_url, entry.file, target)
        except MaterialsError as exc:
            raise ManualFileError(str(exc)) from exc
        downloaded = True
    if not target.exists():
        raise ManualFileError(
            f"нет файла {entry.file} в {manuals_dir}: задайте MATERIALS_URL или MANUALS_URL"
        )
    if sha256_of(target) != entry.sha256:
        if downloaded:
            target.unlink()
        raise ManualFileError(f"sha256 файла {entry.file} не совпадает с манифестом")
    return target
