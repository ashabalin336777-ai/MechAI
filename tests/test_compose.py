"""Проверка docker-compose.yml на запреты Timeweb App Platform (раздел 16 ТЗ, AGENTS.md)."""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE = REPO_ROOT / "docker-compose.yml"

FORBIDDEN_TOP_LEVEL = {"volumes", "networks", "include", "extends", "external", "name", "secrets"}
FORBIDDEN_SERVICE_KEYS = {
    "volumes",
    "privileged",
    "extra_hosts",
    "network_mode",
    "include",
    "extends",
    "external",
    "name",
    "driver_opts",
    "env_file",
}
FORBIDDEN_HOST_PORTS = {80, 443}


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_no_forbidden_top_level_keys(compose: dict) -> None:
    assert not FORBIDDEN_TOP_LEVEL & compose.keys()


def test_no_forbidden_service_keys(compose: dict) -> None:
    for name, service in compose["services"].items():
        found = FORBIDDEN_SERVICE_KEYS & service.keys()
        assert not found, f"сервис {name}: запрещено {sorted(found)}"


def test_app_is_first_service_on_port_8000(compose: dict) -> None:
    services = list(compose["services"])
    assert services[0] == "app"
    assert "8000:8000" in compose["services"]["app"]["ports"]


def test_mocks_follow_app_on_their_ports(compose: dict) -> None:
    assert "8001:8001" in compose["services"]["mock_ml"]["ports"]
    assert "8002:8002" in compose["services"]["mock_toir"]["ports"]


def test_no_host_ports_80_or_443(compose: dict) -> None:
    for name, service in compose["services"].items():
        for mapping in service.get("ports", []):
            host_port = int(str(mapping).split(":")[0])
            assert host_port not in FORBIDDEN_HOST_PORTS, f"сервис {name}: порт {host_port}"


def test_app_uses_environment_not_env_file(compose: dict) -> None:
    env = compose["services"]["app"]["environment"]
    assert "DATABASE_URL" in env
    assert "MOCK_ML_URL" in env and "MOCK_TOIR_URL" in env


def test_app_passes_every_setting_from_env_example(compose: dict) -> None:
    """Все переменные из .env.example доходят до app (кроме POSTGRES_PASSWORD локального файла)."""
    env_keys = {
        line.split("=", 1)[0]
        for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    env_keys.discard("POSTGRES_PASSWORD")
    missing = env_keys - set(compose["services"]["app"]["environment"])
    assert not missing, f"нет в compose: {sorted(missing)}"
