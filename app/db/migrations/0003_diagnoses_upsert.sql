-- Один диагноз на проверку: повторный ход той же сессии обновляет строку, а не добавляет новую.
-- Дубли, накопленные до миграции, оставляем самые свежие (наибольший id).

DELETE FROM diagnoses older
USING diagnoses newer
WHERE older.tenant_id = newer.tenant_id
  AND older.vehicle_id = newer.vehicle_id
  AND older.session_id = newer.session_id
  AND older.id < newer.id;

ALTER TABLE diagnoses
    ADD CONSTRAINT diagnoses_session_uniq UNIQUE (tenant_id, vehicle_id, session_id);
