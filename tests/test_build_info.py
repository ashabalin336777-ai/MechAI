"""Версия сборки: Dockerfile передаёт GIT_SHA, /health показывает хэш коммита образа."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from tests.helpers import REPO_ROOT, VEHICLES_PATH


def test_dockerfile_takes_git_sha_as_build_argument() -> None:
    lines = [line.strip() for line in (REPO_ROOT / "Dockerfile").read_text("utf-8").splitlines()]
    assert "ARG GIT_SHA=unknown" in lines
    assert any(line.startswith("ENV GIT_SHA=${GIT_SHA}") for line in lines)


def test_health_shows_build_commit(app_with_stubs: FastAPI) -> None:
    app_with_stubs.state.settings = Settings(vehicles_path=VEHICLES_PATH, git_sha="abc1234")
    body = TestClient(app_with_stubs).get("/health").json()
    assert body["git_sha"] == "abc1234"


def test_health_says_unknown_without_build_commit(app_with_stubs: FastAPI) -> None:
    app_with_stubs.state.settings = Settings(vehicles_path=VEHICLES_PATH, git_sha="")
    body = TestClient(app_with_stubs).get("/health").json()
    assert body["git_sha"] == "unknown"
