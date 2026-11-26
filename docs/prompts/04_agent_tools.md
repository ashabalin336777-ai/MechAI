# 04 · Агент и инструменты (≈ 3,5 ч) — F2, F3, F4, F5, F7

1. `app/tools/`: `get_vehicle.py`, `get_diagnosis.py`, `search_manual.py`, `get_history.py` (пока: проверки до выбранной + наши заявки), `draft_ticket.py`, `create_ticket.py` — сигнатуры и правила `docs/TZ.md` §6.2. Описания инструментов (docstring) — чёткие, по-русски, это и есть «политика» выбора.
2. `get_diagnosis` считает `verdict`, `confidence_level`, `urgency_suggestion`, `reasons[]` по §7 (пороги из env) и пишет `diagnoses`; в `reasons` подсказка о несоответствии типа топливу (F12/F13 у дизеля, F08 у бензина).
3. `app/agent/graph.py`: LangGraph ReAct на `AGENT_MODEL`, стрим токенов, checkpointer Postgres, лимит 8 инструментов/ход, таймаут 45 с, автопереключение на `AGENT_FALLBACK_MODEL` при ошибке. Системный промпт `app/agent/prompts/system_ru.md` по §6.3 (включая `lang` и `ui_mode`).
4. Guardrails §6.4: `citation_check` (1 перегенерация, затем пометка «не подтверждено руководством»), `engine_guard`, `ticket_guard`. Подтверждение заявки: `draft_ticket` возвращает `draft_id` + хэш состава; UI получает одноразовый `confirm_token`; `create_ticket` отправляет в ТОиР, пишет `tickets`.
5. «Нет инструкции»: если `search_manual` по узлу пуст — агент говорит это, рекомендует дефектовку, пишет `recommendations`, заявку не предлагает.
6. Журнал (минимум сейчас): `agent_runs`/`agent_steps` — каждый LLM-вызов (модель, ttft_ms, токены, tok_per_s, ₽ по `app/obs/prices.py`) и каждый инструмент (аргументы, краткий результат, мс, ошибка).
7. API: `POST /api/chat` (SSE: токены, события `verdict`, `ticket_draft`, `ticket_created`, `meta{ttft, tok_per_s}`), `POST /api/action/get_diagnosis`, `POST /api/tickets/confirm`.
8. Тесты с замоканным LLM: таблица §7 (check_failed → нет заявки; warning → «требует подтверждения», urgency ≤ medium; нет фрагментов → нет заявки), повтор confirm_token.

Приёмка (curl/HTTP): T792HO98/S-0043 → вердикт + этапы со страницами + заявка TKT-…; P456AT178/S-0003 → «повторите запись», без заявки; M260EH47/S-0079 → «нет инструкции» (если общей процедуры нет).
Коммит: `agent: tools, verdict rules, guardrails, tickets, trace`.
