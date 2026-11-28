-- Журнал голоса: вид шага stt (распознавание речи whisper-1). Аудио в журнал не пишем: только модель,
-- язык, размер, длительность, ошибка.

ALTER TABLE agent_steps DROP CONSTRAINT agent_steps_kind_check;

ALTER TABLE agent_steps
    ADD CONSTRAINT agent_steps_kind_check
    CHECK (kind IN ('llm', 'tool', 'guardrail', 'retry', 'error', 'stt'));
