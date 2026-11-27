# MechAI

**MechAI** — AI-агент «Цифровой механик» для диагностики ДВС парка НейроДВС (ЯМЗ-236М2, ЯМЗ-536, ЗМЗ-5234.10, ЗМЗ-40904.10/40905.10). Механик выбирает машину и проверку и нажимает «Получить результат диагностики». Агент объясняет вердикт ML, находит этапы работ в руководстве на двигатель этой машины со ссылкой «документ + страница PDF» и по команде механика создаёт заявку в ТОиР.

Проект хакатона «ИИкузница», трек «Цифровой аватар», заказчик ООО «НейроДВС». Все данные синтетические (заглушки и парк ТС из `mock/`, компонент заказчика). Не использовать как реальные данные ремонта.

**Стенд:** https://ashabalin336777-ai-mechai-3580.twc1.net (проверка версии: `/health`, поле `git_sha`).

## Что готово

- **Агент F1–F7:** LangGraph, инструменты `get_vehicle`, `get_diagnosis`, `search_manual`, `get_history`, `draft_ticket`, `create_ticket`. Заявка уходит только по одноразовому токену, который привязан к показанному черновику.
- **RAG по руководствам:** гибридный поиск (pgvector + полнотекст + реранк), фильтр по двигателю в коде инструмента, порог `RAG_MIN_SCORE` = 0,80. Страницы без текстового слоя распознаёт vision-модель (OCR сканов, около 64 из 72 страниц руководства).
- **Проверка цитат кодом:** каждая цифра с единицей в ответе должна дословно стоять во фрагменте этого хода и иметь ссылку `[обозначение, стр. N]`. Неверная ссылка заменяется кодом, непроверенная фраза убирается.
- **Противоречия руководств:** известные расхождения (`data/known_conflicts.yaml`) показываются механику обеими формулировками со ссылками, без пересказа моделью.
- **Мобильный UI:** вёрстка 360–430 px без горизонтального скролла, цели касания от 48 px. Три режима: «Стандартный», «Новичок», «Крупный». Первая карточка — вердикт «светофор».
- **Журнал и проверки:** `/admin/logs` (только чтение: ходы, шаги, прогоны). Прогоны eval асинхронные: `POST /admin/eval` отвечает 202 и пишет результат в Postgres.

Не сделано: голосовой ввод, PIN-вход и датчики, B1–B3 в полном объёме. Что осталось по этапам, см. [docs/STATUS.md](docs/STATUS.md). История изменений: [CHANGELOG.md](CHANGELOG.md).

## Метрики

| Показатель | Результат |
|---|---|
| Агент, сценарии С1–С3 и контрольные случаи §8.3 | 5 из 5 PASS (прогон 5, `b537b15`). Прогон на `ec99bac` подтверждён, итог в `eval_runs` стенда |
| RAG, набор вопросов | 12 из 14 PASS (прогон 6, `chunker_version` 3). Известные промахи: Q03, N03 |
| Тесты (`pytest`) | 461 проходят на `ec99bac` с тестовой БД (`TEST_DATABASE_URL`, `TEST_DATABASE_ALLOW_RESET=1`). Без них часть DB-тестов пропускается |
| Стоимость прогона агента | около 1,3 ₽ за пять сценариев (прогон 5) |
| Модели | агент `qwen3.8-flash-next-ru-noreason`, эмбеддинги `bge-m3`, реранк `bge-reranker`, OCR `gemma-4-31b-noreason` |

Отчёты прогонов: [eval/agent_report.md](eval/agent_report.md), [eval/rag_report.md](eval/rag_report.md). Сценарии: [eval/agent_scenarios.yaml](eval/agent_scenarios.yaml), вопросы RAG: [eval/questions.yaml](eval/questions.yaml).

## Стек

Python 3.12, FastAPI, Jinja2, HTMX/Alpine.js (мобильный интерфейс), LangGraph с чекпоинтами, PostgreSQL + pgvector, Pydantic v2, httpx. LLM через Neuraldeep API (openai SDK, `https://api.neuraldeep.ru/v1`), серверы в РФ. Деплой: Docker Compose на Timeweb App Platform.

## Структура

```
app/        FastAPI-приложение: api/ (страницы, /health, /ready, /admin/*), clients/ (ML, ТОиР),
            data/ (парк ТС), db/ (БД и миграции), rag/ (поиск, OCR, противоречия), agent/ (агент),
            tools/ (инструменты агента), templates/ и static/ (интерфейс), config.py
mock/       заглушки заказчика (Mock ML, Mock ТОиР, данные). Код не меняем; mock/Dockerfile наш
data/       руководства (manifest.yaml, PDF в образ), known_conflicts.yaml
eval/       сценарии агента, вопросы RAG, отчёты прогонов
scripts/    служебные скрипты: bench_models.py (замер моделей), mobile_check.py (проверка 360–430 px)
tests/      pytest: клиенты против заглушек через TestClient, миграции при TEST_DATABASE_URL
docs/       ТЗ, модели, деплой, промпты фаз, статус проекта
```

## Заглушки заказчика

- `mock/mock_ml` — `POST /diagnose`, `mock/mock_toir` — `POST /tickets`. Контракт: `mock/openapi_ml.json`, `mock/openapi_toir.json`.
- Адреса только из переменных окружения: `MOCK_ML_URL`, `MOCK_TOIR_URL` (см. `.env.example`).
- Если сеть App Platform не резолвит имена сервисов: `MOUNT_MOCKS=1`.

## Переменные окружения

Полный список с пустыми значениями — в `.env.example`. Секреты (ключ Neuraldeep, `JWT_SECRET`, пароль БД, `ADMIN_TOKEN`, PIN) задаются **только** в переменных окружения или в секретах App Platform. В git их не кладём.

## Запуск локально через Docker Compose

Нужны Docker и Docker Compose.

```bash
cp .env.example .env          # заполнить значения локально; файл .env не коммитить
# в .env задать POSTGRES_PASSWORD и ключ Neuraldeep
docker compose -f docker-compose.local.yml up --build
```

Поднимаются четыре контейнера: `app`, `db` (PostgreSQL + pgvector), `mock_ml`, `mock_toir`. Проверка:

```bash
curl http://localhost:8000/health
```

Интерфейс: http://localhost:8000/. Для узкого экрана откройте DevTools и выберите ширину 390 px.

## Запуск без Docker

Нужен Python 3.12.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Без `DATABASE_URL` журнал, заявки и диалоги живут в памяти процесса. Тесты и линтер:

```bash
pytest
ruff check .
```

## Деплой на Timeweb App Platform

Пошаговая инструкция с полями панели и полным списком переменных: [docs/deploy.md](docs/deploy.md).

1. Подключить репозиторий GitHub, выбрать фреймворк **Docker Compose**, регион РФ.
2. Задать переменные окружения и секреты в панели (см. `.env.example`).
3. Первый сервис `app` (порт `8000`) получает домен и HTTPS. Порты 80 и 443 в compose не указывать.
4. Проверить `/health` и `/ready`.

Ограничения compose в App Platform: без `volumes`, `privileged`, `extra_hosts`, `network_mode: host`, `include`, `extends`, `external`, `name`, `driver_opts`.

## Данные и лицензии

- `mock/data/` — синтетика заказчика; копируется в образ при сборке.
- `data/manuals/` — руководства заказчика (5 PDF, 2010–2025). Основание публикации: ответ заказчика в Q&A (вопрос 18, «руководства общедоступные»). Файл `yamz-536_rk_2013.pdf` (99 МБ) в git не кладём: ingest скачивает его с Яндекс Диска заказчика и проверяет sha256 (`app/rag/manuals.py`).
- Заявка в ТОиР создаётся только по команде механика. При «нет инструкции» в руководстве заявка не создаётся.

## Лицензия

MIT, см. [LICENSE](LICENSE).
