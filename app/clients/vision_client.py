"""Клиент vision-моделей Neuraldeep: список моделей и распознавание страницы по PNG.

Таймаут и без повторов: проба и OCR не должны молча дублировать платные запросы.
"""

import base64
import re
import time
from typing import Any

from openai import OpenAI, OpenAIError
from pydantic import BaseModel

VISION_TIMEOUT_S = 120.0
TRANSCRIBE_PROMPT = (
    "Дословно перепиши весь текст со страницы. Таблицы оформи в Markdown. Ничего не додумывай."
)
VISION_MODALITY_KEYS = ("modalities", "input_modalities", "input")
VISION_TYPES = ("image", "vision", "image_url")
VISION_ID_RE = re.compile(r"(?i)vision|(?:^|[-_/])vl(?:$|[-_\d])|llava|omni")


class VisionError(Exception):
    """Vision-модель или список моделей недоступны."""


class ModelInfo(BaseModel):
    id: str
    vision: bool | None


class VisionResult(BaseModel):
    text: str
    tokens_in: int | None
    tokens_out: int | None
    elapsed_ms: int


def detect_vision(item: dict[str, Any]) -> bool | None:
    """Есть ли у модели вход-изображение. None, если по данным каталога не понятно."""
    for key in VISION_MODALITY_KEYS:
        value = item.get(key)
        if isinstance(value, list) and value:
            return any(str(kind).lower() in VISION_TYPES for kind in value)
    if VISION_ID_RE.search(str(item.get("id", ""))):
        return True
    return None


class VisionClient:
    def __init__(self, api_key: str, base_url: str, *, timeout_s: float = VISION_TIMEOUT_S) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0)

    def list_models(self) -> list[ModelInfo]:
        try:
            page = self._client.models.list()
        except OpenAIError as exc:
            raise VisionError(f"список моделей недоступен: {type(exc).__name__}") from exc
        return [
            ModelInfo(id=item.id, vision=detect_vision(item.model_dump())) for item in page.data
        ]

    def describe_page(self, png: bytes, model: str) -> VisionResult:
        """Дословное распознавание страницы: текст, токены и время вызова."""
        data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": TRANSCRIBE_PROMPT},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
            )
        except OpenAIError as exc:
            raise VisionError(f"модель {model} недоступна: {type(exc).__name__}") from exc
        elapsed_ms = int((time.monotonic() - started) * 1000)
        usage = response.usage
        return VisionResult(
            text=response.choices[0].message.content or "",
            tokens_in=usage.prompt_tokens if usage else None,
            tokens_out=usage.completion_tokens if usage else None,
            elapsed_ms=elapsed_ms,
        )
