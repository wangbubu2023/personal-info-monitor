"""Pydantic schemas for API and Auth configuration."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# API Config Schemas
class APIConfigBase(BaseModel):
    """Base schema for API Config."""
    platform: str = Field(..., description="Platform name: openai, youtube, x_twitter, etc.")
    name: Optional[str] = Field(None, description="User-defined name for this config")


class APIConfigCreate(APIConfigBase):
    """Schema for creating API Config."""
    api_key: str = Field(..., description="The API key (will be encrypted)")
    api_secret: Optional[str] = Field(None, description="API secret if required")
    additional_config: Optional[Dict[str, Any]] = Field(default_factory=dict)


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
    """Bootstrap persistent browser profile (MVP: optional cookie seeding + page open)."""

    headless: bool = True
    bootstrap_auth_cookies: bool = True
    dwell_seconds: int = Field(default=8, ge=0, le=120)


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


class AIModelConfigResponse(BaseModel):
    """Schema for AI model config response."""
    provider: str
    model: str
    api_base: Optional[str] = None
    temperature: float
    max_tokens: int
    has_api_key: bool = False


class TranslationModelConfig(BaseModel):
    """Schema for translation model configuration."""

    provider: str = Field(..., description="openai, ollama, anthropic, etc.")
    model: str = Field(..., description="Model name")
    api_base: Optional[str] = Field(None, description="Custom API base URL (for Ollama)")
    api_key: Optional[str] = Field(None, description="API key if required")


class TranslationModelConfigResponse(BaseModel):
    """Schema for translation model config response."""

    provider: str
    model: str
    api_base: Optional[str] = None
    has_api_key: bool = False


class SystemLimitsConfig(BaseModel):
    """Schema for runtime limits."""

    max_sources: int = Field(default=200, ge=1, le=5000)
    max_digest_candidates: int = Field(default=12, ge=3, le=30)
    max_hourly_digest_input_items: int = Field(default=200, ge=20, le=2000)


class SystemSettings(BaseModel):
    """Schema for system-wide settings."""
    ai_model: AIModelConfig
    translation_model: Optional[TranslationModelConfig] = None
    translation_enabled: bool = True
    auto_translate_language: str = "zh-CN"
    summarization_enabled: bool = True
    translation_cloud_fallback_enabled: bool = False
    summarization_cloud_fallback_enabled: bool = False
    email_notifications_enabled: bool = False
    limits: SystemLimitsConfig = Field(default_factory=SystemLimitsConfig)


class SystemSettingsResponse(BaseModel):
    """Schema for system settings response."""
    ai_model: AIModelConfigResponse
    translation_model: Optional[TranslationModelConfigResponse] = None
    translation_enabled: bool
    auto_translate_language: str
    summarization_enabled: bool
    translation_cloud_fallback_enabled: bool
    summarization_cloud_fallback_enabled: bool
    email_notifications_enabled: bool
    limits: SystemLimitsConfig
