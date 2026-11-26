"""Парк из mock/data/vehicles.json: 50 ТС, 195 проверок, поиск, история, модель null → марка."""

from pathlib import Path

from app.data.vehicles import VehicleStore

VEHICLES_PATH = Path(__file__).resolve().parent.parent / "mock" / "data" / "vehicles.json"


def _store() -> VehicleStore:
    return VehicleStore.load(VEHICLES_PATH)


def test_loads_fifty_vehicles_and_195_sessions() -> None:
    store = _store()
    assert len(store) == 50
    assert sum(len(v.sessions) for v in store.all()) == 195


def test_maz_with_null_model_shows_make() -> None:
    store = _store()
    maz_without_model = [v for v in store.all() if v.make == "МАЗ" and v.model == "МАЗ"]
    assert maz_without_model, "ожидаем МАЗ, у которого модель в файле null"
    assert all(v.model == "МАЗ" for v in maz_without_model)


def test_search_by_plate_returns_exact_vehicle() -> None:
    store = _store()
    found = store.search("T792HO98")
    assert [v.vehicle_id for v in found] == ["T792HO98"]


def test_search_by_garage_number() -> None:
    store = _store()
    found = store.search("Г-112")
    assert [v.vehicle_id for v in found] == ["T792HO98"]


def test_search_empty_returns_all() -> None:
    assert len(_store().search("   ")) == 50


def test_control_case_vehicle_has_five_sessions_and_anomaly_last() -> None:
    vehicle = _store().get("T792HO98")
    assert vehicle is not None
    scores = [s.anomaly_score for s in vehicle.sessions]
    assert scores == [0.08, 0.06, 0.2, 0.85]
    last = vehicle.last_session
    assert last is not None
    assert last.session_id == "S-0043"
    assert last.anomaly_type == "F02"


def test_history_before_selected_session_excludes_it() -> None:
    store = _store()
    before = store.history("T792HO98", until_session_id="S-0043")
    assert [s.session_id for s in before] == ["S-0040", "S-0041", "S-0042"]


def test_history_unknown_vehicle_is_empty() -> None:
    assert _store().history("X000XX00") == []
