"""Парк ТС и история проверок из vehicles.json (VEHICLES_PATH). Заглушка списка не отдаёт, читаем файл сами."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, model_validator


class SessionRecord(BaseModel):
    """Проверка машины. Совпадает с ответом /diagnose плюс время проверки."""

    session_id: str
    checked_at: datetime
    vehicle_id: str
    status: Literal["normal", "anomaly", "check_failed"]
    anomaly_type: str | None
    anomaly_title: str | None
    anomaly_score: float | None
    confidence: float | None
    signal_quality: Literal["good", "warning", "bad"]
    description: str
    model_version: str


class Vehicle(BaseModel):
    vehicle_id: str
    garage_no: str
    make: str
    model: str
    vehicle_type: str
    engine_model: str
    fuel: str
    sessions: list[SessionRecord]

    @model_validator(mode="before")
    @classmethod
    def model_from_make_when_null(cls, data: Any) -> Any:
        """У МАЗ с ЯМЗ-536 модель равна null: показываем марку («МАЗ»)."""
        if isinstance(data, dict) and data.get("model") is None:
            return {**data, "model": data.get("make", "")}
        return data

    @property
    def last_session(self) -> SessionRecord | None:
        return self.sessions[-1] if self.sessions else None


SEPARATORS_RE = re.compile(r"[\s\-–—]+")


def display_name(make: str, model: str | None) -> str:
    """Название ТС для экрана: марка и модель, без повтора марки.

    Модели нет, она совпадает с маркой или начинается с марки как слово («МАЗ-5337», «УАЗ Патриот»)
    — показываем один вариант. «МАЗДА» при марке «МАЗ» — отдельное слово, поэтому «МАЗ МАЗДА».
    Сравнение без учёта регистра, пробелов и дефисов.
    """
    make_text = " ".join(make.split())
    model_text = " ".join((model or "").split())
    if not model_text:
        return make_text
    if not make_text:
        return model_text
    make_key = _key(make_text)
    if not make_key:
        return model_text
    if _key(model_text) == make_key:
        return make_text
    if _starts_with_word(model_text, make_key):
        return model_text
    return f"{make_text} {model_text}"


def display_vehicle_name(vehicle: Vehicle) -> str:
    return display_name(vehicle.make, vehicle.model)


def _key(value: str) -> str:
    return SEPARATORS_RE.sub("", value).casefold()


def _starts_with_word(model: str, make_key: str) -> bool:
    """Модель начинается с марки целым словом: между буквами марки допускаются пробелы и дефисы."""
    pattern = r"[\s\-–—]*".join(re.escape(char) for char in make_key)
    return re.match(rf"{pattern}(?![^\W\d_])", model, re.IGNORECASE) is not None


class VehicleStore:
    """Read-only парк из файла. Регистр госномера важен, поиск по гаражному номеру — без регистра."""

    def __init__(self, vehicles: list[Vehicle]) -> None:
        self._vehicles = {v.vehicle_id: v for v in vehicles}

    @classmethod
    def load(cls, path: Path) -> "VehicleStore":
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return cls([Vehicle.model_validate(item) for item in data["vehicles"]])

    def __len__(self) -> int:
        return len(self._vehicles)

    def all(self) -> list[Vehicle]:
        return list(self._vehicles.values())

    def get(self, vehicle_id: str) -> Vehicle | None:
        return self._vehicles.get(vehicle_id)

    def search(self, query: str) -> list[Vehicle]:
        needle = query.strip().casefold()
        if not needle:
            return self.all()
        return [
            v
            for v in self._vehicles.values()
            if needle in v.vehicle_id.casefold() or needle in v.garage_no.casefold()
        ]

    def history(self, vehicle_id: str, until_session_id: str | None = None) -> list[SessionRecord]:
        """Проверки машины по времени. С until_session_id — только более ранние проверки."""
        vehicle = self.get(vehicle_id)
        if vehicle is None:
            return []
        sessions = vehicle.sessions
        if until_session_id is None:
            return list(sessions)
        ids = [s.session_id for s in sessions]
        if until_session_id not in ids:
            return []
        return sessions[: ids.index(until_session_id)]
