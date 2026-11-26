"""Замер скорости моделей Neuraldeep: TTFT, токены в секунду, tool calling. Пишет eval/bench.md.

Запуск (ключ только из переменной окружения, в файлах он не сохраняется):
    NEURALDEEP_API_KEY=... python -m scripts.bench_models

Метрики (ТЗ §9, docs/models.md):
- ttft_ms: от отправки запроса до первого токена (reasoning или content);
- ttft_content_ms: до первого токена ответа (content), без reasoning;
- tok_per_s = completion_tokens / (t_конца − t_первого токена), по usage из стрима;
  если usage не пришёл, считаем число дельт и помечаем замер как приблизительный.
"""

import json
import os
import statistics
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "eval" / "bench.md"
DEFAULT_BASE_URL = "https://api.neuraldeep.ru/v1"
REQUESTS_PER_MODEL = 10
MAX_TOKENS = 400
TIMEOUT_S = 120.0

# Основные кандидаты из ТЗ/фазы 02. Последний — справочный: без reasoning, но без tools.
MODELS: list[tuple[str, str]] = [
    ("qwen3.8-flash-next-ru-noreason", "модель агента (tools, без reasoning, в РФ)"),
    ("qwen3.6-fp8", "справка: reasoning по умолчанию, отказ от кандидата"),
    ("qwen3.6-fp8-noreason", "справка: скорость без reasoning, tools нет по каталогу"),
]

PROMPTS: list[str] = [
    "Опиши порядок проверки давления масла в ЯМЗ-236М2 на холостом ходу и на номинальных оборотах.",
    "Перечисли шаги регулировки теплового зазора клапанов дизеля ЯМЗ-536 по порядку работ.",
    "Как проверить натяжение приводного ремня генератора на ЗМЗ-5234.10? Ответь коротко по шагам.",
    "Что нужно сделать перед заменой вкладышей коренного подшипника в дизеле? Перечисли 6 пунктов.",
    "Объясни, почему при низком давлении масла нельзя продолжать эксплуатацию двигателя.",
    "Какие признаки указывают на износ цилиндропоршневой группы дизеля и как их проверить?",
    "Опиши порядок снятия и установки впускного коллектора на ЗМЗ-40905.10 пошагово.",
    "Что проверяют при диагностике турбокомпрессора дизеля: перечисли проверки по порядку.",
    "Как выполнить замену охлаждающей жидкости на двигателе ЯМЗ-236М2? Ответь по шагам.",
    "Перечисли признаки неисправности форсунок дизеля и порядок их проверки на стенде.",
]

TOOL_PROMPT = "Какая модель двигателя у машины с госномером T792HO98? Используй инструмент."
TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_vehicle",
        "description": "Карточка ТС по госномеру: марка, модель, двигатель.",
        "parameters": {
            "type": "object",
            "properties": {"vehicle_id": {"type": "string", "description": "госномер"}},
            "required": ["vehicle_id"],
        },
    },
}
TOOL_EXPECTED_ARG = {"vehicle_id": "T792HO98"}


@dataclass
class StreamResult:
    ok: bool
    error: str = ""
    ttft_ms: float | None = None
    ttft_content_ms: float | None = None
    total_ms: float | None = None
    completion_tokens: int | None = None
    tok_per_s: float | None = None
    usage_exact: bool = False
    reasoning_seen: bool = False


@dataclass
class ToolResult:
    ok: bool
    error: str = ""
    latency_ms: float | None = None


@dataclass
class ModelReport:
    model: str
    note: str
    streams: list[StreamResult] = field(default_factory=list)
    tool: ToolResult | None = None


def parse_sse(lines: Iterable[str]) -> Iterator[dict]:
    """Извлекает JSON из строк `data: {...}`. Служебный `[DONE]` и пустые строки пропускаем."""
    for raw in lines:
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            continue
        yield json.loads(data)


def percentile(values: list[float], fraction: float) -> float:
    """Нижний перцентиль по отсортированным значениям (p10 для fraction=0.1)."""
    ordered = sorted(values)
    index = int(fraction * (len(ordered) - 1))
    return ordered[index]


def summarize(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "median": statistics.median(values),
        "p10": percentile(values, 0.1),
        "mean": statistics.fmean(values),
    }


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def measure_stream(
    client: httpx.Client, base_url: str, api_key: str, model: str, prompt: str
) -> StreamResult:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.2,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    started = time.perf_counter()
    first_any: float | None = None
    first_content: float | None = None
    deltas = 0
    reasoning_seen = False
    usage: dict | None = None
    try:
        with client.stream(
            "POST", f"{base_url}/chat/completions", json=body, headers=_headers(api_key)
        ) as response:
            if response.status_code >= 400:
                return StreamResult(ok=False, error=f"HTTP {response.status_code}")
            for payload in parse_sse(response.iter_lines()):
                if payload.get("error"):
                    return StreamResult(ok=False, error=str(payload["error"])[:200])
                if payload.get("usage"):
                    usage = payload["usage"]
                for choice in payload.get("choices") or []:
                    delta = choice.get("delta") or {}
                    now = time.perf_counter()
                    if delta.get("reasoning_content"):
                        reasoning_seen = True
                        first_any = first_any or now
                        deltas += 1
                    if delta.get("content"):
                        first_any = first_any or now
                        first_content = first_content or now
                        deltas += 1
    except httpx.HTTPError as exc:
        return StreamResult(ok=False, error=type(exc).__name__)
    ended = time.perf_counter()
    if first_any is None:
        return StreamResult(ok=False, error="пустой ответ")

    completion = usage.get("completion_tokens") if usage else None
    exact = completion is not None
    tokens = int(completion) if exact else deltas
    duration = ended - first_any
    tok_per_s = tokens / duration if duration > 0 else None
    return StreamResult(
        ok=True,
        ttft_ms=(first_any - started) * 1000,
        ttft_content_ms=((first_content or first_any) - started) * 1000,
        total_ms=(ended - started) * 1000,
        completion_tokens=tokens,
        tok_per_s=tok_per_s,
        usage_exact=exact,
        reasoning_seen=reasoning_seen,
    )


def measure_tool_call(client: httpx.Client, base_url: str, api_key: str, model: str) -> ToolResult:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": TOOL_PROMPT}],
        "tools": [TOOL_DEFINITION],
        "tool_choice": "auto",
        "max_tokens": MAX_TOKENS,
        "temperature": 0.0,
    }
    started = time.perf_counter()
    try:
        response = client.post(f"{base_url}/chat/completions", json=body, headers=_headers(api_key))
    except httpx.HTTPError as exc:
        return ToolResult(ok=False, error=type(exc).__name__)
    latency = (time.perf_counter() - started) * 1000
    if response.status_code >= 400:
        return ToolResult(ok=False, error=f"HTTP {response.status_code}", latency_ms=latency)
    try:
        message = response.json()["choices"][0]["message"]
        calls = message.get("tool_calls") or []
    except (ValueError, KeyError, IndexError, TypeError):
        return ToolResult(ok=False, error="ответ не в формате chat", latency_ms=latency)
    if not calls:
        return ToolResult(ok=False, error="модель не вызвала инструмент", latency_ms=latency)
    call = calls[0]
    if call.get("function", {}).get("name") != "get_vehicle":
        return ToolResult(ok=False, error="вызван другой инструмент", latency_ms=latency)
    try:
        args = json.loads(call["function"].get("arguments") or "{}")
    except json.JSONDecodeError:
        return ToolResult(ok=False, error="аргументы не JSON", latency_ms=latency)
    if args != TOOL_EXPECTED_ARG:
        return ToolResult(ok=False, error="аргументы не совпали", latency_ms=latency)
    return ToolResult(ok=True, latency_ms=latency)


def run_model(
    client: httpx.Client, base_url: str, api_key: str, model: str, note: str
) -> ModelReport:
    report = ModelReport(model=model, note=note)
    for index in range(REQUESTS_PER_MODEL):
        prompt = PROMPTS[index % len(PROMPTS)]
        report.streams.append(measure_stream(client, base_url, api_key, model, prompt))
    report.tool = measure_tool_call(client, base_url, api_key, model)
    return report


def _fmt(value: float | None, digits: int = 0) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_report(reports: list[ModelReport], base_host: str, when: datetime) -> str:
    lines = [
        "# Замер моделей Neuraldeep",
        "",
        f"Дата: {when:%Y-%m-%d %H:%M} (локальное время замера). Эндпоинт: `{base_host}`. "
        f"Запросов на модель: {REQUESTS_PER_MODEL}, max_tokens: {MAX_TOKENS}, "
        "стрим с `include_usage`.",
        "",
        "Цель ТЗ: скорость агента > 20 ток/с (p10), TTFT ≈ 1 с. Запрос к инструменту: "
        "`get_vehicle` с госномером `T792HO98`, ожидаем аргумент `vehicle_id`.",
        "",
        "| Модель | Роль | Успешно | TTFT, мс (медиана) | TTFT контента, мс (медиана) | "
        "Ток/с (медиана) | Ток/с (p10) | Ток/с (среднее) | Reasoning | Usage точный | "
        "Tool calling |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for report in reports:
        ok = [s for s in report.streams if s.ok]
        ttft = summarize([s.ttft_ms for s in ok if s.ttft_ms is not None])
        ttft_c = summarize([s.ttft_content_ms for s in ok if s.ttft_content_ms is not None])
        speed = summarize([s.tok_per_s for s in ok if s.tok_per_s is not None])
        reasoning = "да" if any(s.reasoning_seen for s in ok) else "нет"
        exact = sum(1 for s in ok if s.usage_exact)
        tool = report.tool
        tool_text = "—" if tool is None else ("ok" if tool.ok else f"ошибка: {tool.error}")
        lines.append(
            f"| `{report.model}` | {report.note} | {len(ok)}/{len(report.streams)} | "
            f"{_fmt(ttft and ttft['median'])} | {_fmt(ttft_c and ttft_c['median'])} | "
            f"{_fmt(speed and speed['median'], 1)} | {_fmt(speed and speed['p10'], 1)} | "
            f"{_fmt(speed and speed['mean'], 1)} | {reasoning} | "
            f"{exact}/{len(ok)} | {tool_text} |"
        )
    lines += ["", "## Ошибки", ""]
    any_error = False
    for report in reports:
        errors = sorted({s.error for s in report.streams if not s.ok})
        if report.tool is not None and not report.tool.ok:
            errors.append(f"tool: {report.tool.error}")
        if errors:
            any_error = True
            lines.append(f"- `{report.model}`: {'; '.join(errors)}")
    if not any_error:
        lines.append("Ошибок не было.")
    lines += [
        "",
        "Измерения приблизительные, если в колонке «Usage точный» меньше числа успешных "
        "запросов: тогда токены посчитаны по дельтам стрима.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    api_key = os.environ.get("NEURALDEEP_API_KEY", "").strip()
    if not api_key:
        print("Задайте NEURALDEEP_API_KEY в переменной окружения.", file=sys.stderr)
        return 1
    base_url = os.environ.get("NEURALDEEP_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    base_host = httpx.URL(base_url).host
    with httpx.Client(timeout=TIMEOUT_S) as client:
        reports = []
        for model, note in MODELS:
            print(f"замер: {model}", flush=True)
            reports.append(run_model(client, base_url, api_key, model, note))
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(reports, base_host, datetime.now()), encoding="utf-8")
    print(f"готово: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
