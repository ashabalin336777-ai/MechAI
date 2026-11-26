"""Настройки приложения из переменных окружения (раздел 15 ТЗ). Секреты только в env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    neuraldeep_api_key: str = ""
    neuraldeep_base_url: str = "https://api.neuraldeep.ru/v1"
    agent_model: str = "qwen3.8-flash-next-ru-noreason"
    agent_fallback_model: str = "qwen3.8-flash-next-ru-noreason"
    embed_model: str = "bge-m3"
    rerank_model: str = "bge-reranker"
    stt_model: str = "whisper-1"
    stt_browser_fallback: bool = False

    mock_ml_url: str = "http://mock_ml:8001"
    mock_toir_url: str = "http://mock_toir:8002"
    sensors_url: str = ""
    mount_mocks: bool = False

    database_url: str = ""
    vehicles_path: Path = Path("mock/data/vehicles.json")
    fault_types_path: Path = Path("mock/data/fault_types.json")
    manuals_dir: Path = Path("data/manuals")
    manuals_yadisk_url: str = "https://disk.yandex.ru/d/QdAA8p4m0ySe8Q"

    conf_low: float = Field(default=0.60, ge=0, le=1)
    score_high: float = Field(default=0.80, ge=0, le=1)
    rag_min_score: float = Field(default=0.35, ge=0, le=1)

    auth_mode: Literal["demo", "pin"] = "demo"
    jwt_secret: str = ""
    log_retention_days: int = Field(default=90, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
