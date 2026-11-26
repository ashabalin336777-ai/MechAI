-- Одна рекомендация каждого вида на проверку: повторный ход обновляет текст, а не добавляет строку.
-- Ключ включает kind: в одной сессии могут быть разные рекомендации (например, low_confidence
-- и defect_inspection_no_procedure). Дубли, накопленные до миграции, оставляем самые свежие.

DELETE FROM recommendations older
USING recommendations newer
WHERE older.tenant_id = newer.tenant_id
  AND older.vehicle_id = newer.vehicle_id
  AND older.session_id = newer.session_id
  AND older.kind = newer.kind
  AND older.id < newer.id;

ALTER TABLE recommendations
    ADD CONSTRAINT recommendations_session_kind_uniq UNIQUE (tenant_id, vehicle_id, session_id, kind);
