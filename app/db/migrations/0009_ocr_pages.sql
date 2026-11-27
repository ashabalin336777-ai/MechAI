-- Статус OCR по страницам руководства (app/rag/ocr.py):
--   stored          — текст записан чанками source='ocr';
--   skipped_drawing — распознано слишком мало текста: рисунок или схема без текста, не повторяем;
--   failed          — ошибка вызова модели или записи, при следующем запуске повторяем.

CREATE TABLE ocr_pages (
    tenant_id   TEXT NOT NULL DEFAULT 'demo' REFERENCES tenants(id),
    manual_id   TEXT NOT NULL,
    pdf_page    INTEGER NOT NULL CHECK (pdf_page >= 1),
    status      TEXT NOT NULL CHECK (status IN ('stored', 'skipped_drawing', 'failed')),
    model       TEXT,
    text_chars  INTEGER,
    error       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, manual_id, pdf_page),
    FOREIGN KEY (tenant_id, manual_id) REFERENCES manuals (tenant_id, id)
);

-- Страницы, уже записанные OCR до появления таблицы.
INSERT INTO ocr_pages (tenant_id, manual_id, pdf_page, status, updated_at)
SELECT DISTINCT tenant_id, manual_id, pdf_page, 'stored', now()
FROM chunks
WHERE source = 'ocr'
ON CONFLICT DO NOTHING;

-- Страницы, которые прогон 27.11 не смог распознать как текст («распознано слишком мало текста»).
-- Перечислены явно, чтобы следующий запуск их не перераспознавал. На пустой базе строки не
-- добавляются: JOIN с manuals.
INSERT INTO ocr_pages (tenant_id, manual_id, pdf_page, status, error, updated_at)
SELECT m.tenant_id, m.id, v.pdf_page, 'skipped_drawing',
       'распознано слишком мало текста', now()
FROM (VALUES
    ('yamz236_rk', 91), ('yamz236_rk', 105), ('yamz236_rk', 153),
    ('yamz236_rk', 162), ('yamz236_rk', 169), ('yamz536_re', 285)
) AS v(manual_id, pdf_page)
JOIN manuals m ON m.tenant_id = 'demo' AND m.id = v.manual_id
ON CONFLICT DO NOTHING;
