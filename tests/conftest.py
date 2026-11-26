"""Фикстуры: клиенты ML и ТОиР подключаются к настоящим заглушкам из mock/ через TestClient."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mock_ml.app import app as ml_stub
from mock_toir.app import app as toir_stub

from app.clients.ml_client import MlClient
from app.clients.toir_client import ToirClient
from app.config import Settings
from app.main import create_app
from tests.helpers import STUB_BASE, VEHICLES_PATH


@pytest.fixture
def ml_client() -> MlClient:
    return MlClient(STUB_BASE, http=TestClient(ml_stub))


@pytest.fixture
def toir_client() -> ToirClient:
    return ToirClient(STUB_BASE, http=TestClient(toir_stub))


@pytest.fixture
def app_with_stubs() -> Iterator[FastAPI]:
    """Приложение, где клиенты ходят в заглушки в памяти (без сети)."""
    app = create_app(Settings(vehicles_path=VEHICLES_PATH))
    app.state.ml_client = MlClient(STUB_BASE, http=TestClient(ml_stub))
    app.state.toir_client = ToirClient(STUB_BASE, http=TestClient(toir_stub))
    yield app
