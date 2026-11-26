"""Прайс Neuraldeep, ₽ за 1 млн токенов (вход, выход). Источник: docs/models.md, 26.11."""

from decimal import Decimal

PRICES_RUB_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "qwen3.8-flash-next-ru-noreason": (Decimal("20.36"), Decimal("64.30")),
    "qwen3.6-fp8": (Decimal("9.38"), Decimal("53.58")),
    "qwen3.8-27b": (Decimal("32.15"), Decimal("160.74")),
}

MEGA = Decimal(1_000_000)


def cost_rub(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
    """Стоимость вызова в ₽. None, если модели нет в прайсе (тогда в журнале пусто, а не ноль)."""
    price = PRICES_RUB_PER_MTOK.get(model)
    if price is None:
        return None
    input_rate, output_rate = price
    total = Decimal(prompt_tokens) * input_rate + Decimal(completion_tokens) * output_rate
    return (total / MEGA).quantize(Decimal("0.0001"))
