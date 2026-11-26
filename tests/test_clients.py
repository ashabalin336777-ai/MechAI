"""Клиенты ML и ТОиР против настоящих заглушек из mock/ (TestClient): 200, 404, 422, сеть, схема."""

import pytest

from app.clients.base import error_for_status
from app.clients.errors import NotFound, Unavailable, ValidationFailed
from app.clients.ml_client import DiagnoseResponse, MlClient
from app.clients.toir_client import Reference, TicketRequest, ToirClient
from tests.helpers import STUB_BASE, FailingHttp


def _ticket(vehicle_id: str = "M333YK47", session_id: str = "S-0005") -> TicketRequest:
    return TicketRequest(
        vehicle_id=vehicle_id,
        session_id=session_id,
        anomaly_type="F08",
        conclusion="Тестовая заявка фазы 01",
        urgency="medium",
        operations=["Проверить топливоподачу"],
        spare_parts=[],
        references=[Reference(manual="236-3902150-Б РЭ", pdf_page=1)],
    )


# --- Mock ML ---------------------------------------------------------------------------------


def test_diagnose_returns_validated_model(ml_client: MlClient) -> None:
    result = ml_client.diagnose("M333YK47", "S-0005")
    assert isinstance(result, DiagnoseResponse)
    assert result.status == "anomaly"
    assert result.anomaly_type == "F08"
    assert result.model_version == "mock-v1"


def test_diagnose_check_failed_has_nulls(ml_client: MlClient) -> None:
    result = ml_client.diagnose("P456AT178", "S-0003")
    assert result.status == "check_failed"
    assert result.signal_quality == "bad"
    assert result.anomaly_type is None
    assert result.anomaly_score is None
    assert result.confidence is None


def test_diagnose_unknown_vehicle_is_not_found(ml_client: MlClient) -> None:
    with pytest.raises(NotFound) as exc:
        ml_client.diagnose("X000XX00", "S-0005")
    assert "не найдена" in exc.value.user_message


def test_diagnose_session_of_other_vehicle_is_not_found(ml_client: MlClient) -> None:
    with pytest.raises(NotFound):
        ml_client.diagnose("P456AT178", "S-0005")


def test_diagnose_rejects_empty_ids_before_sending(ml_client: MlClient) -> None:
    with pytest.raises(ValueError):
        ml_client.diagnose("", "S-0005")


def test_ml_health_is_true_for_stub(ml_client: MlClient) -> None:
    assert ml_client.health() is True


# --- Mock ТОиР -------------------------------------------------------------------------------


def test_create_ticket_returns_created(toir_client: ToirClient) -> None:
    response = toir_client.create_ticket(_ticket())
    assert response.status == "created"
    assert response.ticket_id.startswith("TKT-")


def test_create_ticket_unknown_session_is_not_found(toir_client: ToirClient) -> None:
    with pytest.raises(NotFound):
        toir_client.create_ticket(_ticket(session_id="S-9999"))


def test_toir_health_is_true_for_stub(toir_client: ToirClient) -> None:
    assert toir_client.health() is True


# --- Маппинг статусов и сеть (без заглушки) --------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, None),
        (201, None),
        (400, ValidationFailed),
        (404, NotFound),
        (418, ValidationFailed),
        (422, ValidationFailed),
        (500, Unavailable),
        (503, Unavailable),
    ],
)
def test_error_for_status_mapping(status: int, expected: type | None) -> None:
    error = error_for_status(status, "mock_toir")
    if expected is None:
        assert error is None
    else:
        assert isinstance(error, expected)


def test_network_error_retries_once_then_unavailable() -> None:
    http = FailingHttp()
    client = MlClient(STUB_BASE, http=http)  # type: ignore[arg-type]
    with pytest.raises(Unavailable):
        client.diagnose("M333YK47", "S-0005")
    assert http.calls == 2


def test_health_returns_false_when_service_down() -> None:
    client = ToirClient(STUB_BASE, http=FailingHttp())  # type: ignore[arg-type]
    assert client.health() is False
