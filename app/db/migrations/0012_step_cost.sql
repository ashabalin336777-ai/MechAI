-- Стоимость шага в ₽ и новые виды шагов: embed (эмбеддинги bge-m3), rerank (реранк bge-reranker).
-- NULL в cost_rub — шаг без цены (модели нет в прайсе или сервис не отдал число токенов).

ALTER TABLE agent_steps ADD COLUMN IF NOT EXISTS cost_rub NUMERIC(12, 4);

ALTER TABLE agent_steps DROP CONSTRAINT agent_steps_kind_check;

ALTER TABLE agent_steps
    ADD CONSTRAINT agent_steps_kind_check
    CHECK (kind IN ('llm', 'tool', 'guardrail', 'retry', 'error', 'stt', 'embed', 'rerank'));
