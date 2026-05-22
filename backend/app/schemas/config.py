"""Pydantic schemas for API and Auth configuration."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


# API Config Schemas
class APIConfigBase(BaseModel):
    """Base schema for API Config."""
    platform: str = Field(..., description="Platform name: openai, youtube, x_twitter, etc.")
    name: Optional[str] = Field(None, description="User-defined name for this config")


class APIConfigCreate(APIConfigBase):
    """Schema for creating API Config."""
    api_key: Optional[str] = Field(None, description="The API key (will be encrypted); omit for Ollama")
    api_secret: Optional[str] = Field(None, description="API secret if required")
    additional_config: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_api_key_unless_ollama(self):
        plat = (self.platform or "").strip().lower()
        key = (self.api_key or "").strip()
        if plat != "ollama" and not key:
            raise ValueError("api_key is required for this platform")
        return self


class APIConfigUpdate(BaseModel):
    """Schema for updating API Config."""
    name: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    additional_config: Optional[Dict[str, Any]] = None


class APIConfigResponse(APIConfigBase):
    """Schema for API Config response (without sensitive data)."""
    id: UUID
    status: str
    last_used_at: Optional[datetime] = None
    rate_limit_info: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    # Show masked key for display
    masked_key: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# Auth Config Schemas (for website authentication)
class AuthConfigBase(BaseModel):
    """Base schema for Auth Config."""
    name: Optional[str] = Field(None, description="User-defined name for this auth config")
    site_url: str = Field(..., description="Website URL")
    auth_type: str = Field(default="password", description="password, api_key, oauth, cookie")
    login_url: Optional[str] = Field(None, description="Login page URL")
    is_shared: bool = Field(default=False, description="Whether this auth config is reusable across sources")


class AuthConfigCreate(AuthConfigBase):
    """Schema for creating Auth Config."""
    username: Optional[str] = None
    password: Optional[str] = None
    cookies: Optional[Union[Dict[str, str], str]] = None
    bind_all_x_sources: bool = True
    login_selectors: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="CSS selectors for login form elements"
    )


class AuthConfigUpdate(BaseModel):
    """Schema for updating Auth Config."""
    name: Optional[str] = None
    site_url: Optional[str] = None
    auth_type: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    cookies: Optional[Union[Dict[str, str], str]] = None
    login_url: Optional[str] = None
    login_selectors: Optional[Dict[str, str]] = None
    is_shared: Optional[bool] = None
    bind_all_x_sources: Optional[bool] = None


class AuthConfigResponse(AuthConfigBase):
    """Schema for Auth Config response."""
    id: UUID
    status: str
    last_validated_at: Optional[datetime] = None
    login_selectors: Dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    # Don't expose credentials in response
    has_credentials: bool = False
    bound_source_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class BrowserSessionCreate(BaseModel):
    """Create/update a persistent browser session profile."""

    site_url: str
    profile_name: Optional[str] = None
    auth_config_id: Optional[UUID] = None
    auto_bind_sources: bool = True


class BrowserSessionOpenLoginRequest(BaseModel):
    """Bootstrap persistent browser profile (MVP: optional cookie seeding + page open).

    When ``headless`` is False, ``dwell_seconds`` is the **upper bound**: the
    server waits until the user closes the browser window (capturing the
    login state), or until the timeout fires. Bump the default/upper limit
    for manual-login flows (NYT, WSJ, …) that need time for captchas/2FA.
    """

    headless: bool = True
    bootstrap_auth_cookies: bool = True
    dwell_seconds: int = Field(default=180, ge=0, le=900)
    sync_cookies_to_auth_config: bool = True


class BrowserSessionValidateRequest(BaseModel):
    """Validate whether session can access first-party article page."""

    test_url: Optional[str] = None
    min_article_paragraphs: int = Field(default=3, ge=0, le=50)
    wait_ms: int = Field(default=3500, ge=0, le=30000)
    sync_cookies_to_auth_config: bool = True


class BrowserSessionResponse(BaseModel):
    """Browser session API response."""

    id: UUID
    site_url: str
    site_host: str
    profile_name: str
    user_data_dir: str
    storage_state_path: Optional[str] = None
    auth_config_id: Optional[UUID] = None
    status: str
    last_validated_at: Optional[datetime] = None
    last_error: Optional[str] = None
    metadata_: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# AI Model Config Schemas
class AIModelConfig(BaseModel):
    """Schema for AI model configuration."""
    provider: str = Field(..., description="openai, ollama, anthropic, etc.")
    model: str = Field(..., description="Model name: gpt-4o-mini, llama2, etc.")
    api_base: Optional[str] = Field(None, description="Custom API base URL (for Ollama)")
    api_key: Optional[str] = Field(None, description="API key if required")
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1000, ge=1)
    ollama_num_ctx: Optional[int] = Field(None, ge=1024, le=262144, description="Ollama context window (num_ctx)")
    ollama_no_think: Optional[bool] = Field(None, description="Append /no_think for Ollama models")


class AIModelConfigResponse(BaseModel):
    """Schema for AI model config response."""
    provider: str
    model: str
    api_base: Optional[str] = None
    temperature: float
    max_tokens: int
    ollama_num_ctx: Optional[int] = None
    ollama_no_think: Optional[bool] = None
    has_api_key: bool = False


class TranslationModelConfig(BaseModel):
    """Schema for translation model configuration."""

    provider: str = Field(..., description="openai, ollama, anthropic, etc.")
    model: str = Field(..., description="Model name")
    api_base: Optional[str] = Field(None, description="Custom API base URL (for Ollama)")
    api_key: Optional[str] = Field(None, description="API key if required")
    ollama_num_ctx: Optional[int] = Field(None, ge=1024, le=262144, description="Ollama context window (num_ctx)")
    ollama_no_think: Optional[bool] = Field(None, description="Append /no_think for Ollama models")


class TranslationModelConfigResponse(BaseModel):
    """Schema for translation model config response."""

    provider: str
    model: str
    api_base: Optional[str] = None
    ollama_num_ctx: Optional[int] = None
    ollama_no_think: Optional[bool] = None
    has_api_key: bool = False


class AtomModelConfig(BaseModel):
    """Schema for news atom extraction model configuration."""

    provider: str = Field(..., description="openai, ollama, anthropic, etc.")
    model: str = Field(default="", description="Model name; empty means fallback to ai_model")
    api_base: Optional[str] = Field(None, description="Custom API base URL (for Ollama)")
    api_key: Optional[str] = Field(None, description="API key if required")
    temperature: float = Field(default=0.1, ge=0, le=2)
    max_tokens: int = Field(default=4000, ge=1)
    ollama_num_ctx: Optional[int] = Field(None, ge=1024, le=262144, description="Ollama context window (num_ctx)")
    ollama_no_think: Optional[bool] = Field(None, description="Append /no_think for Ollama models")


class AtomModelConfigResponse(BaseModel):
    """Schema for atom model config response."""

    provider: str
    model: str
    api_base: Optional[str] = None
    temperature: float
    max_tokens: int
    ollama_num_ctx: Optional[int] = None
    ollama_no_think: Optional[bool] = None
    has_api_key: bool = False


class SystemLimitsConfig(BaseModel):
    """Schema for runtime limits."""

    max_sources: int = Field(default=200, ge=1, le=5000)
    max_digest_candidates: int = Field(default=12, ge=3, le=30)
    max_hourly_digest_input_items: int = Field(default=200, ge=20, le=2000)


HourlyDigestContentType = Literal["website", "rss", "x", "youtube", "podcast"]


class HourlyDigestSettings(BaseModel):
    """简报窗口：统一任务提示词（选稿+综述）、扫描类型与窗口长度。"""

    prompt: str = Field(
        default="",
        max_length=8000,
        description="选稿与写综述时模型须遵循的说明；空则后端使用内置默认。",
    )
    prompt_effective: str | None = Field(
        default=None,
        description="API 响应只读：合并自定义/旧版字段/内置默认后的实际任务提示词。",
    )
    content_types: List[HourlyDigestContentType] = Field(
        default_factory=lambda: ["website", "rss"],
        description="参与简报扫描的入库类型（content_type）。",
    )
    window_hours: int = Field(
        default=3,
        ge=1,
        le=24,
        description="简报覆盖的已完成小时窗口，默认 3 小时。",
    )


class FallbackModelPick(BaseModel):
    """Provider + model id for fallback paths (credentials via 模型接入)."""

    provider: str = "openai"
    model: str = "gpt-4o-mini"


class SystemSettings(BaseModel):
    """Schema for system-wide settings."""
    ai_model: AIModelConfig
    translation_model: Optional[TranslationModelConfig] = None
    atom_model: Optional[AtomModelConfig] = None
    translation_enabled: bool = True
    auto_translate_language: str = "zh-CN"
    summarization_enabled: bool = True
    translation_fallback_enabled: bool = False
    translation_fallback: FallbackModelPick = Field(default_factory=FallbackModelPick)
    summarization_fallback_enabled: bool = False
    summarization_fallback: FallbackModelPick = Field(default_factory=FallbackModelPick)
    translation_cloud_fallback_enabled: bool = False
    summarization_cloud_fallback_enabled: bool = False
    email_notifications_enabled: bool = False
    limits: SystemLimitsConfig = Field(default_factory=SystemLimitsConfig)
    hourly_digest: HourlyDigestSettings = Field(default_factory=HourlyDigestSettings)


class SystemSettingsResponse(BaseModel):
    """Schema for system settings response."""
    ai_model: AIModelConfigResponse
    translation_model: Optional[TranslationModelConfigResponse] = None
    atom_model: Optional[AtomModelConfigResponse] = None
    translation_enabled: bool
    auto_translate_language: str
    summarization_enabled: bool
    translation_fallback_enabled: bool
    translation_fallback: FallbackModelPick
    summarization_fallback_enabled: bool
    summarization_fallback: FallbackModelPick
    translation_cloud_fallback_enabled: bool
    summarization_cloud_fallback_enabled: bool
    email_notifications_enabled: bool
    limits: SystemLimitsConfig
    hourly_digest: HourlyDigestSettings
