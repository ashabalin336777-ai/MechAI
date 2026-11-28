"""Чат агента и кнопка «Получить результат диагностики»: ответ потоком SSE (ТЗ §6.1, §14).

Ход агента идёт в рабочем потоке, события уходят в очередь и отдаются клиенту по мере появления.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.runner import AgentServices, TurnRequest, run_turn

router = APIRouter(prefix="/api", tags=["agent"])

UiMode = Literal["standard", "novice", "senior"]


class ChatBody(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=32)
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    ui_mode: UiMode = "standard"
    lang: Literal["ru"] = "ru"
    # voice — текст из распознавания речи (POST /api/stt); пишется в журнал хода как режим ввода.
    input_mode: Literal["text", "voice"] = "text"


class DiagnosisBody(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=32)
    session_id: str = Field(min_length=1, max_length=64)
    ui_mode: UiMode = "standard"
    lang: Literal["ru"] = "ru"


@router.post("/chat")
async def chat(body: ChatBody, request: Request) -> StreamingResponse:
    return _stream(
        request,
        TurnRequest(
            vehicle_id=body.vehicle_id,
            session_id=body.session_id,
            message=body.message,
            user_action=None,
            ui_mode=body.ui_mode,
            lang=body.lang,
            input_mode=body.input_mode,
        ),
    )


@router.post("/action/get_diagnosis")
async def get_diagnosis_action(body: DiagnosisBody, request: Request) -> StreamingResponse:
    return _stream(
        request,
        TurnRequest(
            vehicle_id=body.vehicle_id,
            session_id=body.session_id,
            message="",
            user_action="get_diagnosis",
            ui_mode=body.ui_mode,
            lang=body.lang,
        ),
    )


def _stream(request: Request, turn: TurnRequest) -> StreamingResponse:
    vehicles = request.app.state.vehicles
    if vehicles.get(turn.vehicle_id) is None:
        raise HTTPException(status_code=404, detail="Машина не найдена.")
    services = request.app.state.agent
    base_prompt = request.app.state.agent_prompt
    return StreamingResponse(
        _events(services, turn, base_prompt),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _events(
    services: AgentServices, turn: TurnRequest, base_prompt: str
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

    def emit(event: str, data: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, data))

    def worker() -> None:
        try:
            run_turn(services, turn, base_prompt, emit)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    task = loop.run_in_executor(None, worker)
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            yield _sse(event, data)
    finally:
        await task


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
