-- Версия нарезки руководства. Ingest переиндексирует руководство, если версия в базе меньше
-- CHUNKER_VERSION (табличные строки «строка: колонка значение единица», см. app/rag/chunking.py).
-- Существующие руководства получают версию 1 и переиндексируются при следующем запуске ingest.

ALTER TABLE manuals
    ADD COLUMN chunker_version INT NOT NULL DEFAULT 1;
