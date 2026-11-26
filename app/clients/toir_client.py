"""Клиент Mock ТОиР: POST /tickets. Контракт — mock/openapi_toir.json (раздел 5.2 ТЗ)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.clients.base import ServiceClient


class Reference(BaseModel):
    manual: str = Field(min_length=1)
    pdf_page: int = Field(ge=1)


class TicketRequest(BaseModel):
    vehicle_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    anomaly_type: str = Field(pattern=r"^F(0[1-9]|1[0-4])$")
    conclusion: str = Field(min_length=1)
    urgency: Literal["low", "medium", "high"]
    operations: list[str] = Field(min_length=1)
    spare_parts: list[str]
    references: list[Reference] = Field(min_length=1)


class TicketResponse(BaseModel):
    ticket_id: str
    status: Literal["created"]


class ToirClient(ServiceClient):
    service_name = "mock_toir"

    def create_ticket(self, ticket: TicketRequest) -> TicketResponse:
        # Заявка не повторяется после таймаута или 5xx: сервис мог создать её и не ответить.
        response = self._request("POST", "/tickets", ticket, retry="connect")
        return self._parse(response, TicketResponse)
