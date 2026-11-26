"""Сборка сервисов агента из настроек: модель, инструменты, журнал, хранилище, checkpointer.

Без DATABASE_URL всё работает в памяти (локальные тесты и демо без БД). С ним — Postgres:
журнал, заявки, состояние диалога LangGraph (ТЗ §4.1, §6.1).
"""

import logging

import psycopg
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.llm import NeuraldeepChat
from app.agent.runner import AgentServices
from app.agent.verdict import Thresholds
from app.clients.ml_client import MlClient
from app.clients.toir_client import ToirClient
from app.config import Settings
from app.data.vehicles import VehicleStore
from app.db.agent_store import MemoryAgentStore, PgAgentStore
from app.obs.journal import MemoryJournal, PgJournal
from app.rag.conflicts import load_conflicts
from app.rag.embeddings import EmbeddingClient
from app.rag.manifest import Manifest
from app.rag.rerank import RerankClient
from app.rag.search import TENANT_ID, Fragment, fetch_manual_pages, search
from app.tools.registry import build_registry
from app.tools.runtime import PageFetchFn, SearchFn, ToolDeps, no_pages

logger = logging.getLogger("app.agent")


def build_agent_services(
    settings: Settings,
    vehicles: VehicleStore,
    manifest: Manifest,
    ml: MlClient,
    toir: ToirClient,
) -> AgentServices:
    database = bool(settings.database_url)
    deps = ToolDeps(
        vehicles=vehicles,
        manifest=manifest,
        thresholds=Thresholds(
            conf_low=settings.conf_low,
            score_medium=settings.score_medium,
            score_high=settings.score_high,
        ),
        ml=ml,
        toir=toir,
        store=PgAgentStore(settings.database_url) if database else MemoryAgentStore(),
        search=_build_search(settings),
        conflicts=load_conflicts(settings.known_conflicts_path),
        fetch_pages=_build_fetch_pages(settings),
    )
    llm = NeuraldeepChat(
        api_key=settings.neuraldeep_api_key,
        base_url=settings.neuraldeep_base_url,
        model=settings.agent_model,
        fallback_model=settings.agent_fallback_model,
    )
    return AgentServices(
        deps=deps,
        llm=llm,
        registry=build_registry(),
        journal=PgJournal(settings.database_url) if database else MemoryJournal(),
        checkpointer=InMemorySaver(),
        timeout_s=settings.agent_timeout_s,
        max_tool_calls=settings.agent_max_tool_calls,
    )


def use_postgres_checkpointer(services: AgentServices, database_url: str) -> None:
    """Состояние диалога в Postgres после миграций. При ошибке остаёмся в памяти."""
    from langgraph.checkpoint.postgres import PostgresSaver

    try:
        conn = psycopg.connect(database_url, connect_timeout=5, autocommit=True)
        saver = PostgresSaver(conn)
        saver.setup()
    except psycopg.Error as exc:
        logger.warning(
            "checkpointer в Postgres недоступен, остаёмся в памяти: %s", type(exc).__name__
        )
        return
    services.checkpointer = saver


def _build_search(settings: Settings) -> SearchFn:
    if not settings.database_url:

        def no_index(query: str, engine_model: str, top_k: int) -> list[Fragment]:
            return []

        return no_index

    embedder = EmbeddingClient(
        settings.neuraldeep_api_key, settings.neuraldeep_base_url, settings.embed_model
    )
    reranker = RerankClient(
        settings.neuraldeep_api_key, settings.neuraldeep_base_url, settings.rerank_model
    )

    def run_search(query: str, engine_model: str, top_k: int) -> list[Fragment]:
        with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
            return search(
                conn,
                query,
                engine_model,
                embedder,
                reranker,
                top_k=top_k,
                min_score=settings.rag_min_score,
            )

    return run_search


def _build_fetch_pages(settings: Settings) -> PageFetchFn:
    if not settings.database_url:
        return no_pages

    def fetch(engine_model: str, designation: str, pages: list[int]) -> list[Fragment]:
        with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
            return fetch_manual_pages(conn, TENANT_ID, engine_model, designation, pages)

    return fetch
