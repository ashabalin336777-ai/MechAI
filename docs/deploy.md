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
| `STT_LANGUAGE` | `ru` | нет | язык голоса по умолчанию: `ru`, `uz`, `kk`, `tg`, `ky`, `en`; пусто — автоопределение |
| `STT_BROWSER_FALLBACK` | `0` | нет | Web Speech API выключен (152-ФЗ) |
| `MOCK_ML_URL` | `http://mock_ml:8001` | нет | внутренний адрес заглушки ML |
| `MOCK_TOIR_URL` | `http://mock_toir:8002` | нет | внутренний адрес заглушки ТОиР |
| `SENSORS_URL` | пусто | нет | датчики, опция; пусто — инструмент не регистрируется |
| `MOUNT_MOCKS` | `0` | нет | `1` — запасной режим, см. ниже |
| `DATABASE_URL` | `postgresql://mechai:<пароль>@<хост>:<порт>/mechai?sslmode=require` | да | строка из панели БД |
| `VEHICLES_PATH` | `mock/data/vehicles.json` | нет | парк ТС; файл докачивается при старте по `MATERIALS_URL` |
| `FAULT_TYPES_PATH` | `mock/data/fault_types.json` | нет | справочник F01–F14; докачивается при старте |
| `MANUALS_DIR` | `data/manuals` | нет | каталог PDF руководств; PDF докачиваются при ingest |
| `MATERIALS_URL` | публичная ссылка на папку Яндекс Диска с материалами задачи | да (для деплоя) | п. 9.1 требований организатора; без неё `/health` покажет `materials: missing` |
| `MANUALS_URL` | пусто | нет | ссылка на папку с PDF, если они не в `MATERIALS_URL`; пусто — берётся `MATERIALS_URL` |
| `MOCK_DATA_URL` | пусто | нет | ссылка на папку с JSON заглушек; пусто — берётся `MATERIALS_URL` |
| `MOCK_ARCHIVE_NAME` | `neurodvs_hackathon_mock_2026-11-16.zip` | нет | архив в той же папке, из которого берутся `data/vehicles.json` и `data/fault_types.json`, если отдельных файлов в папке нет |
| `CONF_LOW` | `0.60` | нет | порог уверенности (ТЗ §7) |
| `SCORE_HIGH` | `0.80` | нет | порог приоритета high (ТЗ §7.2) |
| `RAG_MIN_SCORE` | `0.80` | нет | минимальный rerank score фрагмента (подобран по прогону eval 26.11, см. `eval/rag_report.md`) |
| `AUTH_MODE` | `demo` | нет | `demo` без входа; `pin` — фаза 09 |
| `JWT_SECRET` | `<openssl rand -hex 32>` | да | для режима `pin`, сгенерировать и хранить только в панели |
| `LOG_RETENTION_DAYS` | `90` | нет | срок хранения журнала агента |
| `GIT_SHA` | `<полный SHA коммита>` | нет | версия в `/health` (поле `git_sha`); пусто — `unknown` |
| `COMMIT_SHA` | `<полный SHA коммита>` | нет | SHA в `eval_runs` и отчётах; задаётся тем же значением, что `GIT_SHA` |

**Материалы до деплоя.** Перед первым деплоем положить ссылку `MATERIALS_URL` в панель Timeweb App Platform (раздел переменных, как секрет или обычное значение). Без неё сервисы стартуют, но парк ТС пуст, а `/health` покажет `materials: missing`. Проверка после деплоя: `https://<домен>/health` содержит `"materials":"ok"`. Заглушки `mock_ml` и `mock_toir` докачивают `vehicles.json` сами (по `MOCK_DATA_URL` или `MATERIALS_URL`); если докачка не удалась, сервис пишет причину в лог и завершает запуск с кодом 1.

**Версия стенда.** Образ собирается из GitHub без build-аргументов, поэтому `GIT_SHA` и `COMMIT_SHA` задаются вручную в панели App Platform после каждого деплоя. Значение: полный хэш коммита, который задеплоен (`git rev-parse HEAD` в локальном репозитории, либо `git log -1` для нужной ветки). Пока переменная пуста, `/health` покажет `unknown`. Проверка: `https://<домен>/health` возвращает `git_sha` с тем же хэшем.

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

Первая индексация на стенде выполнена 26.11.2026: 6 руководств, 1672 чанка, ошибок нет (версия нарезки 1). Отчёт: [eval/ingest_report.md](../eval/ingest_report.md).

27.11.2026 руководства переиндексированы: `chunker_version` 3 у всех шести (проверено SQL по БД стенда). Временный эндпоинт `POST /admin/ingest` удалён из кода на этапе 10, после деплоя релиза его не будет. Повторная индексация локальная: `python -m app.rag.ingest` с `DATABASE_URL`, `NEURALDEEP_API_KEY` и PDF в `MANUALS_DIR` (PDF докачиваются по `MATERIALS_URL`). Чанки `source='ocr'` при индексации не удаляются.
## Проверка поиска и агента (POST /admin/eval)

Админ-прогон проверки, асинхронный. Все три эндпоинта требуют `Authorization: Bearer <ADMIN_TOKEN>`. Без `ADMIN_TOKEN` их нет (404), без верного токена 401.

- `POST /admin/eval?suite=rag|agent` (по умолчанию `rag`): создаёт строку в таблице `eval_runs` и запускает прогон в фоне. Ответ 202: `{"status": "started", "suite": ..., "run_id": N}`. Пока идёт другой прогон, отвечает 409.
- `GET /admin/eval/status` возвращает последний прогон; `GET /admin/eval/status?run_id=N` возвращает прогон N. Поля: `id`, `suite`, `commit_sha`, `status` (`running`, `done`, `error`), `started_at`, `finished_at`, `passed`, `total`, `error_message`, `report_md` (отчёт в Markdown, только метрики без фрагментов и ответов), `report_json` (сводка по кейсам). Полный отчёт с фрагментами и ответами хранится в БД (`report_full_md`) и открывается в `/admin/logs`. Если прогонов ещё не было, 404.
- `GET /admin/eval/runs?limit=10` (от 1 до 100): список последних прогонов без `report_md`.

Прогон идёт на сервере, поэтому обрыв сети у клиента его не останавливает. Итог лежит в Postgres, поэтому после перезапуска или деплоя результат остаётся доступен. Прогон, который висит дольше 30 минут (сервис упал до записи итога), при следующем запуске помечается `error`.

Критерии «пройдено»: для `rag` — hit@5 по странице у вопроса с эталоном, а для вопроса «нет инструкции» — порог отсёк выдачу. Для `agent` — все проверки сценария. `passed` и `total` считаются по этим критериям.

`commit_sha` берётся из переменной `COMMIT_SHA` (задаётся в панели App Platform). Пусто — в таблице NULL.

PowerShell (вместо `<ADMIN_TOKEN>` свой токен, значение в чат не присылать):

```powershell
$h = @{ Authorization = "Bearer <ADMIN_TOKEN>" }
$base = "https://ashabalin336777-ai-mechai-3580.twc1.net/admin/eval"
# запуск агентского прогона: вернёт run_id
$run = Invoke-RestMethod -Method Post -Uri "${base}?suite=agent" -Headers $h
# статус выбранного прогона (без run_id — последний)
$st = Invoke-RestMethod -Uri "${base}/status?run_id=$($run.run_id)" -Headers $h
$st.status; "$($st.passed) из $($st.total)"
# отчёт в Markdown: сохранить в файл
$st.report_md | Set-Content -Encoding UTF8 eval\reports\agent_run_$($run.run_id).md
# список последних прогонов без текста отчёта
(Invoke-RestMethod -Uri "${base}/runs?limit=10" -Headers $h).runs | Format-Table id, suite, status, passed, total, commit_sha
```

Пока `status` равен `running`, повторно опрашивать статус (обычно несколько минут). Когда `status` стал `done`, отчёт в `report_md` (метрики для `eval/*.md`); полный текст — в `/admin/logs`. Если `status` равен `error`, причина в `error_message`: короткий текст без строки подключения и ключей.
## Журнал агента: /admin/logs

Страница только для чтения: ходы агента (`agent_runs`), шаги (`agent_steps`) и прогоны проверки (`eval_runs`).

- Адрес: `https://ashabalin336777-ai-mechai-3580.twc1.net/admin/logs`. Без входа откроется форма: вставьте `ADMIN_TOKEN` и нажмите «Войти». В браузере остаётся cookie на 8 часов, сам токен не сохраняется. Выход: «Выйти из журнала».
- Фильтр ходов: «Все», «Успешные», «С ошибкой», «Идут» (параметр `status=all|ok|error|running`).
- Ход открывается по ссылке времени в строке. Шаги: вызовы инструментов (`tool`), `raw_answer` (ответ модели до правок кодом), `citation_check`, `conflict_notice` (`guardrail`), ошибки и повторы (класс и текст ошибки).
- Вкладка «Прогоны проверки» (`?tab=eval`): набор, итог «passed из total», коммит, ссылка «Открыть отчёт».
- Для скриптов тот же адрес принимает `Authorization: Bearer <ADMIN_TOKEN>`.
- Без `ADMIN_TOKEN` страницы нет (404). Без `DATABASE_URL` на странице написано, что журнал не записывается.

Мобильная проверка страниц (360, 390, 430 px) и скриншоты: `python scripts/mobile_check.py --base <адрес>` с `ADMIN_TOKEN` в окружении. Отчёт: `docs/mobile_design/check/report.md`.

## Что ещё не сделано

- Миграции применяются при старте `app` (`app/db/database.py`). Повторный ingest локально: `python -m app.rag.ingest` (нужны `DATABASE_URL` и `NEURALDEEP_API_KEY`).
- Замер моделей: `eval/bench.md` неполный (26.11 API Neuraldeep не отвечал с рабочей машины). Агент переведён на `qwen3.8-flash-next-ru-noreason` по решению владельца; полный замер нужно повторить до демо (`python -m scripts.bench_models`, ключ из env).
- Переменная `AGENT_MODEL` в панели App Platform должна быть `qwen3.8-flash-next-ru-noreason` (или не задана: по умолчанию в compose та же модель). После смены перезапустить `app`.

