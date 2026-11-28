# AGENTS.md — MechAI («Цифровой механик»)

Регламент для Cursor Agent. Полное ТЗ: `docs/TZ.md` (редакция 26.11 v2). Промпты фаз: `docs/prompts/00…10`. Модели: `docs/models.md`. Выводы по задаче своими словами: `docs/task_notes.md`. Материалы задачи (заглушки, PDF, документы заказчика) вне репозитория, см. раздел «Данные».

## Сроки
- Спринт идёт: до **28.11 12:00 МСК (16:00 Нск)**. Оценивается последний коммит до этого времени. Наша заморозка — **15:30 Нск**.
- Коммит после каждой фазы, сообщения по делу. История проверяется.

## Приоритеты (строго по порядку)
1. Обязательный минимум **F1–F7** и сценарии **С1–С3** на стенде (без них проект не оценивают).
2. **B1** память, **B2** график, **B3** «Главный механик».
3. Пожелания заказчика: голос (whisper-1), режимы «Новичок»/«Крупный», журнал агента, SaaS/роли, 152-ФЗ.
4. Опция: адаптер датчиков/CAN `get_sensor_telemetry`.
Не начинать пункт ниже, пока выше не работает на стенде.

## Данные
- PDF, данные заглушек и документы заказчика не коммитить. Материалы задачи не публикуем, требование организатора, п. 9.1. В git: `data/manuals/manifest.yaml` без ссылок; `mock/data/` и `docs/customer/` игнорируются, `.gitignore` и `.dockerignore` это задают.
- Ссылки на материалы только из env: `MATERIALS_URL` (общая публичная папка), при необходимости `MANUALS_URL` (PDF) и `MOCK_DATA_URL` (JSON заглушек). Файлы докачиваются при старте (`app/materials.py`), `/health` показывает `materials: ok|missing`.
- Тесты не читают материалы: синтетический fixture в `tests/fixtures/mock_data/`, тесты с настоящими PDF помечены `requires_real_materials` и запускаются с `MECHAI_REAL_MATERIALS=1`.
- ТС и справочник F01–F14: `mock/data/vehicles.json` и `mock/data/fault_types.json` (локально, из `MATERIALS_URL`). Код в `mock/` **не менять** (это компонент заказчика).
- Руководства: `data/manuals/*.pdf` (локально, из `MANUALS_URL` или `MATERIALS_URL`) + `data/manuals/manifest.yaml` (file, sha256, двигатели).
- Старые данные (Cummins ISF 2.8, ГАЗель, S1–S5, схема v1.1, 1С) **не использовать**.

## Контракты (точно по `mock/openapi_ml.json` и `mock/openapi_toir.json`)
- `POST {MOCK_ML_URL}/diagnose` `{vehicle_id, session_id}` → `status normal|anomaly|check_failed`, `anomaly_type F01…F14|null`, `anomaly_title`, `anomaly_score`, `confidence`, `signal_quality good|warning|bad`, `description`, `model_version`.
- `POST {MOCK_TOIR_URL}/tickets` все поля обязательны: `vehicle_id, session_id, anomaly_type, conclusion, urgency low|medium|high, operations[≥1], spare_parts[], references[≥1]{manual, pdf_page≥1}` → 201 `{ticket_id, status:"created"}`.
- URL только из `.env`.

## Стек (не менять без просьбы)
Python 3.12, FastAPI, Jinja2, HTMX, Alpine.js, Pydantic v2, httpx, LangGraph, openai SDK → Neuraldeep `https://api.neuraldeep.ru/v1`, PostgreSQL + pgvector (Timeweb Managed), Docker Compose на Timeweb App Platform. Модели: `AGENT_MODEL=qwen3.8-flash-next-ru-noreason`, `EMBED_MODEL=bge-m3`, `RERANK_MODEL=bge-reranker`, `STT_MODEL=whisper-1`. Нет: Streamlit, React, Qdrant, Redis, Langfuse, Nginx, модели «вне РФ».

## Жёсткие правила агента
- Инструменты отдельные: `get_vehicle`, `get_diagnosis`, `search_manual`, `get_history`, `draft_ticket`, `create_ticket` (+ опц. `get_sensor_telemetry`). Обязательный контекст (ТС, диагноз, история) загружается кодом до первого вызова модели (параллельно); модель выбирает `search_manual` и `draft_ticket`, а не цепочку if-else.
- `search_manual` всегда фильтрует по двигателю ТС (фильтр в коде инструмента).
- Цифры и нормативы — только из найденных фрагментов этого диалога, со ссылкой `[обозначение, стр. N]`. Нет данных → «нет данных в руководстве на <двигатель>» + рекомендация дефектовки.
- `check_failed`/`bad` → без выводов о двигателе, без заявки.
- Заявка: только по команде механика и после подтверждения состава; при «нет инструкции» не отправлять.
- Пороги и приоритет — `docs/TZ.md` §7, основание показывать механику.
- Каждый шаг агента пишется в журнал (`agent_runs`, `agent_steps`): токены, мс, ток/с, ₽.

## Деплой
Compose: первый сервис `app` (порт 8000, получает домен), затем `mock_ml` (8001), `mock_toir` (8002). Запрещено: `volumes`, `privileged`, `extra_hosts`, `network_mode: host`, `include`, `extends`, `external`, `name`, `driver_opts`, хост-порты 80/443. Запасной режим `MOUNT_MOCKS=1`. Стенд работает до 23:59 3.12.

## Секреты
Публичный репозиторий. Ключи, PIN, `JWT_SECRET`, `DATABASE_URL` — только в env / секретах App Platform. В git — `.env.example` без значений.

## Как работать
- Одна фаза = один новый чат, прикреплять `@docs/prompts/NN_*.md` и только нужные файлы.
- После фазы: `pytest -q`, ручная проверка, коммит.
- Юнит-тесты не ходят в настоящий Neuraldeep (мок клиента). `eval/run_scenarios.py` — ходит.
