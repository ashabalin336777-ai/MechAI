# Деплой стенда на Timeweb App Platform

Инструкция для ручных действий в панели Timeweb. Секреты сюда не вписываются: в примерах только заглушки вида `<...>`. Реальные значения вводятся в панели.

## Статус стенда

Стенд на App Platform работает: `https://ashabalin336777-ai-mechai-3580.twc1.net`. `/health` → `ok` (заглушки ML и ТОиР доступны, БД `ok`), `/ready` → `{"status":"ready","database":"ok"}`. Миграция `0001_init.sql` применена.

## Что уже проверено локально

- `docker compose -f docker-compose.yml up` без БД: `/ready` → `200 {"status":"ready","database":"not_configured"}`, `/health` → `ok`, заглушки ML и ТОиР отвечают.
- `docker compose -f docker-compose.local.yml up` с PostgreSQL + pgvector: миграция `0001_init.sql` применена, демо-арендатор `demo` создан, `/ready` → `200 ok`.
- Тесты: `pytest -q`, в том числе проверка `docker-compose.yml` на запреты App Platform (`tests/test_compose.py`).

## Чек-лист из 8 пунктов

1. Запушить `main` в публичный репозиторий `https://github.com/ashabalin336777-ai/MechAI`. App Platform собирает образ из GitHub, локальные коммиты не видит.
2. Создать **Managed PostgreSQL 16** в регионе РФ, в той же сети, что и App Platform. Создать пользователя и базу `mechai`.
3. Включить расширения `vector` и `pg_trgm` до первого запуска приложения: в панели БД (раздел расширений) или под администратором SQL `CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;`. Миграция сама их создаёт, но без прав падает с `InsufficientPrivilege`.
4. Скопировать строку подключения с SSL и вписать её в `DATABASE_URL` (см. таблицу переменных ниже).
5. Создать приложение: тип **Docker Compose**, источник **GitHub**, репозиторий `ashabalin336777-ai/MechAI`, ветка `main`, файл `docker-compose.yml`, регион РФ.
6. Ввести переменные окружения и секреты (таблица ниже). Секреты помечать как секретные.
7. Первым сервисом остаётся `app` (порт 8000): ему назначается домен и HTTPS. `mock_ml` и `mock_toir` внутренние, отдельного домена им не нужно.
8. Запустить деплой и проверить `https://<домен>/health` и `https://<домен>/ready`.

> Названия экранов в панели могут отличаться от описанных. Ориентируйтесь на смысл: тип Docker Compose, регион, переменные окружения, домен первого сервиса.

## Managed PostgreSQL: поля

| Поле | Значение |
|---|---|
| Версия | PostgreSQL 18 (проверено на стенде; миграции с pgvector на ней работают) |
| Регион | РФ, тот же, что у App Platform |
| Сеть | приватная, та же, что у приложения (если выбор есть); на стенде подключаемся по доменному имени |
| Имя базы | `default_db` (как создала панель; любое имя подходит, в `DATABASE_URL` указывайте своё) |
| Пользователь | `gen_user` (или свой, с правами на базу) |
| Расширения | `vector`, `pg_trgm`: включает администратор или панель. Без прав пользователь получает `InsufficientPrivilege` |

Строка подключения (пример, значения заменить):

```
postgresql://gen_user:<пароль>@<хост-из-панели>:5432/default_db?sslmode=require
```

`sslmode=require` обязателен: БД в облаке, соединение шифруется.

**Пароль в строке подключения.** Если в пароле есть символы `@ : / ? # & %`, их нужно экранировать (`@`→`%40`, `:`→`%3A`, `/`→`%2F`, `?`→`%3F`, `#`→`%23`, `&`→`%26`, `%`→`%25`). Проще задать пароль только из латинских букв и цифр. Проверка на своей машине без отправки пароля в чат:

```
python -c "import urllib.parse; print(urllib.parse.quote(input('пароль: '), safe=''))"
```

## App Platform: поля

| Поле | Значение |
|---|---|
| Тип | Docker Compose |
| Источник | GitHub, `ashabalin336777-ai/MechAI`, ветка `main` |
| Файл | `docker-compose.yml` |
| Регион | РФ |
| Домен | назначается первому сервису `app`, порт `8000` |
| Порты 80 и 443 | не указывать (запрещено) |

## Переменные окружения

Все переменные, которые читает приложение (`app/config.py`). Значения-примеры не являются реальными.

| Переменная | Пример | Секрет | Комментарий |
|---|---|---|---|
| `NEURALDEEP_API_KEY` | `<ключ из кабинета Neuraldeep>` | да | ключ моделей, в git не класть |
| `NEURALDEEP_BASE_URL` | `https://api.neuraldeep.ru/v1` | нет | |
| `AGENT_MODEL` | `qwen3.8-flash-next-ru-noreason` | нет | модель агента |
| `AGENT_FALLBACK_MODEL` | `qwen3.8-flash-next-ru-noreason` | нет | запасная модель |
| `EMBED_MODEL` | `bge-m3` | нет | эмбеддинги, 1024 измерения |
| `RERANK_MODEL` | `bge-reranker` | нет | реранк |
| `STT_MODEL` | `whisper-1` | нет | распознавание голоса (фаза 08) |
| `STT_BROWSER_FALLBACK` | `0` | нет | Web Speech API выключен (152-ФЗ) |
| `MOCK_ML_URL` | `http://mock_ml:8001` | нет | внутренний адрес заглушки ML |
| `MOCK_TOIR_URL` | `http://mock_toir:8002` | нет | внутренний адрес заглушки ТОиР |
| `SENSORS_URL` | пусто | нет | датчики, опция; пусто — инструмент не регистрируется |
| `MOUNT_MOCKS` | `0` | нет | `1` — запасной режим, см. ниже |
| `DATABASE_URL` | `postgresql://mechai:<пароль>@<хост>:<порт>/mechai?sslmode=require` | да | строка из панели БД |
| `VEHICLES_PATH` | `mock/data/vehicles.json` | нет | парк ТС, в образе |
| `FAULT_TYPES_PATH` | `mock/data/fault_types.json` | нет | справочник F01–F14 |
| `MANUALS_DIR` | `data/manuals` | нет | руководства в образе |
| `MANUALS_YADISK_URL` | `https://disk.yandex.ru/d/QdAA8p4m0ySe8Q` | нет | для ingest 536 РК (фаза 03) |
| `CONF_LOW` | `0.60` | нет | порог уверенности (ТЗ §7) |
| `SCORE_HIGH` | `0.80` | нет | порог приоритета high (ТЗ §7.2) |
| `RAG_MIN_SCORE` | `0.80` | нет | минимальный rerank score фрагмента (подобран по прогону eval 26.11, см. `eval/rag_report.md`) |
| `AUTH_MODE` | `demo` | нет | `demo` без входа; `pin` — фаза 09 |
| `JWT_SECRET` | `<openssl rand -hex 32>` | да | для режима `pin`, сгенерировать и хранить только в панели |
| `LOG_RETENTION_DAYS` | `90` | нет | срок хранения журнала агента |

Пока не используется на стенде: `POSTGRES_PASSWORD` (только для локального `docker-compose.local.yml`).

Как сгенерировать `JWT_SECRET` на своей машине (не в репозитории):

```
python -c "import secrets; print(secrets.token_hex(32))"
```

## После деплоя: проверка

1. `https://<домен>/health` → `"status":"ok"`, у всех сервисов `ok`. Если `mock_ml` или `mock_toir` `unavailable`, см. запасной режим.
2. `https://<домен>/ready` → `200 {"status":"ready","database":"ok"}`. Если `database` = `not_configured`, при заданном `DATABASE_URL` переменная не дошла до контейнера: проверьте имя и секретность. Если `unavailable`, проверьте строку подключения, `sslmode=require` и сеть БД. Если `migration_failed`, смотрите логи приложения: миграция не применилась (обычно нет прав на расширения).
3. Открыть главную `https://<домен>/` с телефона по HTTPS.

## Диагностика: что значит статус в /ready и строка в логах

Приложение пишет в лог `app` строку вида `БД недоступна: <класс ошибки>: <текст>` (пароль и строка подключения вырезаются). Что означает каждая:

| В логе | Причина | Что сделать |
|---|---|---|
| `ProgrammingError: invalid percent-encoded token` | в пароле `%` без экранирования | экранировать пароль или задать буквенно-цифровой |
| `ProgrammingError: invalid connection option` | схема `postgresql+psycopg://` или лишний параметр в строке | схема должна быть `postgresql://`, параметры только `sslmode=require` |
| `OperationalError: password authentication failed` | пароль не совпадает | сбросить пароль в панели (раздел «Пользователи») и обновить `DATABASE_URL` |
| `OperationalError` / `ConnectionTimeout` | сеть или хост | проверить статус кластера, хост и порт |
| `миграция не применена: InsufficientPrivilege` | нет прав на расширение `vector` | включить `vector` и `pg_trgm` (панель или поддержка Timeweb) |

После исправления переменной или расширения перезапустите сервис `app` и проверьте `/ready`. Ожидаемый ответ: `{"status":"ready","database":"ok"}`.

Статусы `/ready`: `not_configured` (`DATABASE_URL` пуст, стенд готов без БД), `ok`, `unavailable` (БД недоступна, код 503), `migration_failed` (БД отвечает, миграция не применилась, код 503).

## Запасной режим: заглушки внутри app

Если `mock_ml` или `mock_toir` не резолвятся по имени внутри сети App Platform:

```
MOUNT_MOCKS=1
MOCK_ML_URL=http://127.0.0.1:8000/mock/ml
MOCK_TOIR_URL=http://127.0.0.1:8000/mock/toir
```

Контракт заглушек тот же, код не меняется. Проверка: `https://<домен>/mock/ml/health`.

## Индексация руководств

Выполнена на стенде 26.11.2026: 6 руководств, 1672 чанка, ошибок нет. Отчёт: [eval/ingest_report.md](../eval/ingest_report.md). Временный эндпоинт `/admin/ingest` удалён. Переменную `INGEST_TOKEN` в панели App Platform можно удалить.

## Проверка поиска по руководствам (POST /admin/eval)

Постоянный админ-эндпоинт: `POST /admin/eval` с заголовком `Authorization: Bearer <ADMIN_TOKEN>`. Без `ADMIN_TOKEN` эндпоинта нет (404). Прогоняет `eval/questions.yaml` и возвращает отчёт в Markdown (поле `report`): вопрос, двигатель, топ-5 фрагментов с руководством и страницей PDF. Отчёт сохраняется в `eval/rag_report.md`. В фазе 06 этот же эндпоинт расширится сценариями С1–С3.

PowerShell (вместо `<ADMIN_TOKEN>` свой токен, значение в чат не присылать):
`(Invoke-RestMethod -Method Post -Uri https://ashabalin336777-ai-mechai-3580.twc1.net/admin/eval -Headers @{ Authorization = "Bearer <ADMIN_TOKEN>" }).report`

## Что ещё не сделано

- Миграции применяются при старте `app` (`app/db/database.py`). Повторный ingest локально: `python -m app.rag.ingest` (нужны `DATABASE_URL` и `NEURALDEEP_API_KEY`).
- Замер моделей: `eval/bench.md` неполный (26.11 API Neuraldeep не отвечал с рабочей машины). Агент переведён на `qwen3.8-flash-next-ru-noreason` по решению владельца; полный замер нужно повторить до демо (`python -m scripts.bench_models`, ключ из env).
- Переменная `AGENT_MODEL` в панели App Platform должна быть `qwen3.8-flash-next-ru-noreason` (или не задана: по умолчанию в compose та же модель). После смены перезапустить `app`.
