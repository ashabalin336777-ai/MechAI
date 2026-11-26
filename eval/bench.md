# Замер моделей Neuraldeep

Дата: 2026-11-26 19:47 (локальное время замера). Эндпоинт: `api.neuraldeep.ru`. Запросов на модель: 10, max_tokens: 400, стрим с `include_usage`.

Цель ТЗ: скорость агента > 20 ток/с (p10), TTFT ≈ 1 с. Запрос к инструменту: `get_vehicle` с госномером `T792HO98`, ожидаем аргумент `vehicle_id`.

| Модель | Роль | Успешно | TTFT, мс (медиана) | TTFT контента, мс (медиана) | Ток/с (медиана) | Ток/с (p10) | Ток/с (среднее) | Reasoning | Usage точный | Tool calling |
|---|---|---|---|---|---|---|---|---|---|---|
| `qwen3.6-fp8` | основной кандидат агента (reasoning по умолчанию) | 0/10 | — | — | — | — | — | нет | 0/0 | ошибка: ConnectError |
| `qwen3.8-flash-next-ru-noreason` | запасной кандидат агента (tools, без reasoning) | 2/10 | 2763 | 2763 | 38.1 | 30.2 | 38.1 | нет | 2/2 | ошибка: ConnectError |
| `qwen3.6-35b-a3b` | вторая запасная (reasoning) | 0/10 | — | — | — | — | — | нет | 0/0 | ошибка: ConnectError |
| `qwen3.6-fp8-noreason` | справка: скорость без reasoning, tools нет по каталогу | 0/10 | — | — | — | — | — | нет | 0/0 | ошибка: ConnectError |

## Ошибки

- `qwen3.6-fp8`: ConnectError; tool: ConnectError
- `qwen3.8-flash-next-ru-noreason`: ConnectError; ReadTimeout; tool: ConnectError
- `qwen3.6-35b-a3b`: ConnectError; tool: ConnectError
- `qwen3.6-fp8-noreason`: ConnectError; tool: ConnectError

Измерения приблизительные, если в колонке «Usage точный» меньше числа успешных запросов: тогда токены посчитаны по дельтам стрима.
