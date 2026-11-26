# Промпт 1. Каркас репозитория и деплой-заготовка

Собери минимальный каркас по TZ.md §13–15.

Сделай:
1. pyproject.toml или requirements.txt с закреплёнными версиями: fastapi, uvicorn, jinja2, python-multipart, pydantic, openai, langgraph, langgraph-checkpoint-postgres, asyncpg / psycopg, sqlalchemy или эквивалент, argon2-cffi (или passlib+argon2), pyjwt, httpx, boto3 или aiobotocore, jsonschema, pytest, ruff.
2. Dockerfile (Python 3.12-slim), CMD uvicorn на 0.0.0.0:8000.
3. docker-compose.yml строго по образцу ТЗ: один сервис app, порт 8000:8000, без volumes и прочих запрещённых директив.
4. .env.example с именами переменных из ТЗ §14, без значений-секретов. Полный .gitignore (обязательно .env, ключи, дампы, локальные официальные руководства).
5. LICENSE (MIT) и README: запуск локально (внешняя Postgres), деплой на App Platform из публичного репозитория, проверка GET /health, что секреты только в env.
6. FastAPI-приложение: маршруты GET /health (без авторизации) и GET / (пока простая русская заглушка «Цифровой механик»).
7. Каталоги app/, data/, tests/, eval/ как в ТЗ. В data/ положи копию синтетических данных (если их ещё нет — опиши команду копирования из data, но не выдумывай JSON). Официальные мануалы Cummins при неясной лицензии не коммитить.
8. Репозиторий сразу публичный. Коммиты частые, сообщения по делу. Первый коммит — только после 26.11 14:00 Asia/Novosibirsk.

Не реализуй агента, auth и UI шагов в этой фазе. После генерации покажи, как проверить health локально.
