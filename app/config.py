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
    # Vision-модель для OCR страниц-рисунков; запасная — при ошибке или таймауте основной.
    ocr_model: str = "gemma-4-31b-noreason"
    ocr_fallback_model: str = "qwen3.6-35b-a3b-noreason"
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
    known_conflicts_path: Path = Path("data/known_conflicts.yaml")
    # Материалы задачи не лежат в git (п. 9.1 требований организатора). Ссылки только из env.
    # MATERIALS_URL — публичная папка с vehicles.json, fault_types.json и PDF руководств.
    # MANUALS_URL и MOCK_DATA_URL переопределяют её для PDF и для JSON заглушек.
    materials_url: str = ""
    manuals_url: str = ""
    mock_data_url: str = ""
    # Архив с заглушками в публичной папке: используется, если отдельного JSON в папке нет.
    mock_archive_name: str = "neurodvs_hackathon_mock_2026-11-16.zip"

    conf_low: float = Field(default=0.60, ge=0, le=1)
    score_medium: float = Field(default=0.60, ge=0, le=1)
    score_high: float = Field(default=0.80, ge=0, le=1)
    rag_min_score: float = Field(default=0.80, ge=0, le=1)

    agent_timeout_s: float = Field(default=90.0, gt=0)
    agent_max_tool_calls: int = Field(default=8, ge=1, le=20)

    auth_mode: Literal["demo", "pin"] = "demo"
    jwt_secret: str = ""
    log_retention_days: int = Field(default=90, ge=1)

    # Постоянный админ-доступ к POST /admin/eval (Bearer). Пусто — эндпоинта нет (404).
    admin_token: str = ""
    eval_questions_path: Path = Path("eval/questions.yaml")
    agent_scenarios_path: Path = Path("eval/agent_scenarios.yaml")
    # Хэш коммита, из которого собрано приложение (для eval_runs). Пусто — в таблице NULL.
    commit_sha: str = ""
    # Хэш коммита образа: Dockerfile получает ARG GIT_SHA. Пусто — в /health будет unknown.
    git_sha: str = ""

    @property
    def manuals_base_url(self) -> str:
        """Публичная папка для PDF руководств: MANUALS_URL, иначе MATERIALS_URL."""
        return self.manuals_url or self.materials_url

    @property
    def mock_data_base_url(self) -> str:
        """Публичная папка для JSON заглушек: MOCK_DATA_URL, иначе MATERIALS_URL."""
        return self.mock_data_url or self.materials_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
