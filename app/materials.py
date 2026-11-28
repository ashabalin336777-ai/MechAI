"""Материалы задачи вне репозитория (требование организатора, п. 9.1).

Заглушки (vehicles.json, fault_types.json) и PDF руководств в git не лежат. Ссылка на публичную
папку задаётся только переменными окружения: MATERIALS_URL, а при необходимости MANUALS_URL и
MOCK_DATA_URL. Недостающий файл докачивается, уже скачанный и читаемый файл не качается повторно.

Модуль не зависит от pydantic и сторонних пакетов: образ заглушек копирует его (mock/Dockerfile),
чтобы mock_ml и mock_toir получили vehicles.json до запуска uvicorn.
"""

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("app.materials")

YANDEX_API_URL = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
REQUEST_TIMEOUT_S = 120.0
_CHUNK = 1 << 20


class MaterialsError(Exception):
    """Файл материалов не удалось получить: сеть, код ответа или неверная ссылка."""


@dataclass(frozen=True)
class MaterialsStatus:
    ok: bool
    problems: list[str] = field(default_factory=list)


def download_public_file(public_url: str, remote_name: str, target: Path) -> None:
    """Скачивает файл из публичной папки Яндекс Диска во временный файл и переименовывает его."""
    query = urllib.parse.urlencode({"public_key": public_url, "path": f"/{remote_name}"})
    temp = target.with_name(target.name + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(f"{YANDEX_API_URL}?{query}", timeout=REQUEST_TIMEOUT_S) as meta:
            href = json.loads(meta.read())["href"]
        with (
            urllib.request.urlopen(href, timeout=REQUEST_TIMEOUT_S) as response,
            temp.open("wb") as handle,
        ):
            while block := response.read(_CHUNK):
                handle.write(block)
    except urllib.error.HTTPError as exc:
        temp.unlink(missing_ok=True)
        raise MaterialsError(f"не удалось скачать {remote_name}: код ответа {exc.code}") from exc
    except (OSError, KeyError, ValueError) as exc:
        temp.unlink(missing_ok=True)
        raise MaterialsError(f"не удалось скачать {remote_name}: {type(exc).__name__}") from exc
    os.replace(temp, target)


def read_json_problem(path: Path, list_key: str | None) -> str | None:
    """None, если JSON читается и содержит список; иначе понятная причина.

    list_key — имя ключа со списком внутри объекта; None — файл сам является списком.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"файл {path.name} не читается как JSON"
    if list_key is None:
        return None if isinstance(data, list) else f"в {path.name} ожидается список"
    if isinstance(data, dict) and isinstance(data.get(list_key), list):
        return None
    return f"в {path.name} нет списка «{list_key}»"


def ensure_json_file(
    path: Path, base_url: str, remote_name: str, list_key: str | None
) -> str | None:
    """Проверяет JSON и при отсутствии или порче докачивает файл. Возвращает причину или None."""
    problem = read_json_problem(path, list_key) if path.exists() else f"нет файла {path.name}"
    if problem is None:
        return None
    if not base_url:
        return f"{problem}; ссылка MATERIALS_URL не задана"
    logger.info("материалы: %s, скачиваю из публичной папки", problem)
    try:
        download_public_file(base_url, remote_name, path)
    except MaterialsError as exc:
        return str(exc)
    problem = read_json_problem(path, list_key)
    if problem is not None:
        path.unlink(missing_ok=True)
        return problem
    logger.info("материалы: скачан %s", path)
    return None


def ensure_runtime_materials(
    vehicles_path: Path, fault_types_path: Path, base_url: str
) -> MaterialsStatus:
    """Для приложения: парк ТС и справочник F01–F14 нужны при каждом запросе.

    PDF руководств здесь не качаются: им нужны только ingest и OCR, а ingest скачивает их сам.
    """
    checks = (
        ensure_json_file(vehicles_path, base_url, vehicles_path.name, "vehicles"),
        ensure_json_file(fault_types_path, base_url, fault_types_path.name, None),
    )
    problems = [problem for problem in checks if problem is not None]
    for problem in problems:
        logger.error("материалы: %s", problem)
    return MaterialsStatus(ok=not problems, problems=problems)


def main(argv: list[str] | None = None) -> int:
    """Докачка одного JSON-файла перед запуском заглушки (образ mock_ml и mock_toir)."""
    parser = argparse.ArgumentParser(description="Докачка JSON-заглушки из публичной папки")
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--list-key", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    base_url = os.environ.get("MOCK_DATA_URL") or os.environ.get("MATERIALS_URL", "")
    problem = ensure_json_file(args.target, base_url, args.target.name, args.list_key)
    if problem is not None:
        logger.error("материалы: %s", problem)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
