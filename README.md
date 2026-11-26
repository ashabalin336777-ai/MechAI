# MechAI

**MechAI** — AI-агент «Цифровой механик» для диагностики ДВС коммерческого транспорта (ГАЗель Next, Cummins ISF 2.8).

Проект хакатона «ИИКузница» (Софтлайн), трек «Цифровой аватар».

Мастер СТО описывает симптомы, коды ошибок и звук двигателя, а агент предлагает гипотезы неисправностей, шаги проверки по мануалам и черновик заявки на ремонт.

Все данные в репозитории синтетические (см. `data/README.md`). Не использовать как реальные данные ремонта.

## Стек

FastAPI, Jinja2, HTMX/Alpine.js (мобильное PWA), LangGraph с чекпоинтами в PostgreSQL, PostgreSQL + pgvector, Timeweb S3, LLM через Neuraldeep API (openai SDK). Деплой: Docker Compose на Timeweb App Platform.

## Статус

Фаза 1: каркас репозитория, `GET /health`, заглушка главной страницы. Агента, входа и UI шагов пока нет.

## Структура

```
app/        FastAPI-приложение (пока только main.py)
data/       синтетические данные (копия agent_data), кладутся в образ
eval/       прогон золотых сценариев S1–S5 (появится в фазе 06)
tests/      тесты (pytest)
docs/       ТЗ, промпты фаз, макеты (не входят в образ)
```

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

## Деплой на Timeweb App Platform

1. Репозиторий публичный: https://github.com/ashabalin336777-ai/MechAI (ветка `main`).
2. В панели App Platform подключить аккаунт GitHub (не URL), выбрать фреймворк **Docker Compose**, регион РФ.
3. Задать переменные окружения и секреты в панели (см. `.env.example`).
4. Первый сервис в `docker-compose.yml` (`app`, порт `8000`) получает основной домен и HTTPS. Порты 80 и 443 в compose не указывать.
5. Проверить `https://<домен>/health`.

Ограничения compose в App Platform: без `volumes`, `privileged`, `extra_hosts`, `network_mode: host`, `include`, `extends`, `external`, `name`, `driver_opts`.

## Данные и лицензии

- `data/` — синтетика; копируется в образ при сборке.
- Официальные руководства Cummins в репозиторий **не коммитятся** (`data/manuals/official/` в `.gitignore`). Ingest — из S3 или скриптом.

## Лицензия

MIT, см. [LICENSE](LICENSE).
