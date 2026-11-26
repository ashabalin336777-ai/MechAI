"""Хранилище агента: диагнозы, рекомендации, черновики заявок, заявки ТОиР.

Два варианта одного протокола: PostgreSQL (боевой) и память (тесты и запуск без DATABASE_URL).
Все запросы фильтруются по tenant_id (ТЗ §4.1).
"""

import threading
from datetime import datetime
from typing import Any, Literal, Protocol

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

TENANT_ID = "demo"
RecommendationKind = Literal["repeat_recording", "defect_inspection_no_procedure", "low_confidence"]


class DraftRecord(BaseModel):
    draft_id: str
    vehicle_id: str
    session_id: str
    payload: dict[str, Any]
    draft_hash: str
    token_hash: str
    verdict_code: Literal["anomaly", "needs_confirmation"]
    claimed: bool = False
    ticket_id: str | None = None


class TicketRecord(BaseModel):
    ticket_id: str
    session_id: str
    created_at: datetime
    payload: dict[str, Any]


class AgentStore(Protocol):
    def save_diagnosis(
        self, vehicle_id: str, session_id: str, payload: dict[str, Any], verdict: str
    ) -> None: ...

    def save_recommendation(
        self, vehicle_id: str, session_id: str, kind: RecommendationKind, text: str
    ) -> None: ...

    def save_draft(self, draft: DraftRecord) -> None: ...

    def get_draft(self, draft_id: str) -> DraftRecord | None: ...

    def claim_draft(self, draft_id: str) -> bool: ...

    def release_draft(self, draft_id: str) -> None: ...

    def complete_draft(self, draft_id: str, ticket_id: str) -> None: ...

    def list_tickets(self, vehicle_id: str) -> list[TicketRecord]: ...


class MemoryAgentStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.diagnoses: list[tuple[str, str, str]] = []
        self.recommendations: list[tuple[str, str, str]] = []
        self._drafts: dict[str, DraftRecord] = {}
        self._tickets: list[tuple[str, str, str, dict[str, Any], datetime]] = []

    def save_diagnosis(
        self, vehicle_id: str, session_id: str, payload: dict[str, Any], verdict: str
    ) -> None:
        with self._lock:
            self.diagnoses.append((vehicle_id, session_id, verdict))

    def save_recommendation(
        self, vehicle_id: str, session_id: str, kind: RecommendationKind, text: str
    ) -> None:
        with self._lock:
            self.recommendations.append((vehicle_id, session_id, kind))

    def save_draft(self, draft: DraftRecord) -> None:
        with self._lock:
            self._drafts[draft.draft_id] = draft.model_copy()

    def get_draft(self, draft_id: str) -> DraftRecord | None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            return draft.model_copy() if draft else None

    def claim_draft(self, draft_id: str) -> bool:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None or draft.claimed or draft.ticket_id:
                return False
            draft.claimed = True
            return True

    def release_draft(self, draft_id: str) -> None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is not None and not draft.ticket_id:
                draft.claimed = False

    def complete_draft(self, draft_id: str, ticket_id: str) -> None:
        with self._lock:
            draft = self._drafts[draft_id]
            draft.ticket_id = ticket_id
            draft.claimed = False
            self._tickets.append(
                (draft.vehicle_id, draft.session_id, ticket_id, draft.payload, datetime.now())
            )

    def list_tickets(self, vehicle_id: str) -> list[TicketRecord]:
        with self._lock:
            return [
                TicketRecord(ticket_id=tid, session_id=sid, created_at=created, payload=payload)
                for vid, sid, tid, payload, created in self._tickets
                if vid == vehicle_id
            ]


class PgAgentStore:
    """Каждая операция — короткая транзакция. Соединение на операцию: нагрузка демо мала."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._url, connect_timeout=5, autocommit=True)

    def save_diagnosis(
        self, vehicle_id: str, session_id: str, payload: dict[str, Any], verdict: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO diagnoses (tenant_id, vehicle_id, session_id, payload, verdict) "
                "VALUES (%s, %s, %s, %s, %s)",
                (TENANT_ID, vehicle_id, session_id, Jsonb(payload), verdict),
            )

    def save_recommendation(
        self, vehicle_id: str, session_id: str, kind: RecommendationKind, text: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO recommendations (tenant_id, vehicle_id, session_id, kind, text) "
                "VALUES (%s, %s, %s, %s, %s)",
                (TENANT_ID, vehicle_id, session_id, kind, text),
            )

    def save_draft(self, draft: DraftRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ticket_drafts (tenant_id, draft_id, vehicle_id, session_id, payload, "
                "draft_hash, token_hash, verdict_code) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    TENANT_ID,
                    draft.draft_id,
                    draft.vehicle_id,
                    draft.session_id,
                    Jsonb(draft.payload),
                    draft.draft_hash,
                    draft.token_hash,
                    draft.verdict_code,
                ),
            )

    def get_draft(self, draft_id: str) -> DraftRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT draft_id, vehicle_id, session_id, payload, draft_hash, token_hash, "
                "verdict_code, claimed_at IS NOT NULL, ticket_id FROM ticket_drafts "
                "WHERE tenant_id = %s AND draft_id = %s",
                (TENANT_ID, draft_id),
            ).fetchone()
        if row is None:
            return None
        return DraftRecord(
            draft_id=row[0],
            vehicle_id=row[1],
            session_id=row[2],
            payload=row[3],
            draft_hash=row[4],
            token_hash=row[5],
            verdict_code=row[6],
            claimed=bool(row[7]),
            ticket_id=row[8],
        )

    def claim_draft(self, draft_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE ticket_drafts SET claimed_at = now() "
                "WHERE tenant_id = %s AND draft_id = %s "
                "AND claimed_at IS NULL AND ticket_id IS NULL RETURNING id",
                (TENANT_ID, draft_id),
            ).fetchone()
        return row is not None

    def release_draft(self, draft_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE ticket_drafts SET claimed_at = NULL WHERE tenant_id = %s AND draft_id = %s "
                "AND ticket_id IS NULL",
                (TENANT_ID, draft_id),
            )

    def complete_draft(self, draft_id: str, ticket_id: str) -> None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "UPDATE ticket_drafts SET ticket_id = %s, claimed_at = NULL "
                "WHERE tenant_id = %s AND draft_id = %s RETURNING vehicle_id, session_id, payload",
                (ticket_id, TENANT_ID, draft_id),
            ).fetchone()
            if row is None:
                raise LookupError(draft_id)
            conn.execute(
                "INSERT INTO tickets (tenant_id, vehicle_id, session_id, ticket_id, payload) "
                "VALUES (%s, %s, %s, %s, %s)",
                (TENANT_ID, row[0], row[1], ticket_id, Jsonb(row[2])),
            )

    def list_tickets(self, vehicle_id: str) -> list[TicketRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ticket_id, session_id, created_at, payload FROM tickets "
                "WHERE tenant_id = %s AND vehicle_id = %s ORDER BY created_at",
                (TENANT_ID, vehicle_id),
            ).fetchall()
        return [
            TicketRecord(ticket_id=r[0], session_id=r[1], created_at=r[2], payload=r[3])
            for r in rows
        ]
