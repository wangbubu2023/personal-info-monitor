"""Application configuration management."""

import json
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> str:
    return os.path.join(Path.home(), ".pim", "data")


def _default_cors_origins() -> str:
    return ",".join(
        [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "http://localhost:1420",
            "http://127.0.0.1:1420",
        ]
    )


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Application
    app_name: str = "Personal Information Monitor"
    debug: bool = False

    # Data directory (SQLite db, logs, etc.)
    data_dir: str = _default_data_dir()

    # Database (SQLite — zero-install)
    database_url: str = ""
    async_database_url: str = ""

    # Fetch concurrency
    fetch_concurrency: int = 20  # Max parallel fetches

    # OpenAI
    openai_api_key: Optional[str] = None

    # Translation
    google_translate_api_key: Optional[str] = None

    # X (Twitter)
    x_api_key: Optional[str] = None
    x_api_secret: Optional[str] = None
    x_bearer_token: Optional[str] = None
    x_auth_token: Optional[str] = None       # 浏览器 Cookie auth_token
    x_ct0_token: Optional[str] = None        # 浏览器 Cookie ct0
    rsshub_url: str = "https://rsshub.app"
    nitter_instances: Optional[str] = None

    # YouTube API
    youtube_api_key: Optional[str] = None

    # Email SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None

    # Security
    encryption_key: str = ""
    probe_disable_ssl_verify: bool = False
    pim_api_key: str = ""
    cors_origins: str = _default_cors_origins()

    # AI processing (optional, can be enabled later)
    ai_processing_enabled: bool = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Expand ~ but leave filesystem bootstrap to explicit runtime entrypoints.
        self.data_dir = os.path.expanduser(self.data_dir)

        # Default SQLite paths if not explicitly set
        db_path = os.path.join(self.data_dir, "pim.db")
        if not self.database_url:
            self.database_url = f"sqlite:///{db_path}"
        if not self.async_database_url:
            self.async_database_url = f"sqlite+aiosqlite:///{db_path}"

        # Fallback in-memory secrets for direct imports/tests.
        if not self.encryption_key:
            self.encryption_key = secrets.token_hex(16)
        if not self.pim_api_key:
            self.pim_api_key = secrets.token_urlsafe(32)


_RUNTIME_SECRETS_FILENAME = "runtime-secrets.json"


def _runtime_secrets_path(data_dir: str) -> Path:
    return Path(data_dir).expanduser() / _RUNTIME_SECRETS_FILENAME


def _read_runtime_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        "ENCRYPTION_KEY": str(payload.get("ENCRYPTION_KEY") or "").strip(),
        "PIM_API_KEY": str(payload.get("PIM_API_KEY") or "").strip(),
    }


def _write_runtime_secrets(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=True, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        # Best-effort chmod on non-POSIX platforms.
        pass


def _ensure_runtime_secrets(data_dir: str) -> dict[str, str]:
    path = _runtime_secrets_path(data_dir)
    existing = _read_runtime_secrets(path)
    merged = dict(existing)

    if not merged.get("ENCRYPTION_KEY"):
        merged["ENCRYPTION_KEY"] = secrets.token_hex(16)
    if not merged.get("PIM_API_KEY"):
        merged["PIM_API_KEY"] = secrets.token_urlsafe(32)

    if merged != existing:
        _write_runtime_secrets(path, merged)

    return merged


def bootstrap_runtime_environment() -> None:
    """Create runtime directories and stable secrets without mutating backend/.env."""
    data_dir = os.path.expanduser(os.getenv("DATA_DIR") or _default_data_dir())
    os.makedirs(data_dir, exist_ok=True)
    runtime_secrets = _ensure_runtime_secrets(data_dir)

    # Environment values have highest priority for BaseSettings.
    os.environ.setdefault("DATA_DIR", data_dir)
    os.environ.setdefault("ENCRYPTION_KEY", runtime_secrets["ENCRYPTION_KEY"])
    os.environ.setdefault("PIM_API_KEY", runtime_secrets["PIM_API_KEY"])

    get_settings.cache_clear()


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def parse_cors_origins(raw: Optional[str]) -> list[str]:
    """Parse comma or newline separated CORS origins from env."""
    if not raw:
        return []

    origins: list[str] = []
    seen: set[str] = set()
    for chunk in str(raw).replace("\n", ",").split(","):
        origin = chunk.strip()
        if not origin or origin in seen:
            continue
        seen.add(origin)
        origins.append(origin)
    return origins
