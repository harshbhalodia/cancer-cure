"""Runtime settings. Override any value with a CC_-prefixed environment variable (or backend/.env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CC_", env_file=BACKEND_DIR / ".env", extra="ignore")

    # All patient data (database + uploads) lives under this folder, which is git-ignored.
    data_dir: Path = BACKEND_DIR / "data"

    lm_endpoint: str = "http://localhost:1234/api/v1/chat"
    lm_models_endpoint: str = "http://localhost:1234/v1/models"
    lm_model: str = "qwen/qwen3.6-35b-a3b"
    lm_timeout_s: float = 600
    lm_temperature: float = 0.2
    # Scanned pages are read by a vision-capable model through LM Studio's OpenAI-compatible endpoint.
    lm_openai_endpoint: str = "http://localhost:1234/v1/chat/completions"
    ocr_model: str = ""  # empty = use lm_model
    ocr_fallback_model: str = "google/gemma-4-e2b"  # tried when the main model returns nothing for a page; empty = off
    ocr_timeout_s: float = 600

    emergency_number: str = "112"
    cors_origins: list[str] = ["http://localhost:5174", "http://127.0.0.1:5174"]

    # Background processing of bulk uploads. Files dropped in inbox_dir are picked up automatically.
    worker_enabled: bool = True
    inbox_dir: Path = BACKEND_DIR.parent / "uploads"
    watch_interval_s: float = 10

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cancer_cure.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
