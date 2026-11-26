# MechAI

**MechAI** — AI-агент «Цифровой механик» для диагностики ДВС парка НейроДВС (ЯМЗ-236М2, ЯМЗ-536, ЗМЗ-5234.10, ЗМЗ-40904.10/40905.10).

Проект хакатона «ИИкузница», трек «Цифровой аватар», заказчик ООО «НейроДВС».

Механик выбирает машину и проверку, нажимает «Получить результат диагностики». Агент объясняет вердикт ML, находит этапы работ в руководстве на двигатель этой машины со ссылкой «документ + страница PDF» и по команде механика создаёт заявку в ТОиР.

Все данные в репозитории синтетические, заглушки и парк ТС — из `mock/` (компонент заказчика). Не использовать как реальные данные ремонта.

## Стек

FastAPI, Jinja2, HTMX/Alpine.js (мобильное PWA), LangGraph с чекпоинтами в PostgreSQL, PostgreSQL + pgvector, Timeweb S3, LLM через Neuraldeep API (openai SDK). Деплой: Docker Compose на Timeweb App Platform.

## Статус

Фаза 01: каркас, клиенты Mock ML и Mock ТОиР по OpenAPI, парк ТС из `mock/data/vehicles.json`, `GET /health`, запасной режим `MOUNT_MOCKS=1`. Агента, входа и экран чата пока нет (фазы 04–05).

## Структура

```
app/        FastAPI-приложение: api/ (страницы, /health), clients/ (ML, ТОиР), data/ (парк ТС), config.py
mock/       заглушки заказчика (Mock ML, Mock ТОиР, данные). Код не меняем; mock/Dockerfile наш
data/       руководства (PDF) и manifest; кладутся в образ
eval/       прогон сценариев С1–С3 и вопросов RAG (фазы 03 и 06)
tests/      тесты (pytest): клиенты против заглушек через TestClient
docs/       ТЗ, промпты фаз, макеты (не входят в образ)
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

1. Репозиторий публичный: https://github.com/ashabalin336777-ai/MechAI (ветка `main`).
2. В панели App Platform подключить аккаунт GitHub (не URL), выбрать фреймворк **Docker Compose**, регион РФ.
3. Задать переменные окружения и секреты в панели (см. `.env.example`).
4. Первый сервис в `docker-compose.yml` (`app`, порт `8000`) получает основной домен и HTTPS. Порты 80 и 443 в compose не указывать.
5. Проверить `https://<домен>/health`.

Ограничения compose в App Platform: без `volumes`, `privileged`, `extra_hosts`, `network_mode: host`, `include`, `extends`, `external`, `name`, `driver_opts`.

## Данные и лицензии

- `mock/data/` — синтетика заказчика; копируется в образ при сборке.
- `data/manuals/` — руководства заказчика (5 PDF). `yamz-536_rk_2013.pdf` (99 МБ) в git не кладём: его скачивает ingest с Яндекс Диска заказчика (фаза 03).
- Раздел про заявки и подтверждения: заявка только по команде механика; при «нет инструкции» заявка не создаётся (ТЗ §7.1).

## Лицензия

MIT, см. [LICENSE](LICENSE).
