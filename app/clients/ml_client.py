"""Клиент Mock ML: POST /diagnose. Контракт — mock/openapi_ml.json (раздел 5.1 ТЗ)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.clients.base import ServiceClient


class DiagnoseRequest(BaseModel):
    vehicle_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


class DiagnoseResponse(BaseModel):
    vehicle_id: str
    session_id: str
    status: Literal["normal", "anomaly", "check_failed"]
    anomaly_type: str | None = Field(pattern=r"^F(0[1-9]|1[0-4])$")
    anomaly_title: str | None
    anomaly_score: float | None = Field(ge=0, le=1)
    confidence: float | None = Field(ge=0, le=1)
    signal_quality: Literal["good", "warning", "bad"]
    description: str
    model_version: str


class MlClient(ServiceClient):
    service_name = "mock_ml"

    def diagnose(self, vehicle_id: str, session_id: str) -> DiagnoseResponse:
        body = DiagnoseRequest(vehicle_id=vehicle_id, session_id=session_id)
        response = self._request("POST", "/diagnose", body)
        return self._parse(response, DiagnoseResponse)
