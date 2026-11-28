"""Название ТС на экране: марка и модель без повтора марки (display_vehicle_name)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.data.vehicles import Vehicle, VehicleStore, display_name, display_vehicle_name
from tests.helpers import VEHICLES_PATH


@pytest.mark.parametrize(
    ("make", "model", "expected"),
    [
        ("МАЗ", "МАЗ", "МАЗ"),  # модель совпадает с маркой
        ("МАЗ", None, "МАЗ"),  # модель null в данных
        ("МАЗ", "", "МАЗ"),  # модель пустая строка
        ("КАМАЗ", "КАМАЗ", "КАМАЗ"),
        ("КАМАЗ", "КАМАЗ-65115", "КАМАЗ-65115"),  # модель начинается с марки через дефис
        ("КАМАЗ", "", "КАМАЗ"),
        ("УАЗ", "УАЗ Патриот", "УАЗ Патриот"),  # марка отдельным словом в начале модели
        ("МАЗ", "МАЗ-5337", "МАЗ-5337"),
        ("ГАЗ", "ГАЗель", "ГАЗ ГАЗель"),  # «ГАЗель» — не слово «ГАЗ», марка остаётся
        ("МАЗ", "МАЗДА 3", "МАЗ МАЗДА 3"),  # «МАЗДА» не начинается с марки как слово
        ("МАЗ", "маз", "МАЗ"),  # без учёта регистра
        ("МАЗ", "М А З", "МАЗ"),  # пробелы внутри модели
        ("  МАЗ  ", " МАЗ ", "МАЗ"),  # лишние пробелы
        ("УАЗ", "Патриот", "УАЗ Патриот"),  # модель без марки
    ],
)
def test_display_name_shows_make_once(make: str, model: str | None, expected: str) -> None:
    assert display_name(make, model) == expected


def test_display_name_handles_empty_make() -> None:
    assert display_name("", "Патриот") == "Патриот"
    assert display_name("", "") == ""


def test_display_vehicle_name_takes_make_and_model_from_vehicle() -> None:
    vehicle = Vehicle.model_validate(
        {
            "vehicle_id": "С596ХТ78",
            "garage_no": "1",
            "make": "МАЗ",
            "model": None,
            "vehicle_type": "грузовой",
            "engine_model": "ЯМЗ-536",
            "fuel": "дизель",
            "sessions": [],
        }
    )
    assert display_vehicle_name(vehicle) == "МАЗ"


def test_no_vehicle_in_the_fleet_shows_the_make_twice() -> None:
    store = VehicleStore.load(VEHICLES_PATH)
    for vehicle in store.all():
        name = display_vehicle_name(vehicle)
        assert not name.casefold().startswith(f"{vehicle.make} {vehicle.make}".casefold()), (
            vehicle.vehicle_id,
            name,
        )


def test_vehicle_header_on_pages_does_not_repeat_the_make(app_with_stubs: FastAPI) -> None:
    client = TestClient(app_with_stubs)
    store = VehicleStore.load(VEHICLES_PATH)
    same_name = next(
        vehicle for vehicle in store.all() if vehicle.make == "ТЕСТ" and vehicle.model == "ТЕСТ"
    )
    dashboard_html = client.get(f"/dashboard/{same_name.vehicle_id}").text
    assert f"{same_name.vehicle_id} · ТЕСТ</h1>" in dashboard_html
    assert "ТЕСТ ТЕСТ" not in dashboard_html
    assert "ТЕСТ ТЕСТ" not in client.get("/dashboard").text
    assert "ТЕСТ ТЕСТ" not in client.get("/vehicles").text
