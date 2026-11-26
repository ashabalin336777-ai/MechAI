# 01 · Каркас + заглушки заказчика (≈ 1 ч) — F1, F2 (основа), F6

Сделай:
1. Каркас по `docs/TZ.md` §19: `app/main.py` (FastAPI, Jinja2, статика), `app/config.py` (pydantic-settings, все переменные §15), `requirements.txt` с пинами, `Dockerfile` (python:3.12-slim, COPY app, mock/data, data/manuals; uvicorn 0.0.0.0:8000), `.env.example` (§15, без секретов), `LICENSE` MIT, дополнить `.gitignore` (`.env`, `__pycache__`, `.venv`, `data/manuals/yamz-536_rk_2013.pdf`). README и `.gitignore` не затирать — дописать.
2. `mock/` уже лежит в репо (заглушки заказчика, не менять). Добавь только `mock/Dockerfile` (python:3.12-slim, `pip install -r requirements.txt`, `COPY . .`).
3. `docker-compose.yml` по §16 (app первым, mock_ml 8001, mock_toir 8002; без запрещённых директив) и `docker-compose.local.yml` (то же + `pgvector/pgvector:pg16` только для локального запуска).
4. `app/clients/ml_client.py`, `app/clients/toir_client.py`: httpx, pydantic-модели **точно** по `mock/openapi_ml.json` и `mock/openapi_toir.json`, таймаут 5 с, 1 ретрай на сетевую ошибку, типизированные ошибки `NotFound`, `ValidationFailed`, `Unavailable`.
5. `app/data/vehicles.py`: загрузка `VEHICLES_PATH`, поиск по госномеру/гаражному номеру, история проверок, нормализация `model=null` → «МАЗ».
6. `MOUNT_MOCKS=1`: монтировать `mock_ml.app:app` в `/mock/ml` и `mock_toir.app:app` в `/mock/toir` внутри app (запасной режим для App Platform).
7. `GET /health`: статус app, mock_ml, mock_toir, БД (если задана).
8. Тесты: клиенты против заглушек через `TestClient` (200, 404, 422), загрузка 50 ТС.

Приёмка: `docker compose -f docker-compose.local.yml up --build` поднимает 4 контейнера, `/health` зелёный, `pytest -q` проходит.
Коммит: `chore: scaffold, customer mocks, ML/TOiR clients`.
