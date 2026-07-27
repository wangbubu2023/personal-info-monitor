"""Application configuration management."""

import json
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> str:
    return os.path.join(Path.home(), ".pim", "data")


def _default_cors_origins() -> str:
    return ",".join(
        [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "http://localhost:1420",
            "http://127.0.0.1:1420",
        ]
    )


def effective_fetch_concurrency(settings: object) -> int:
    """Return the number of fetch pipelines allowed to run at once.

    ``FETCH_CONCURRENCY`` existed before fetch work shared a single uvicorn
    event loop with HTTP. Keep its historical 20-way default while exposing an
    independent activity cap for constrained hosts and incident mitigation.
    """

    configured = max(1, int(getattr(settings, "fetch_concurrency", 1) or 1))
    active_limit = max(1, int(getattr(settings, "fetch_active_limit", 20) or 20))
    return min(configured, active_limit)


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
    fetch_concurrency: int = Field(default=20, ge=1)  # Legacy/requested max parallel fetches
    # Emergency/operator activity cap, independent of the requested worker
    # count. Keep the historical 20-way throughput by default; lower this only
    # for constrained hosts or incident mitigation.
    fetch_active_limit: int = Field(default=20, ge=1, le=64)
    # Business timezone for user-facing calendar dates (digest/dashboard/hourly/email budgets).
    user_timezone: str = "Asia/Shanghai"
    # Backward-compatible scheduler setting; scheduler defaults should match USER_TIMEZONE.
    scheduler_timezone: str = "Asia/Shanghai"
    event_loop_slow_callback_seconds: float = 1.0
    event_loop_lag_probe_interval_seconds: float = 1.0
    job_lease_seconds: int = Field(default=120, ge=10, le=3600)
    job_heartbeat_seconds: int = Field(default=30, ge=2, le=600)
    fetch_stage_timeout_seconds: int = Field(default=900, ge=10, le=7200)
    postprocess_stage_timeout_seconds: int = Field(default=600, ge=10, le=7200)
    shutdown_grace_seconds: int = Field(default=30, ge=1, le=600)
    diagnostic_buffer_max: int = Field(default=2000, ge=10, le=100000)
    diagnostic_batch_size: int = Field(default=100, ge=1, le=10000)
    diagnostic_rotate_bytes: int = Field(default=10 * 1024 * 1024, ge=65536)
    diagnostic_disk_limit_bytes: int = Field(default=100 * 1024 * 1024, ge=65536)
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
    # Personal single-user Web deployments may trust the same-origin browser
    # UI and avoid recurring bootstrap prompts. API-key auth still applies to
    # non-browser clients. Set true for an Internet-facing multi-user boundary.
    pim_web_auth_required: bool = False
    # One-time shared secret guarding /local-token. Populated from runtime-secrets.json
    # on startup; distributed to trusted local callers (Tauri shell, operator CLI) via
    # the filesystem (file mode 0600), never exposed over HTTP.
    bootstrap_token: str = ""
    # Canonical browser-facing deployment URL. Besides generating one-click
    # bootstrap links, this origin is trusted automatically by both CORS and
    # the bootstrap exchange endpoint.
    pim_public_url: str = ""
    # Backward-compatible alias used by older deployments/CLI invocations.
    pim_public_origin: str = ""
    cors_origins: str = _default_cors_origins()
    # Per-IP (+ API key hint) sliding window for /api; 0 = disabled
    api_rate_limit_per_minute: int = 120
    #: Per-IP limit for ``GET /local-token`` (bootstrap); 0 = disabled
    local_token_rate_limit_per_minute: int = 30

    # Deployment-level emergency stop for all new outbound AI calls. Product-level
    # feature toggles live in system_settings and are resolved by app.platform.llm.policy.
    pim_ai_hard_disable: bool = False
    #: Rough daily cap on *estimated* LLM tokens (prompt + max output). ``0`` = unlimited.
    ai_daily_token_budget: int = 0
    #: Rough monthly cap on *estimated* LLM tokens (prompt + max output). ``0`` = unlimited.
    ai_monthly_token_budget: int = 0
    cloud_fallback_enabled: bool = True

    #: After this many consecutive fetch *errors*, auto-disable the source (``0`` = never).
    fetch_error_disable_threshold: int = 12
    #: Hard-disable password-based browser auto-login. Recommended for VPS/headless deployments
    #: that should only consume imported cookies/browser sessions.
    pim_disable_password_auto_login: bool = False

    # Web Clean Pipeline. The legacy extractor remains authoritative until
    # explicitly enabled; shadow mode only writes bounded diagnostics.
    pim_web_clean_enabled: bool = False
    pim_web_clean_shadow: bool = True
    pim_web_clean_write_metadata: bool = True
    pim_web_clean_use_sidecar: bool = False
    pim_web_clean_max_html_bytes: int = Field(default=3_000_000, ge=10_000, le=20_000_000)
    pim_web_clean_timeout_ms: int = Field(default=8_000, ge=100, le=60_000)
    pim_web_clean_template_enabled: bool = False

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


def _browser_origin(raw: str, *, setting_name: str) -> str:
    """Return the HTTP(S) origin represented by a public deployment URL."""
    value = raw.strip()
    if not value:
        return ""

    try:
        parsed = urlsplit(value)
        # Accessing ``port`` also validates malformed/out-of-range ports.
        parsed.port
    except ValueError as exc:
        raise CorsOriginConfigError(f"{setting_name} is not a valid URL: {exc}.") from exc

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise CorsOriginConfigError(
            f"{setting_name} must be an absolute http:// or https:// URL."
        )
    if parsed.username or parsed.password:
        raise CorsOriginConfigError(f"{setting_name} must not contain credentials.")

    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def effective_cors_origins(settings: object) -> list[str]:
    """Return explicit CORS entries plus configured public deployment origins.

    ``PIM_PUBLIC_URL`` is the canonical public browser address, so requiring an
    operator to repeat the same value in ``CORS_ORIGINS`` is both redundant and
    error-prone. Keep ``PIM_PUBLIC_ORIGIN`` as a compatibility alias.
    """
    origins = parse_cors_origins(getattr(settings, "cors_origins", ""))
    seen = {origin.lower() for origin in origins}
    for setting_name, raw in (
        ("PIM_PUBLIC_URL", getattr(settings, "pim_public_url", "")),
        ("PIM_PUBLIC_ORIGIN", getattr(settings, "pim_public_origin", "")),
    ):
        origin = _browser_origin(str(raw or ""), setting_name=setting_name)
        if origin and origin.lower() not in seen:
            origins.append(origin)
            seen.add(origin.lower())
    return origins
