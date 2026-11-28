"""Распознавание речи механика: Neuraldeep whisper-1, русский язык (ТЗ §10).

Аудио уходит в запросе и нигде не сохраняется (152-ФЗ). Повтора нет: таймаут 30 с — это предел.
"""

from dataclasses import dataclass

import openai
from openai import NOT_GIVEN, OpenAI

# Языки голоса из ТЗ и CIS-плана README: русский по умолчанию; uz/kk/tg/ky/en — по запросу формы.
STT_LANGUAGES = ("ru", "uz", "kk", "tg", "ky", "en")
# Whisper отдаёт язык полным английским названием в verbose_json; переводим в код.
WHISPER_LANGUAGE_NAMES = {
    "russian": "ru",
    "uzbek": "uz",
    "kazakh": "kk",
    "tajik": "tg",
    "kyrgyz": "ky",
    "english": "en",
}

STT_TIMEOUT_S = 30.0
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO_SECONDS = 30.0
# Словарь терминов (ТЗ §10): подсказка декодеру, чтобы «ТНВД» и «ЯМЗ» не искажались.
TERMS_PROMPT = (
    "ЯМЗ, ЗМЗ, ЯМЗ-236, ЗМЗ-40905, форсунка, ТНВД, коленвал, вкладыш, гидротолкатель, "
    "турбокомпрессор, дефектовка, заявка, тепловой зазор, давление масла, компрессия."
)
UNAVAILABLE_MESSAGE = (
    "Сервис распознавания речи временно недоступен. Повторите или введите вопрос текстом."
)


class SttError(Exception):
    """Распознавание не удалось. user_message — текст для механика; detail без трасс и ключей."""

    def __init__(self, status_code: int, user_message: str, detail: str = "") -> None:
        self.status_code = status_code
        self.user_message = user_message
        self.detail = detail
        super().__init__(f"stt: {user_message} {detail}".strip())


@dataclass(frozen=True)
class Transcript:
    text: str
    duration_s: float | None
    # Код языка, который определила модель (ru, uz…); None, если модель его не сообщила.
    language: str | None


def language_code(name: str | None) -> str | None:
    """Код языка из ответа Whisper: «russian» → «ru». Незнакомое название не пишем."""
    if not name:
        return None
    lowered = name.strip().lower()
    if lowered in STT_LANGUAGES:
        return lowered
    return WHISPER_LANGUAGE_NAMES.get(lowered)


class SttClient:
    def __init__(
        self, api_key: str, base_url: str, model: str, *, timeout_s: float = STT_TIMEOUT_S
    ) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0)
        self.model = model

    def transcribe(self, audio: bytes, filename: str, language: str | None) -> Transcript:
        """language=None — автоопределение моделью; иначе код из STT_LANGUAGES."""
        try:
            response = self._client.audio.transcriptions.create(
                model=self.model,
                file=(filename, audio),
                language=language or NOT_GIVEN,
                prompt=TERMS_PROMPT,
                response_format="verbose_json",
            )
        except openai.APITimeoutError as exc:
            raise SttError(
                504,
                "Распознавание заняло больше 30 секунд. Запишите короче "
                "или введите вопрос текстом.",
                type(exc).__name__,
            ) from exc
        except openai.APIStatusError as exc:
            if exc.status_code in (400, 413, 415, 422):
                raise SttError(
                    422, "Не удалось прочитать запись. Запишите ещё раз.", f"HTTP {exc.status_code}"
                ) from exc
            raise SttError(503, UNAVAILABLE_MESSAGE, f"HTTP {exc.status_code}") from exc
        except openai.OpenAIError as exc:
            raise SttError(503, UNAVAILABLE_MESSAGE, type(exc).__name__) from exc
        duration = getattr(response, "duration", None)
        return Transcript(
            text=(response.text or "").strip(),
            duration_s=float(duration) if duration is not None else None,
            language=language_code(getattr(response, "language", None)),
        )
