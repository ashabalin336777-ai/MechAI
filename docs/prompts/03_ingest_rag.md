# 03 · Ingest PDF и поиск по руководствам (≈ 3 ч) — F4, Качество RAG

1. `data/manuals/manifest.yaml` по `docs/TZ.md` §3.2 (id, обозначение `manual`, название, год, файл, sha256, `engine_models`, страниц, URL Яндекс Диска).
2. `scripts/fetch_manuals.py`: если файла нет локально — скачать с публичного Яндекс Диска заказчика через `https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key=...&path=/<имя>` (обязательно для `yamz-536_rk_2013.pdf`), проверить sha256.
3. `app/rag/ingest.py` (`python -m app.rag.ingest`): pymupdf постранично; страница < 100 символов → OCR tesseract rus, если доступен, иначе пометка `image_only`; чанки 600–900 токенов с перекрытием 100 **внутри страницы**, `section` из ближайшего заголовка; эмбеддинги `EMBED_MODEL` батчами по 32; `tsvector('russian')`; идемпотентно по sha256; отчёт `eval/ingest_report.md`.
4. `app/rag/search.py`: `search(query, engine_model, top_k=6)` = pgvector (top 30) ∪ полнотекст (top 30) → RRF → `RERANK_MODEL` → top_k; **фильтр `engine_models @> [engine_model]` в SQL**; отсечка `RAG_MIN_SCORE`; результат `{manual_id, manual, pdf_page, section, text, score}`.
5. `app/rag/citations.py`: `citation_check(answer, fragments)` — ссылки только на полученные страницы, цифры с единицами должны встречаться в тексте фрагмента (нормализация «0,15»/«0.15», пробелов, «Н·м»/«Н м»).
6. Тесты: фильтр по двигателю (запрос про ЗМЗ на ТС с ЯМЗ не возвращает ЗМЗ), citation_check.
7. Быстрая проверка руками: 10 вопросов (момент затяжки крышек коренных подшипников, тепловой зазор клапанов, давление масла — по каждому двигателю). Выведи страницы, я сверю по PDF.

Приёмка: в БД ~1 500–2 500 чанков по 6 руководствам; 8/10 вопросов находят верную страницу.
Коммит: `rag: ingest 6 manuals, hybrid search, citation check`.
