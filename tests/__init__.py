"""Тесты MechAI. Окружение для всех тестов задаётся здесь, до импорта заглушек mock/.

Заглушки читают парк из MOCK_DATA_PATH (mock/mock_ml/app.py). Тесты подставляют синтетический
набор из tests/fixtures/mock_data, а не материалы заказчика (п. 9.1 требований организатора).
Ссылки на материалы пустые: тесты не ходят в сеть и не качают файлы.
"""

import os
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "mock_data"
os.environ["MOCK_DATA_PATH"] = str(FIXTURES_DIR / "vehicles.json")
os.environ["VEHICLES_PATH"] = str(FIXTURES_DIR / "vehicles.json")
os.environ["FAULT_TYPES_PATH"] = str(FIXTURES_DIR / "fault_types.json")
for _name in ("MATERIALS_URL", "MANUALS_URL", "MOCK_DATA_URL"):
    os.environ[_name] = ""
