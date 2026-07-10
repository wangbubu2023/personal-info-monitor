"""Application configuration management."""

import json
import os
import secrets
import warnings
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
        # Operators often leave legacy/unknown keys in .env (JWT_SECRET_KEY
        # from earlier iterations, custom DEBUG_* flags, etc). Failing startup
        # on extras is needlessly brittle — we silently ignore them instead
        # and let the dedicated runtime-secrets file own the authoritative
        # security-sensitive values.
        extra="ignore",
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
    scheduler_timezone: str = "Asia/Shanghai"
    event_loop_slow_callback_seconds: float = 1.0
    event_loop_lag_probe_interval_seconds: float = 1.0
    pim_ui_upgrade_args: str = ""
    pim_update_check_repo: str = "wangbubu2023/personal-info-monitor"
    pim_update_check_github_token: str = ""
    pim_update_check_timeout_seconds: float = 4.0

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
    # One-time shared secret guarding /local-token. Populated from runtime-secrets.json
    # on startup; distributed to trusted local callers (Tauri shell, operator CLI) via
    # the filesystem (file mode 0600), never exposed over HTTP.
    bootstrap_token: str = ""
    cors_origins: str = _default_cors_origins()
    # Per-IP (+ API key hint) sliding window for /api; 0 = disabled
    api_rate_limit_per_minute: int = 120
    #: Per-IP limit for ``GET /local-token`` (bootstrap); 0 = disabled
    local_token_rate_limit_per_minute: int = 30

    # Master kill switch for outbound LLM calls (summaries, translation, digest
    # selection, etc.). The legacy ``AI_PROCESSING_ENABLED`` env name is still
    # accepted but now serves only as the *master* gate; new deployments configure
    # the per-feature ``ENRICH_*`` toggles below and leave this flag at its
    # ``False`` default. Phase 7 of the modular refactor cleaned the
    # "AI_PROCESSING_ENABLED is the only switch" narrative out of the docs and
    # runtime paths — the flag is no longer slated for removal.
    ai_processing_enabled: bool = False
    #: Rough daily cap on *estimated* LLM tokens (prompt + max output). ``0`` = unlimited.
    ai_daily_token_budget: int = 0
    #: Rough monthly cap on *estimated* LLM tokens (prompt + max output). ``0`` = unlimited.
    ai_monthly_token_budget: int = 0
    cloud_fallback_enabled: bool = True

    # Phase 4 step 8 introduces the ``ENRICH_*`` family — per-feature toggles for the
    # post-ingest enrichment pipeline. Defaults match historical behavior:
    #
    # * ``enrich_auto_on_ingest`` — whether the ingest finalizer should enqueue an
    #   automatic summary/translate pass for every freshly-inserted Content row.
    #   Default ``False`` matches current production (the auto-enrich pipeline
    #   does not yet exist; Phase 4/5 will wire it up).
    # * ``enrich_summary_enabled`` — gate for :class:`Summarizer` text generation.
    # * ``enrich_translate_enabled`` — gate for :class:`Translator` LLM calls.
    #   New installs keep outbound LLM calls off until the operator opts in.
    enrich_auto_on_ingest: bool = False
    enrich_summary_enabled: bool = False
    enrich_translate_enabled: bool = False

    #: After this many consecutive fetch *errors*, auto-disable the source (``0`` = never).
    fetch_error_disable_threshold: int = 12
    #: Hard-disable password-based browser auto-login. Recommended for VPS/headless deployments
    #: that should only consume imported cookies/browser sessions.
    pim_disable_password_auto_login: bool = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Expand ~ but leave filesystem bootstrap to explicit runtime entrypoints.
        self.data_dir = os.path.expanduser(self.data_dir)

        # Soft-deprecation notice for the legacy ``AI_PROCESSING_ENABLED`` env name.
        # The flag still functions as the master kill switch (see field docstring
        # above), so we no longer threaten removal — we just nudge operators toward
        # the ENRICH_* family for fine-grained control. The single-emit guard
        # prevents warning spam inside ``get_settings.cache_clear()`` loops.
        if (
            os.environ.get("AI_PROCESSING_ENABLED") is not None
            and not os.environ.get("_PIM_AI_DEPRECATION_LOGGED")
        ):
            warnings.warn(
                "AI_PROCESSING_ENABLED is the legacy master kill switch; per-feature "
                "gates moved to ENRICH_AUTO_ON_INGEST / ENRICH_SUMMARY_ENABLED / "
                "ENRICH_TRANSLATE_ENABLED. The master flag is still honored; "
                "prefer the ENRICH_* family for fine-grained control "
                "(see backend/.env.example).",
                DeprecationWarning,
                stacklevel=2,
            )
            os.environ["_PIM_AI_DEPRECATION_LOGGED"] = "1"

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
        if not self.bootstrap_token:
            self.bootstrap_token = secrets.token_urlsafe(32)


_RUNTIME_SECRETS_FILENAME = "runtime-secrets.json"


class RuntimeSecretsError(RuntimeError):
    """Raised when runtime-secrets.json exists but cannot be safely read.

    We fail closed instead of regenerating: silently minting a new
    ENCRYPTION_KEY would make every previously-encrypted credential
    undecryptable and rotate PIM_API_KEY out from under existing clients.
    A corrupt file almost always means a truncated write or disk issue, not
    "start fresh", so we stop and let the operator restore or delete it.
    """


def _runtime_secrets_path(data_dir: str) -> Path:
    return Path(data_dir).expanduser() / _RUNTIME_SECRETS_FILENAME


_RUNTIME_SECRETS_RECOVERY = (
    "Refusing to regenerate secrets (that would orphan encrypted credentials "
    "and invalidate the API key). Restore the file from backup, or — only if "
    "you have no encrypted data to keep — delete it to mint fresh secrets."
)


def _read_runtime_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeSecretsError(
            f"Cannot read runtime secrets at {path}: {exc}. {_RUNTIME_SECRETS_RECOVERY}"
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeSecretsError(
            f"Runtime secrets at {path} are not valid JSON: {exc}. {_RUNTIME_SECRETS_RECOVERY}"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeSecretsError(
            f"Runtime secrets at {path} must be a JSON object. {_RUNTIME_SECRETS_RECOVERY}"
        )

    return {
        "ENCRYPTION_KEY": str(payload.get("ENCRYPTION_KEY") or "").strip(),
        "PIM_API_KEY": str(payload.get("PIM_API_KEY") or "").strip(),
        "BOOTSTRAP_TOKEN": str(payload.get("BOOTSTRAP_TOKEN") or "").strip(),
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
    if not merged.get("BOOTSTRAP_TOKEN"):
        merged["BOOTSTRAP_TOKEN"] = secrets.token_urlsafe(32)

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
    os.environ.setdefault("BOOTSTRAP_TOKEN", runtime_secrets["BOOTSTRAP_TOKEN"])

    get_settings.cache_clear()


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


class CorsOriginConfigError(ValueError):
    """Raised when CORS_ORIGINS contains insecure values."""


def parse_cors_origins(raw: Optional[str]) -> list[str]:
    """Parse comma or newline separated CORS origins from env.

    Raises CorsOriginConfigError on insecure values (``*`` wildcard or malformed
    scheme). Since ``allow_credentials=True`` is required for the Tauri shell,
    a wildcard ``*`` would either be silently neutered by Starlette or would
    widen the auth surface dangerously — we fail-fast instead of both.
    """
    if not raw:
        return []

    origins: list[str] = []
    seen: set[str] = set()
    for chunk in str(raw).replace("\n", ",").split(","):
        origin = chunk.strip()
        if not origin or origin in seen:
            continue
        if origin == "*":
            raise CorsOriginConfigError(
                "CORS_ORIGINS contains a wildcard '*', which is incompatible with "
                "allow_credentials=True. Please list explicit origins instead."
            )
        if "*" in origin:
            raise CorsOriginConfigError(
                f"CORS_ORIGINS entry '{origin}' contains a wildcard; only exact origins are supported."
            )
        if not (origin.startswith("http://") or origin.startswith("https://") or origin.startswith("tauri://")):
            raise CorsOriginConfigError(
                f"CORS_ORIGINS entry '{origin}' must start with http://, https:// or tauri://."
            )
        seen.add(origin)
        origins.append(origin)
    return origins
