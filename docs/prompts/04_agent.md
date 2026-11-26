# Промпт 4. Граф LangGraph, HITL и две модели Neuraldeep

Собери оркестратор по TZ.md §6.

Узлы: intake, collect_context, retrieve, hypothesize, ask, draft, await_confirm, submit, respond.
Checkpointer — Postgres. Interrupt на ask и await_confirm.

Политика моделей:
- цикл выбора инструментов — FAST_MODEL (qwen3.6-fp8), tool_choice=auto
- hypothesize и текст черновика — REASONING_MODEL (qwen3.8-27b)
- не вызывай 27b на каждый tool-call
- ключ только из env, base_url https://api.neuraldeep.ru/v1

Guardrails из ТЗ §6.3: нет диагноза без get_ml_diagnosis (кроме ветки S4 requires_rerecord); гипотеза без цитаты запрещена; submit только из узла submit после HITL; лимит 8/10 шагов.

Каждый прогон пишет trace в Postgres: узлы, инструменты, токены, оценка ₽ по тарифам из env или константам кошелька.

Для локальных тестов графа мокай LLM, но прогони «сухой» сценарий S1 и S4 на реальных заглушках инструментов (без сети Neuraldeep).
