"""Инструменты агента и подтверждение заявки: engine_guard, ticket_guard, повтор confirm_token."""

import pytest

from app.clients.toir_client import ToirClient
from app.rag.search import Fragment
from app.tools import draft_ticket, get_diagnosis, search_manual
from app.tools.create_ticket import ConfirmError, confirm_draft
from app.tools.runtime import Runtime, TurnContext
from tests.agent_helpers import (
    DIAG_SESSION,
    DIAG_VEHICLE,
    YAMZ236_RK,
    YAMZ536_RE,
    ScriptedChat,
    make_ready_draft,
    make_services,
    manual_fragment,
)
from tests.helpers import STUB_BASE, FailingHttp


def _runtime(services, vehicle: str, session: str) -> Runtime:
    return Runtime(deps=services.deps, turn=TurnContext(vehicle_id=vehicle, session_id=session))


def test_search_manual_drops_fragments_of_other_engine() -> None:
    services = make_services(ScriptedChat([]))
    foreign = Fragment(
        manual_id="yamz536_re",
        manual=YAMZ536_RE,
        pdf_page=10,
        section=None,
        text="Зазор клапанов 0,30 мм",
        score=0.99,
    )
    services.deps.search = lambda query, engine, top_k: [foreign]
    runtime = _runtime(services, DIAG_VEHICLE, DIAG_SESSION)
    result = search_manual.run(
        runtime,
        search_manual.Args(query="зазор клапанов", vehicle_id=DIAG_VEHICLE, top_k=3),
    )
    assert result["found"] is False
    assert runtime.turn.retrieved == []
    assert runtime.turn.fetched_now == []


def test_search_manual_keeps_own_engine_fragment() -> None:
    services = make_services(ScriptedChat([]))
    services.deps.search = lambda query, engine, top_k: [manual_fragment()]
    runtime = _runtime(services, DIAG_VEHICLE, DIAG_SESSION)
    result = search_manual.run(
        runtime,
        search_manual.Args(query="момент затяжки головки", vehicle_id=DIAG_VEHICLE, top_k=3),
    )
    assert result["found"] is True
    assert len(runtime.turn.fetched_now) == 1


def test_check_failed_never_gets_ticket_draft() -> None:
    services = make_services(ScriptedChat([]))
    runtime = _runtime(services, "P456AT178", "S-0003")
    diagnosis = get_diagnosis.run(
        runtime, get_diagnosis.Args(vehicle_id="P456AT178", session_id="S-0003")
    )
    assert diagnosis["verdict"]["code"] == "check_failed"
    runtime.turn.remember([manual_fragment()])
    result = draft_ticket.run(
        runtime,
        draft_ticket.Args(
            vehicle_id="P456AT178",
            session_id="S-0003",
            conclusion="Попытка создать заявку при сбое записи",
            urgency="high",
            operations=["Снять головку блока"],
            spare_parts=[],
            references=[draft_ticket.Reference(manual=YAMZ236_RK, pdf_page=267)],
        ),
    )
    assert result["ok"] is False
    assert not any(name == "ticket_draft" for name, _ in runtime.turn.events)


def test_ticket_confirm_creates_once_and_repeat_returns_same_ticket() -> None:
    services = make_services(ScriptedChat([]))
    draft_id, token = make_ready_draft(services)

    first = confirm_draft(services.deps.store, services.deps.toir, draft_id, token)
    second = confirm_draft(services.deps.store, services.deps.toir, draft_id, token)

    assert first.created is True
    assert second.created is False
    assert second.ticket_id == first.ticket_id
    assert len(services.deps.store.list_tickets(DIAG_VEHICLE)) == 1


def test_wrong_token_is_rejected_without_ticket() -> None:
    services = make_services(ScriptedChat([]))
    draft_id, _ = make_ready_draft(services)
    with pytest.raises(ConfirmError) as exc:
        confirm_draft(services.deps.store, services.deps.toir, draft_id, "неверный-токен")
    assert exc.value.status == 403
    assert services.deps.store.list_tickets(DIAG_VEHICLE) == []


def test_unknown_draft_is_not_found() -> None:
    services = make_services(ScriptedChat([]))
    with pytest.raises(ConfirmError) as exc:
        confirm_draft(services.deps.store, services.deps.toir, "DR-нет", "токен")
    assert exc.value.status == 404


def test_changed_composition_is_conflict() -> None:
    services = make_services(ScriptedChat([]))
    draft_id, token = make_ready_draft(services)
    services.deps.store._drafts[draft_id].payload["conclusion"] = "Состав подменили"
    with pytest.raises(ConfirmError) as exc:
        confirm_draft(services.deps.store, services.deps.toir, draft_id, token)
    assert exc.value.status == 409
    assert services.deps.store.list_tickets(DIAG_VEHICLE) == []


def test_unavailable_toir_releases_draft_for_retry() -> None:
    services = make_services(ScriptedChat([]))
    draft_id, token = make_ready_draft(services)
    broken = ToirClient(STUB_BASE, http=FailingHttp())  # type: ignore[arg-type]
    with pytest.raises(ConfirmError) as exc:
        confirm_draft(services.deps.store, broken, draft_id, token)
    assert exc.value.status == 503
    assert services.deps.store.get_draft(draft_id).claimed is False  # type: ignore[union-attr]

    result = confirm_draft(services.deps.store, services.deps.toir, draft_id, token)
    assert result.created is True
