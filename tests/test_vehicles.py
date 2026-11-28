"""Парк ТС: поиск, история, модель null → марка. Данные синтетические (tests/fixtures)."""

from app.data.vehicles import VehicleStore
from tests.helpers import VEHICLES_PATH


def _store() -> VehicleStore:
    return VehicleStore.load(VEHICLES_PATH)


def test_loads_fixture_vehicles_and_sessions() -> None:
    store = _store()
    assert len(store) == 4
    assert sum(len(v.sessions) for v in store.all()) == 13


def test_null_model_shows_make() -> None:
    store = _store()
    null_model = [v for v in store.all() if v.make == "ТЕСТ" and v.model == "ТЕСТ"]
    assert null_model, "ожидаем ТС, у которого модель в файле null"
    assert any(v.vehicle_id == "TST-C003" for v in null_model)


def test_search_by_plate_returns_exact_vehicle() -> None:
    store = _store()
    found = store.search("TST-A001")
    assert [v.vehicle_id for v in found] == ["TST-A001"]


def test_search_by_garage_number() -> None:
    store = _store()
    found = store.search("ТЕСТ-001")
    assert [v.vehicle_id for v in found] == ["TST-A001"]


def test_search_empty_returns_all() -> None:
    assert len(_store().search("   ")) == 4


def test_vehicle_with_anomaly_last_has_anomaly_as_last_session() -> None:
    vehicle = _store().get("TST-A001")
    assert vehicle is not None
    scores = [s.anomaly_score for s in vehicle.sessions]
    assert scores == [0.05, None, 0.85]
    last = vehicle.last_session
    assert last is not None
    assert last.session_id == "S-9002"
    assert last.anomaly_type == "F02"


def test_history_before_selected_session_excludes_it() -> None:
    store = _store()
    before = store.history("TST-A001", until_session_id="S-9002")
    assert [s.session_id for s in before] == ["S-9001", "S-9003"]


def test_history_unknown_vehicle_is_empty() -> None:
    assert _store().history("X000XX00") == []
