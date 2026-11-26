-- Схема по docs/TZ.md §4.1. Все прикладные таблицы несут tenant_id (SaaS-ready).
-- Расширения vector и pg_trgm на Managed PostgreSQL включаются заранее в панели (docs/deploy.md).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE tenants (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    plan       TEXT NOT NULL DEFAULT 'demo',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    TEXT NOT NULL REFERENCES tenants(id),
    tabel_no     TEXT NOT NULL,
    pin_hash     TEXT,
    role         TEXT NOT NULL CHECK (role IN ('mechanic', 'chief', 'admin')),
    display_name TEXT,
    ui_mode      TEXT NOT NULL DEFAULT 'standard' CHECK (ui_mode IN ('standard', 'novice', 'senior')),
    lang         TEXT NOT NULL DEFAULT 'ru',
    consent_at   TIMESTAMPTZ,
    UNIQUE (tenant_id, tabel_no)
);

CREATE TABLE manuals (
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    id         TEXT NOT NULL,
    designation TEXT NOT NULL,
    title      TEXT NOT NULL,
    year       INTEGER,
    file_name  TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    pages      INTEGER NOT NULL CHECK (pages >= 1),
    engine_models TEXT[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE chunks (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(id),
    manual_id     TEXT NOT NULL,
    engine_models TEXT[] NOT NULL,
    pdf_page      INTEGER NOT NULL CHECK (pdf_page >= 1),
    section       TEXT,
    text          TEXT NOT NULL,
    tsv           TSVECTOR GENERATED ALWAYS AS (to_tsvector('russian', text)) STORED,
    embedding     VECTOR(1024),
    FOREIGN KEY (tenant_id, manual_id) REFERENCES manuals(tenant_id, id)
);
CREATE INDEX chunks_engine_models_idx ON chunks USING GIN (engine_models);
CREATE INDEX chunks_tsv_idx ON chunks USING GIN (tsv);
CREATE INDEX chunks_embedding_idx ON chunks USING HNSW (embedding vector_cosine_ops);
CREATE INDEX chunks_text_trgm_idx ON chunks USING GIN (text gin_trgm_ops);

CREATE TABLE diagnoses (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    vehicle_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    payload    JSONB NOT NULL,
    verdict    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX diagnoses_vehicle_idx ON diagnoses (tenant_id, vehicle_id, created_at);

CREATE TABLE tickets (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    vehicle_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    ticket_id  TEXT NOT NULL,
    payload    JSONB NOT NULL,
    created_by BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, ticket_id)
);
CREATE INDEX tickets_vehicle_idx ON tickets (tenant_id, vehicle_id, created_at);

CREATE TABLE recommendations (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id),
    vehicle_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('repeat_recording', 'defect_inspection_no_procedure', 'low_confidence')),
    text       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_runs (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         TEXT NOT NULL REFERENCES tenants(id),
    user_id           BIGINT REFERENCES users(id),
    vehicle_id        TEXT,
    session_id        TEXT,
    lang              TEXT NOT NULL DEFAULT 'ru',
    input_mode        TEXT NOT NULL DEFAULT 'text' CHECK (input_mode IN ('text', 'voice')),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_ms          INTEGER,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    cost_rub          NUMERIC(12, 4),
    tok_per_s         NUMERIC(10, 2),
    status            TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'error'))
);
CREATE INDEX agent_runs_tenant_started_idx ON agent_runs (tenant_id, started_at);

CREATE TABLE agent_steps (
    id                BIGSERIAL PRIMARY KEY,
    run_id            BIGINT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    n                 INTEGER NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('llm', 'tool', 'guardrail')),
    name              TEXT NOT NULL,
    input             JSONB,
    output            JSONB,
    ms                INTEGER,
    ttft_ms           INTEGER,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    tok_per_s         NUMERIC(10, 2),
    model             TEXT,
    error             TEXT,
    UNIQUE (run_id, n)
);

INSERT INTO tenants (id, name, plan) VALUES ('demo', 'Демо-автопарк', 'demo')
ON CONFLICT (id) DO NOTHING;
