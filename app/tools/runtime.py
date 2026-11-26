"""Общая среда инструментов агента: зависимости (сервисы, БД, поиск) и контекст одного хода.

Инструменты получают Runtime и аргументы (pydantic). Возвращают dict: при ошибке
`{"ok": false, ...}`,
чтобы модель видела понятный текст, а не исключение.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.verdict import Thresholds
from app.clients.ml_client import MlClient
from app.clients.toir_client import ToirClient
from app.data.vehicles import VehicleStore
from app.db.agent_store import AgentStore
from app.rag.conflicts import ConflictNotice, KnownConflict
from app.rag.manifest import Manifest
from app.rag.search import Fragment

SearchFn = Callable[[str, str, int], list[Fragment]]
# Страницы руководства: (модель двигателя, обозначение руководства, номера страниц PDF).
PageFetchFn = Callable[[str, str, list[int]], list[Fragment]]


def no_pages(engine_model: str, designation: str, pages: list[int]) -> list[Fragment]:
    return []


@dataclass
class ToolDeps:
    vehicles: VehicleStore
    manifest: Manifest
    thresholds: Thresholds
    ml: MlClient
    toir: ToirClient
    store: AgentStore
    search: SearchFn
    tenant_id: str = "demo"
    conflicts: list[KnownConflict] = field(default_factory=list)
    fetch_pages: PageFetchFn = no_pages


@dataclass
class TurnContext:
    """Состояние одного хода: что уже получено из инструментов и что показать интерфейсу."""

    vehicle_id: str
    session_id: str
    retrieved: list[Fragment] = field(default_factory=list)
    fetched_now: list[Fragment] = field(default_factory=list)
    diagnosis: dict[str, Any] | None = None
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    # Карточку вердикта показываем в первом ходе сессии и по кнопке «Получить результат».
    show_verdict: bool = True
    # Противоречия руководства, найденные в этом ходе: ответ обязан их показать (guards.py).
    conflicts: list[ConflictNotice] = field(default_factory=list)

    def remember(self, fragments: list[Fragment]) -> None:
        """Фрагменты диалога копим без дублей: по (руководство, страница, начало текста)."""
        known = {(f.manual, f.pdf_page, f.text[:80]) for f in self.retrieved}
        for fragment in fragments:
            self.fetched_now.append(fragment)
            key = (fragment.manual, fragment.pdf_page, fragment.text[:80])
            if key not in known:
                self.retrieved.append(fragment)
                known.add(key)


@dataclass
class Runtime:
    deps: ToolDeps
    turn: TurnContext

    def engine_manuals(self, engine_model: str) -> dict[str, int]:
        """Обозначение руководства -> число страниц PDF двигателя. Пусто, если руководства нет."""
        return {
            entry.designation: entry.pages
            for entry in self.deps.manifest.manuals
            if engine_model in entry.engine_models
        }


def content_hash(payload: dict[str, Any]) -> str:
    """Хэш состава заявки: одинаковый состав — одинаковый хэш, порядок ключей не важен."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
