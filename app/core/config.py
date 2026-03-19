from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
IS_VERCEL = bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    base_dir: Path
    data_dir: Path
    runtime_dir: Path
    upload_dir: Path
    generated_dir: Path
    database_path: Path
    max_upload_size_mb: int
    deepl_api_key: str | None
    deepl_api_url: str
    cefr_api_enabled: bool
    cefr_api_url: str
    cefr_api_timeout_seconds: float
    history_limit: int

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def supported_extensions(self) -> set[str]:
        return {".pdf", ".docx", ".pptx"}

    @property
    def cefr_cache_path(self) -> Path:
        return self.runtime_dir / "cefr_level_cache.json"

    @classmethod
    def from_env(cls) -> "Settings":
        runtime_dir = Path("/tmp/ger_translator") if IS_VERCEL else BASE_DIR
        return cls(
            app_name=os.getenv("APP_NAME", "Ger Translator"),
            environment=os.getenv("APP_ENV", "development"),
            base_dir=BASE_DIR,
            data_dir=BASE_DIR / "data",
            runtime_dir=runtime_dir,
            upload_dir=runtime_dir / "uploads",
            generated_dir=runtime_dir / "generated",
            database_path=runtime_dir / "app_data.sqlite3",
            max_upload_size_mb=_env_int("MAX_UPLOAD_SIZE_MB", 20),
            deepl_api_key=os.getenv("DEEPL_API_KEY"),
            deepl_api_url=os.getenv(
                "DEEPL_API_URL",
                "https://api-free.deepl.com/v2/translate",
            ),
            cefr_api_enabled=_env_bool("CEFR_API_ENABLED", True),
            cefr_api_url=os.getenv(
                "CEFR_API_URL",
                "https://cental.uclouvain.be/cefrlex/daflex/analyse/",
            ),
            cefr_api_timeout_seconds=_env_float("CEFR_API_TIMEOUT_SECONDS", 12.0),
            history_limit=_env_int("HISTORY_LIMIT", 8),
        )

    def ensure_directories(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)


settings = Settings.from_env()
settings.ensure_directories()
