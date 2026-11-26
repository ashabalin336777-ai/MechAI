# MechAI

**MechAI** — AI-агент «Цифровой механик» для диагностики ДВС парка НейроДВС (ЯМЗ-236М2, ЯМЗ-536, ЗМЗ-5234.10, ЗМЗ-40904.10/40905.10).

Проект хакатона «ИИкузница», трек «Цифровой аватар», заказчик ООО «НейроДВС».

Механик выбирает машину и проверку, нажимает «Получить результат диагностики». Агент объясняет вердикт ML, находит этапы работ в руководстве на двигатель этой машины со ссылкой «документ + страница PDF» и по команде механика создаёт заявку в ТОиР.

Все данные в репозитории синтетические, заглушки и парк ТС — из `mock/` (компонент заказчика). Не использовать как реальные данные ремонта.

## Стек

FastAPI, Jinja2, HTMX/Alpine.js (мобильное PWA), LangGraph с чекпоинтами в PostgreSQL, PostgreSQL + pgvector, Timeweb S3, LLM через Neuraldeep API (openai SDK). Деплой: Docker Compose на Timeweb App Platform.

## Статус

Готово в коде (`pytest`: 328 тестов проходят, 10 пропускаются без `TEST_DATABASE_URL`):
- **Фазы 01–02:** каркас, клиенты Mock ML и Mock ТОиР по OpenAPI, парк ТС из `mock/data/vehicles.json`, `GET /health` и `GET /ready`, PostgreSQL с миграциями (pgvector), запасной режим `MOUNT_MOCKS=1`. Развёрнуто на Timeweb App Platform.
- **Фаза 03:** ингест руководств, гибридный поиск (pgvector + полнотекст + реранк) с порогом `RAG_MIN_SCORE`, фильтр по двигателю в SQL, известные противоречия руководств (`data/known_conflicts.yaml`).
- **Фаза 04:** агент LangGraph и инструменты `get_vehicle`, `get_diagnosis`, `search_manual`, `get_history`, `draft_ticket`, `create_ticket` (отправка только по одноразовому токену), журнал ходов `agent_runs` / `agent_steps` с шагами `error` и `retry` (класс и текст ошибки без секретов). Таймаут вызова модели не меньше 15 с, один повтор при 5xx, таймауте и обрыве (`97cb0f7`).
- **Фаза 05 (черновик):** мобильный чат, карточка вердикта, экран заявки, дашборд, режимы «Стандартный» / «Новичок» / «Крупный».

Не подтверждено на стенде: агент и поиск зависят от Neuraldeep (с рабочей машины API недоступен). Последний прогон агента на стенде 27.11, 03:59 — 2 из 4 сценариев (C3 и M260EH47), отчёт в [eval/agent_report.md](eval/agent_report.md). Фикс X01 (таймаут, журнал ошибок) ждёт проверки на стенде; регресс по сессии S-0083 добавлен в [eval/agent_scenarios.yaml](eval/agent_scenarios.yaml). Подробности и решения: [docs/STATUS.md](docs/STATUS.md).

## Модели

- Агент (tool loop и стрим ответа): `qwen3.8-flash-next-ru-noreason` (Neuraldeep, в РФ, tools, без reasoning).
- Эмбеддинги `bge-m3`, реранк `bge-reranker`, голос `whisper-1`.
- `qwen3.6-fp8` не используем для агента: reasoning по умолчанию, выключается только через `-noreason`-версию без tools.
- Замер скорости 26.11 неполный (API с рабочей машины не отвечал по TLS). Предварительно медиана 38 ток/с по 2 успешным запросам. Полный замер (`python -m scripts.bench_models`) — перед демо. Детали: [docs/models.md](docs/models.md), [eval/bench.md](eval/bench.md).

## Структура

```
app/        FastAPI-приложение: api/ (страницы, /health, /ready), clients/ (ML, ТОиР), data/ (парк ТС), db/ (БД и миграции), config.py
mock/       заглушки заказчика (Mock ML, Mock ТОиР, данные). Код не меняем; mock/Dockerfile наш
data/manuals/  руководства (PDF); в образ копируются. manifest.yaml — реестр руководств (ТЗ §3.2)
scripts/    служебные скрипты (замер моделей `bench_models.py`)
eval/       прогон сценариев С1–С3 и вопросов RAG (фазы 03 и 06), замер моделей `bench.md`
tests/      тесты (pytest): клиенты против заглушек через TestClient, миграции при TEST_DATABASE_URL
docs/       ТЗ, модели, деплой, промпты фаз, макеты (не входят в образ)
```

## Заглушки заказчика

- `mock/mock_ml` — `POST /diagnose`, `mock/mock_toir` — `POST /tickets`. Контракт: `mock/openapi_ml.json`, `mock/openapi_toir.json`.
- Адреса только из переменных окружения: `MOCK_ML_URL`, `MOCK_TOIR_URL` (см. `.env.example`).
- Запуск вне compose: `uvicorn mock_ml.app:app --port 8001` и `uvicorn mock_toir.app:app --port 8002`, затем `MOCK_ML_URL=http://127.0.0.1:8001 MOCK_TOIR_URL=http://127.0.0.1:8002 uvicorn app.main:app`.
- Если сеть App Platform не резолвит имена сервисов: `MOUNT_MOCKS=1`, `MOCK_ML_URL=http://127.0.0.1:8000/mock/ml`, `MOCK_TOIR_URL=http://127.0.0.1:8000/mock/toir`.

## Переменные окружения

Полный список с пустыми значениями — в `.env.example`. Секреты (ключ Neuraldeep, `JWT_SECRET`, пароль БД, PIN, ключи S3) задаются **только** в переменных окружения или в секретах App Platform. В git их не кладём.

## Запуск локально

Нужен Python 3.12.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Проверка:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Открыть в браузере: http://localhost:8000/ (заглушка на русском). Для узкого экрана откройте DevTools и выберите ширину 390 px.

Тесты и линтер:

```bash
pytest
ruff check .
```

Внешняя PostgreSQL (с pgvector) понадобится с фазы 02. Строку подключения укажите в `DATABASE_URL` в локальном `.env`.

## Запуск через Docker Compose

```bash
cp .env.example .env              # заполнить значения локально, файл не коммитить
docker compose up --build
curl http://localhost:8000/health
```

Локально с PostgreSQL + pgvector (четыре контейнера: app, db, mock_ml, mock_toir):

```bash
# в .env задать POSTGRES_PASSWORD
docker compose -f docker-compose.local.yml up --build
```

`/health` возвращает `ok`, если заглушки отвечают, и `degraded` (код 200), если нет. Проверка БД появится в фазе 02.

## Деплой на Timeweb App Platform

Пошаговая инструкция с полями панели и полным списком переменных: [docs/deploy.md](docs/deploy.md). Секреты в репозиторий не кладём.

1. Репозиторий публичный: https://github.com/ashabalin336777-ai/MechAI (ветка `main`).
2. В панели App Platform подключить аккаунт GitHub (не URL), выбрать фреймворк **Docker Compose**, регион РФ.
3. Задать переменные окружения и секреты в панели (см. `.env.example`).
4. Первый сервис в `docker-compose.yml` (`app`, порт `8000`) получает основной домен и HTTPS. Порты 80 и 443 в compose не указывать.
5. Проверить `https://<домен>/health` и `https://<домен>/ready`. `/ready` отвечает 200 и без БД (`database: not_configured`), при сбое БД — 503.

Ограничения compose в App Platform: без `volumes`, `privileged`, `extra_hosts`, `network_mode: host`, `include`, `extends`, `external`, `name`, `driver_opts`.

## Данные и лицензии

- `mock/data/` — синтетика заказчика; копируется в образ при сборке.
- `data/manuals/` — руководства заказчика (5 PDF, 2010–2025). Основание публикации: ответ заказчика в Q&A (вопрос 18, «руководства общедоступные»). Файл `yamz-536_rk_2013.pdf` (99 МБ) в git не кладём: его скачивает ingest с Яндекс Диска заказчика и проверяет sha256 (`app/rag/manuals.py`). Отдельного скрипта `scripts/fetch_manuals.py` в репозитории нет.
- Заявка в ТОиР — только по команде механика; при «нет инструкции» заявка не создаётся (ТЗ §7.1).

## Лицензия

MIT, см. [LICENSE](LICENSE).
