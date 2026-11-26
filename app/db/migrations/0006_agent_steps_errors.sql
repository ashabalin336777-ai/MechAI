-- Журнал агента: класс и краткий текст ошибки шага (без строки подключения и ключей),
-- новые виды шагов retry (повтор вызова внешнего сервиса) и error (сбой хода или вызова).

ALTER TABLE agent_steps
    ADD COLUMN error_class TEXT,
    ADD COLUMN error_message TEXT;

ALTER TABLE agent_steps DROP CONSTRAINT agent_steps_kind_check;

ALTER TABLE agent_steps
    ADD CONSTRAINT agent_steps_kind_check
    CHECK (kind IN ('llm', 'tool', 'guardrail', 'retry', 'error'));
