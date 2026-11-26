# 02 · Ранний деплой + замер моделей (≈ 1 ч 15 мин)

1. Проверь compose на запрещённые директивы (§16). Подготовь README-раздел «Деплой на Timeweb App Platform» (шаги из §16, без секретов).
2. Миграции (SQL-файлы или Alembic) по §4.1: `tenants`, `users`, `manuals`, `chunks` (vector(1024), tsvector, индексы ivfflat/hnsw + GIN), `diagnoses`, `tickets`, `recommendations`, `agent_runs`, `agent_steps`. Запуск при старте app. Сид: арендатор `demo`.
3. `scripts/bench_models.py`: для `qwen3.6-fp8`, `qwen3.8-flash-next-ru-noreason`, `qwen3.6-35b-a3b` по 10 стрим-запросов (~300 токенов ответа, русский текст про ремонт ДВС, плюс 1 запрос с tool call). Меряет TTFT, ток/с (completion_tokens / (t_end − t_first_token)), ошибки tools. Пишет `eval/bench.md`. Ключ из env. Проверь, как у `qwen3.6-fp8` выключается reasoning (см. https://neuraldeep.ru/docs/chat.md), и зафиксируй в `docs/models.md`.
4. Я сам: создаю App Platform (Docker Compose, регион РФ, переменные) и Managed PostgreSQL с `vector`, `pg_trgm`. Ты дай мне чек-лист из 8 пунктов, что нажать.

Приёмка: стенд по HTTPS отвечает `/health`, заглушки доступны из app (если нет — включаем `MOUNT_MOCKS=1`), `eval/bench.md` с цифрами ток/с.
Коммит: `deploy: app platform compose, migrations, model bench`.
