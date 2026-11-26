-- Черновики заявок ТОиР и одноразовые подтверждения (ТЗ §6.2, §6.4 п.3).
-- В базе лежат только хэш состава черновика и хэш confirm_token. Сам токен хранится у интерфейса механика.
-- claimed_at ставится атомарно перед вызовом ТОиР: повторное подтверждение не отправит вторую заявку.

CREATE TABLE ticket_drafts (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    TEXT NOT NULL REFERENCES tenants(id),
    draft_id     TEXT NOT NULL,
    vehicle_id   TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    payload      JSONB NOT NULL,
    draft_hash   TEXT NOT NULL,
    token_hash   TEXT NOT NULL,
    verdict_code TEXT NOT NULL CHECK (verdict_code IN ('anomaly', 'needs_confirmation')),
    claimed_at   TIMESTAMPTZ,
    ticket_id    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, draft_id)
);
