"""Совместимость кода неисправности с топливом двигателя (ТЗ §17.1, строка «нет инструкции»).

F12 (зажигание) и F13 (подача бензина) — узлы бензинового двигателя, F08 (дизельная топливоподача) —
дизельного. Для ТС с другим топливом диагноз не применим: процедуру по нему не подбираем и заявку
не формируем. Таблица — правило заказчика, fault_types.json поля топлива не содержит.
"""

FAULT_FUEL: dict[str, str] = {"F08": "дизель", "F12": "бензин", "F13": "бензин"}
FUEL_ADJECTIVE: dict[str, str] = {"дизель": "дизельному", "бензин": "бензиновому"}


def expected_fuel(anomaly_type: str | None) -> str | None:
    """Топливо, к которому относится код неисправности (None — код от топлива не зависит)."""
    return FAULT_FUEL.get(anomaly_type or "")


def fuel_mismatch(anomaly_type: str | None, fuel: str) -> str | None:
    """Топливо, к которому относится код, если оно не совпадает с топливом ТС; иначе None."""
    required = expected_fuel(anomaly_type)
    return required if required is not None and required != fuel else None
