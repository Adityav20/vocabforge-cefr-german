from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    base_dir: Path
    data_dir: Path
    upload_dir: Path
    generated_dir: Path
    database_path: Path
    max_upload_size_mb: int
    deepl_api_key: str | None
    deepl_api_url: str
    history_limit: int

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def supported_extensions(self) -> set[str]:
        return {".pdf", ".docx", ".pptx"}

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_name=os.getenv("APP_NAME", "Ger Translator"),
            environment=os.getenv("APP_ENV", "development"),
            base_dir=BASE_DIR,
            data_dir=BASE_DIR / "data",
            upload_dir=BASE_DIR / "uploads",
            generated_dir=BASE_DIR / "generated",
            database_path=BASE_DIR / "app_data.sqlite3",
            max_upload_size_mb=_env_int("MAX_UPLOAD_SIZE_MB", 20),
            deepl_api_key=os.getenv("DEEPL_API_KEY"),
            deepl_api_url=os.getenv(
                "DEEPL_API_URL",
                "https://api-free.deepl.com/v2/translate",
            ),
            history_limit=_env_int("HISTORY_LIMIT", 8),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)


settings = Settings.from_env()
settings.ensure_directories()

