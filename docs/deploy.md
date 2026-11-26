# Деплой стенда на Timeweb App Platform

Инструкция для ручных действий в панели Timeweb. Секреты сюда не вписываются: в примерах только заглушки вида `<...>`. Реальные значения вводятся в панели.

## Что уже проверено локально

- `docker compose -f docker-compose.yml up` без БД: `/ready` → `200 {"status":"ready","database":"not_configured"}`, `/health` → `ok`, заглушки ML и ТОиР отвечают.
- `docker compose -f docker-compose.local.yml up` с PostgreSQL + pgvector: миграция `0001_init.sql` применена, демо-арендатор `demo` создан, `/ready` → `200 ok`.
- Тесты: `pytest -q`, в том числе проверка `docker-compose.yml` на запреты App Platform (`tests/test_compose.py`).

## Чек-лист из 8 пунктов

1. Запушить `main` в публичный репозиторий `https://github.com/ashabalin336777-ai/MechAI`. App Platform собирает образ из GitHub, локальные коммиты не видит.
2. Создать **Managed PostgreSQL 16** в регионе РФ, в той же сети, что и App Platform. Создать пользователя и базу `mechai`.
3. Включить расширения `vector` и `pg_trgm` до первого запуска приложения: в панели БД (раздел расширений) или под администратором SQL `CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;`. Миграция сама их создаёт, но без прав это упадёт.
4. Скопировать строку подключения с SSL и вписать её в `DATABASE_URL` (см. таблицу переменных ниже).
5. Создать приложение: тип **Docker Compose**, источник **GitHub**, репозиторий `ashabalin336777-ai/MechAI`, ветка `main`, файл `docker-compose.yml`, регион РФ.
6. Ввести переменные окружения и секреты (таблица ниже). Секреты помечать как секретные.
7. Первым сервисом остаётся `app` (порт 8000): ему назначается домен и HTTPS. `mock_ml` и `mock_toir` внутренние, отдельного домена им не нужно.
8. Запустить деплой и проверить `https://<домен>/health` и `https://<домен>/ready`.

> Названия экранов в панели могут отличаться от описанных. Ориентируйтесь на смысл: тип Docker Compose, регион, переменные окружения, домен первого сервиса.

## Managed PostgreSQL: поля

| Поле | Значение |
|---|---|
| Версия | PostgreSQL 16 |
| Регион | РФ, тот же, что у App Platform |
| Сеть | приватная, та же, что у приложения (если выбор есть) |
| Имя базы | `mechai` |
| Пользователь | `mechai` (пароль генерирует панель или задаёте сами, сохраните его) |
| Расширения | `vector`, `pg_trgm` |

Строка подключения (пример, значения заменить):

```
postgresql://mechai:<пароль>@<хост-из-панели>:<порт>/mechai?sslmode=require
```

`sslmode=require` обязателен: БД в облаке, соединение шифруется.

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
| `AGENT_MODEL` | `qwen3.6-fp8` | нет | модель агента |
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
| `RAG_MIN_SCORE` | `0.35` | нет | минимальный score фрагмента |
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

## Запасной режим: заглушки внутри app

Если `mock_ml` или `mock_toir` не резолвятся по имени внутри сети App Platform:

```
MOUNT_MOCKS=1
MOCK_ML_URL=http://127.0.0.1:8000/mock/ml
MOCK_TOIR_URL=http://127.0.0.1:8000/mock/toir
```

Контракт заглушек тот же, код не меняется. Проверка: `https://<домен>/mock/ml/health`.

## Что ещё не сделано

- Миграции применяются при старте `app` (`app/db/database.py`). Ingest руководств (`python -m app.rag.ingest`) появится в фазе 03.
- Замер моделей `scripts/bench_models.py` и `eval/bench.md` (фаза 02, пункт 3): нужен ключ Neuraldeep, он ещё не передан.
- Фаза 02 считается закрытой, когда по HTTPS отвечает `/ready`, заглушки доступны из `app`, `eval/bench.md` заполнен.
