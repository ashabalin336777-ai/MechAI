# Промпт 3. Восемь инструментов на синтетических данных

Реализуй детерминированный слой tools по сигнатурам TZ.md §6.2. Источники: data/engine_cards.json, ml_responses/, defect_history.json, manuals/chunks.jsonl, mechanic_dialogs.json, defect_requests/.

Требования:
- JSON-схемы инструментов для OpenAI tool calling
- get_ml_diagnosis возвращает объект, валидный по schema v1.1
- search_manuals: BM25/tsvector + pgvector, затем rerank (интерфейс можно мокнуть в тестах)
- get_manual_page по manual_id и page_id вида "12-04"
- draft_defect_request создаёт запись status=draft_awaiting_confirmation, без request_id и без confirmation_token
- confirmation_token создаётся **только** отдельной функцией UI/API «подтвердить черновик», не инструментом и не LLM
- submit_defect_request отказывает без валидного токена, при роли администратор, при несовпадении confirmed_by, при повторном использовании токена (идемпотентный ответ с тем же номером, без второй заявки)
- ни один инструмент не выдумывает page_id и артикулы

Тесты на отказы submit и на то, что цитаты из эталонных черновиков находятся в chunks.jsonl.
Пока не подключай LLM: инструменты должны работать как обычные Python-функции.
