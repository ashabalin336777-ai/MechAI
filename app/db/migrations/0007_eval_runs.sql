-- Прогоны проверки (POST /admin/eval): статус, сводка и отчёт в БД, чтобы результат
-- переживал перезапуск сервиса. Строку подключения, ключи и токены сюда не пишем.
-- tenant_id как у остальных таблиц: все запросы фильтруются по нему.

CREATE TABLE IF NOT EXISTS eval_runs (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT 'demo' REFERENCES tenants(id),
    suite         TEXT NOT NULL CHECK (suite IN ('rag', 'agent')),
    commit_sha    TEXT,
    status        TEXT NOT NULL CHECK (status IN ('running', 'done', 'error')),
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    passed        INTEGER CHECK (passed >= 0),
    total         INTEGER CHECK (total >= 0),
    report_md     TEXT,
    report_json   JSONB,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS eval_runs_tenant_started_idx ON eval_runs (tenant_id, started_at);
