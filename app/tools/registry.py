"""Реестр инструментов агента: схемы для модели и обработчики. Выбирает модель (ТЗ F5)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.tools import (
    create_ticket,
    draft_ticket,
    get_diagnosis,
    get_history,
    get_vehicle,
    search_manual,
)
from app.tools.runtime import Runtime


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[[Runtime, Any], dict[str, Any]]


def build_registry() -> dict[str, ToolSpec]:
    modules = [get_vehicle, get_diagnosis, search_manual, get_history, draft_ticket, create_ticket]
    return {
        module.NAME: ToolSpec(
            name=module.NAME,
            description=module.DESCRIPTION,
            args=module.Args,
            run=module.run,
        )
        for module in modules
    }


def openai_tools(registry: dict[str, ToolSpec]) -> list[dict[str, Any]]:
    """Описание инструментов в формате chat.completions (function calling)."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.args.model_json_schema(),
            },
        }
        for spec in registry.values()
    ]
