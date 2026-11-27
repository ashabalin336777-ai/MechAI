-- Источник чанка: text — текст слоя PDF (ingest), ocr — страница «только рисунок», распознанная
-- vision-моделью (app/rag/ocr.py). Переиндексация текста удаляет только source='text'.

ALTER TABLE chunks
    ADD COLUMN source TEXT NOT NULL DEFAULT 'text' CHECK (source IN ('text', 'ocr'));

CREATE INDEX chunks_ocr_page_idx ON chunks (tenant_id, manual_id, pdf_page) WHERE source = 'ocr';
