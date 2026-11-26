"""Файлы руководств: проверка sha256 и загрузка недостающего файла с публичного Яндекс Диска."""

import hashlib
import logging
import os
from pathlib import Path

import httpx

from app.rag.manifest import ManualEntry

logger = logging.getLogger("app.rag.manuals")

YANDEX_API_URL = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
DOWNLOAD_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)
_CHUNK = 1 << 20


class ManualFileError(Exception):
    """Файл руководства недоступен или не совпадает с sha256 из манифеста."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def download_from_yandex(public_url: str, file_name: str, target: Path) -> None:
    """Скачивает файл из публичной папки Яндекс Диска во временный файл и переименовывает его."""
    try:
        with httpx.Client(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            meta = client.get(
                YANDEX_API_URL, params={"public_key": public_url, "path": f"/{file_name}"}
            )
            meta.raise_for_status()
            href = meta.json()["href"]
            temp = target.with_suffix(".part")
            with client.stream("GET", href) as response:
                response.raise_for_status()
                with temp.open("wb") as handle:
                    for block in response.iter_bytes(_CHUNK):
                        handle.write(block)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise ManualFileError(
            f"не удалось скачать {file_name} с Яндекс Диска: {type(exc).__name__}"
        ) from exc
    os.replace(temp, target)


def ensure_manual_file(entry: ManualEntry, manuals_dir: Path) -> Path:
    """Путь к файлу руководства с проверенным sha256. Недостающий файл качается по URL."""
    target = manuals_dir / entry.file
    if not target.exists() and entry.yandex_url:
        logger.info("скачиваю %s с Яндекс Диска", entry.file)
        download_from_yandex(entry.yandex_url, entry.file, target)
    if not target.exists():
        raise ManualFileError(f"нет файла {entry.file} в {manuals_dir}")
    actual = sha256_of(target)
    if actual != entry.sha256:
        if entry.yandex_url:
            target.unlink()
        raise ManualFileError(f"sha256 файла {entry.file} не совпадает с манифестом")
    return target
