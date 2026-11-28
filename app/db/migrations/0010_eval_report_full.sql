-- Полный отчёт прогона (фрагменты руководств и ответы агента) хранится только в БД.
-- В report_md остаются метрики: его можно копировать в eval/*.md и в git (п. 9.1).

ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS report_full_md TEXT;
