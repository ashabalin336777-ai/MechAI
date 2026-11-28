"""Голосовой ввод: POST /api/stt. Запись механика → распознанный текст для поля ввода (ТЗ §10).

Аудио живёт в памяти только на время запроса и нигде не сохраняется (152-ФЗ). В журнал
пишем ход распознавания (run с input_mode=voice) и шаг stt: модель, язык, размер, длительность,
₽ и код ошибки. Байтов записи в журнале нет.
"""

import time
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.clients.stt_client import MAX_AUDIO_BYTES, MAX_AUDIO_SECONDS, SttError
from app.obs.journal import RunSummary, StepRecord
from app.obs.prices import stt_cost_rub

router = APIRouter(prefix="/api", tags=["voice"])

# Типы из MediaRecorder: Chrome/Android — webm/opus, Safari/iOS — mp4 (аас).
EXTENSIONS: dict[str, str] = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "video/mp4": "mp4",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
}
# Допуск к проверке длительности: клиент обрезает на 30 с, сервер не отвергает округление.
DURATION_TOLERANCE_S = 1.0


class SttResult(BaseModel):
    text: str
    duration_s: float | None
    language: str = "ru"


@router.post("/stt", response_model=SttResult)
def transcribe(
    request: Request,
    audio: Annotated[UploadFile, File()],
    consent_at: Annotated[str | None, Form(max_length=40)] = None,
    vehicle_id: Annotated[str | None, Form(max_length=32)] = None,
    session_id: Annotated[str | None, Form(max_length=64)] = None,
) -> SttResult:
    _check_consent(consent_at)
    mime = (audio.content_type or "").split(";")[0].strip().lower()
    extension = EXTENSIONS.get(mime)
    if extension is None:
        raise HTTPException(
            status_code=415, detail="Неподдерживаемый формат записи. Запишите ещё раз."
        )
    data = audio.file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Запись больше 10 МБ. Запишите короче.")
    if not data:
        raise HTTPException(status_code=422, detail="Запись пустая. Нажмите микрофон и повторите.")

    services = request.app.state.agent
    client = request.app.state.stt_client
    journal = services.journal
    run_id = journal.start_run(
        vehicle_id=vehicle_id, session_id=session_id, lang="ru", input_mode="voice"
    )
    started = time.monotonic()
    error: SttError | None = None
    transcript = None
    try:
        transcript = client.transcribe(data, filename=f"voice.{extension}")
        if (
            transcript.duration_s is not None
            and transcript.duration_s > MAX_AUDIO_SECONDS + DURATION_TOLERANCE_S
        ):
            error = SttError(422, "Запись длиннее 30 секунд. Запишите короче.", "too_long")
    except SttError as exc:
        error = exc
    total_ms = int((time.monotonic() - started) * 1000)

    duration = transcript.duration_s if transcript is not None else None
    journal.add_step(
        StepRecord(
            run_id=run_id,
            n=1,
            kind="stt",
            name=client.model,
            input={"model": client.model, "language": "ru", "bytes": len(data), "mime": mime},
            output=(
                {"chars": len(transcript.text), "duration_s": duration}
                if transcript is not None and error is None
                else None
            ),
            ms=total_ms,
            model=client.model,
            error=error.user_message if error is not None else None,
            error_class=type(error).__name__ if error is not None else None,
            error_message=error.detail if error is not None else None,
        )
    )
    journal.finish_run(
        run_id,
        RunSummary(
            status="error" if error is not None else "ok",
            total_ms=total_ms,
            cost_rub=stt_cost_rub(duration),
        ),
    )
    if error is not None:
        raise HTTPException(status_code=error.status_code, detail=error.user_message)
    assert transcript is not None
    return SttResult(text=transcript.text, duration_s=transcript.duration_s)


def _check_consent(consent_at: str | None) -> None:
    """Согласие на микрофон: интерфейс передаёт время подтверждения (ТЗ, 152-ФЗ)."""
    try:
        datetime.fromisoformat(consent_at or "")
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="Сначала подтвердите согласие на голосовой ввод."
        ) from exc
