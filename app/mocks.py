"""Запасной режим MOUNT_MOCKS=1: заглушки заказчика монтируются в app как под-приложения.

Используется, если межсервисная сеть App Platform не резолвит имена сервисов.
Код заглушек не меняем.
"""

import sys
from pathlib import Path

from fastapi import FastAPI

MOCKS_DIR = Path(__file__).resolve().parent.parent / "mock"


def mount_mocks(app: FastAPI) -> None:
    if str(MOCKS_DIR) not in sys.path:
        sys.path.insert(0, str(MOCKS_DIR))
    from mock_ml.app import app as ml_app
    from mock_toir.app import app as toir_app

    app.mount("/mock/ml", ml_app)
    app.mount("/mock/toir", toir_app)
