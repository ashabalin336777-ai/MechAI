"""Прайс Neuraldeep, ₽ за 1 млн токенов (вход, выход). Источник: docs/models.md, 26.11.

Модели без выходных токенов (эмбеддинги, реранк) имеют выход 0: в прайсе у них «—».
Реранк в ₽ не считаем по токенам: сервис не возвращает их число (см. app/rag/rerank.py).
"""

from decimal import Decimal

PRICES_RUB_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "qwen3.8-flash-next-ru-noreason": (Decimal("20.36"), Decimal("64.30")),
    "qwen3.6-fp8": (Decimal("9.38"), Decimal("53.58")),
    "qwen3.8-27b": (Decimal("32.15"), Decimal("160.74")),
    "bge-m3": (Decimal("3.21"), Decimal("0")),
    "bge-reranker": (Decimal("3.21"), Decimal("0")),
}

MEGA = Decimal(1_000_000)
# Распознавание речи, whisper-1: 1 ₽ за минуту (docs/models.md).
STT_RUB_PER_MINUTE = Decimal("1")


def cost_rub(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
    """Стоимость вызова в ₽. None, если модели нет в прайсе (тогда в журнале пусто, а не ноль)."""
    price = PRICES_RUB_PER_MTOK.get(model)
    if price is None:
        return None
    input_rate, output_rate = price
    total = Decimal(prompt_tokens) * input_rate + Decimal(completion_tokens) * output_rate
    return (total / MEGA).quantize(Decimal("0.0001"))


def stt_cost_rub(duration_s: float | None) -> Decimal | None:
    """Стоимость распознавания в ₽ по длительности записи. None, если длительность неизвестна."""
    if duration_s is None:
        return None
    minutes = Decimal(str(duration_s)) / Decimal(60)
    return (minutes * STT_RUB_PER_MINUTE).quantize(Decimal("0.0001"))
