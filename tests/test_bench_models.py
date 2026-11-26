"""Скрипт замера проверяется на поддельном транспорте: без сети и без ключа."""

import json
from datetime import datetime

import httpx

from scripts.bench_models import (
    TOOL_EXPECTED_ARG,
    measure_stream,
    measure_tool_call,
    parse_sse,
    percentile,
    render_report,
    summarize,
)

BASE = "https://api.test/v1"
KEY = "test-key"


def _sse(chunks: list[dict]) -> bytes:
    lines = [f"data: {json.dumps(c, ensure_ascii=False)}" for c in chunks]
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode("utf-8")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_sse_skips_done_and_blank_lines() -> None:
    raw = ['data: {"a": 1}', "", "data: [DONE]", ": keep-alive"]
    assert list(parse_sse(raw)) == [{"a": 1}]


def test_measure_stream_reads_usage_and_reasoning() -> None:
    body = _sse(
        [
            {"choices": [{"delta": {"reasoning_content": "думаю"}}]},
            {"choices": [{"delta": {"content": "Ответ"}}]},
            {"choices": [{"delta": {"content": " дальше"}}]},
            {"choices": [], "usage": {"completion_tokens": 3}},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        sent = json.loads(request.content)
        assert sent["stream"] is True
        assert sent["stream_options"] == {"include_usage": True}
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    result = measure_stream(_client(handler), BASE, KEY, "m", "вопрос")
    assert result.ok
    assert result.reasoning_seen
    assert result.usage_exact
    assert result.completion_tokens == 3
    assert result.ttft_ms is not None and result.ttft_content_ms is not None
    assert result.ttft_content_ms >= result.ttft_ms


def test_measure_stream_without_usage_is_marked_approximate() -> None:
    body = _sse(
        [{"choices": [{"delta": {"content": "a"}}]}, {"choices": [{"delta": {"content": "b"}}]}]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    result = measure_stream(_client(handler), BASE, KEY, "m", "вопрос")
    assert result.ok
    assert not result.usage_exact
    assert result.completion_tokens == 2


def test_measure_stream_reports_http_error_without_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "limit"})

    result = measure_stream(_client(handler), BASE, KEY, "m", "вопрос")
    assert not result.ok
    assert result.error == "HTTP 429"


def test_measure_stream_empty_answer_is_error() -> None:
    body = _sse([{"choices": [{"delta": {}}]}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    result = measure_stream(_client(handler), BASE, KEY, "m", "вопрос")
    assert not result.ok
    assert result.error == "пустой ответ"


def test_tool_call_correct_arguments_is_ok() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "get_vehicle",
                                "arguments": json.dumps(TOOL_EXPECTED_ARG),
                            }
                        }
                    ]
                }
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["tools"][0]["function"]["name"] == "get_vehicle"
        return httpx.Response(200, json=payload)

    assert measure_tool_call(_client(handler), BASE, KEY, "m").ok


def test_tool_call_wrong_arguments_fails() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "get_vehicle", "arguments": '{"vehicle_id": "X"}'}}
                    ]
                }
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    result = measure_tool_call(_client(handler), BASE, KEY, "m")
    assert not result.ok
    assert result.error == "аргументы не совпали"


def test_no_tool_call_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "текст"}}]})

    result = measure_tool_call(_client(handler), BASE, KEY, "m")
    assert not result.ok
    assert result.error == "модель не вызвала инструмент"


def test_percentile_and_summary() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(values, 0.1) == 10.0
    stats = summarize(values)
    assert stats is not None
    assert stats["median"] == 30.0
    assert summarize([]) is None


def test_render_report_contains_table_and_errors() -> None:
    from scripts.bench_models import ModelReport, StreamResult, ToolResult

    report = ModelReport(
        model="qwen3.6-fp8",
        note="тест",
        streams=[
            StreamResult(
                ok=True,
                ttft_ms=900.0,
                ttft_content_ms=1200.0,
                completion_tokens=300,
                tok_per_s=40.0,
                usage_exact=True,
                reasoning_seen=True,
            ),
            StreamResult(ok=False, error="HTTP 429"),
        ],
        tool=ToolResult(ok=False, error="модель не вызвала инструмент"),
    )
    text = render_report([report], "api.test", datetime(2026, 11, 26, 19, 0))
    assert "`qwen3.6-fp8`" in text
    assert "| 1/2 |" in text
    assert "да | 1/1 | ошибка: модель не вызвала инструмент |" in text
    assert "HTTP 429" in text
    assert "test-key" not in text
