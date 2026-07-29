"""Pydantic schemas for Source model."""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from urllib.parse import urlparse

from app.utils.url import normalize_source_url_input
from app.domains.score.score_utils import normalize_authority_type
from app.domains.fetch.web_clean.templates import TemplateValidationError, validate_template

_MAX_FETCH_LAG_MIN = 1
_MAX_FETCH_LAG_MAX = 525600  # 365 days


def _normalize_source_quality_metadata(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not meta:
        return meta
    out = dict(meta)

    if "source_stars" in out and out.get("source_stars") is not None:
        try:
            out["source_stars"] = max(1, min(3, int(out["source_stars"])))
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata.source_stars must be 1, 2, or 3") from exc

    if "source_weight" in out and out.get("source_weight") is not None:
        try:
            weight = float(out["source_weight"])
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata.source_weight must be a number") from exc
        out["source_weight"] = max(0.5, min(1.5, weight))

    if "domain_focus" in out and out.get("domain_focus") is not None:
        raw_focus = out.get("domain_focus")
        if isinstance(raw_focus, str):
            focus = [x.strip() for x in re.split(r"[,\n，、]+", raw_focus) if x.strip()]
        elif isinstance(raw_focus, list):
            focus = [str(x).strip() for x in raw_focus if str(x).strip()]
        else:
            raise ValueError("metadata.domain_focus must be a list or comma-separated string")
        out["domain_focus"] = focus[:20]

    if "authority_type" in out and out.get("authority_type") is not None:
        out["authority_type"] = normalize_authority_type(out["authority_type"])[:80]

    if "web_clean_mode" in out and out.get("web_clean_mode") is not None:
        mode = str(out["web_clean_mode"]).strip().lower()
        if mode not in {"off", "shadow", "write"}:
            raise ValueError("metadata.web_clean_mode must be off, shadow, or write")
        out["web_clean_mode"] = mode

    if "web_clean_template" in out and out.get("web_clean_template") is not None:
        template = out["web_clean_template"]
        if not isinstance(template, dict):
            raise ValueError("metadata.web_clean_template must be an object")
        try:
            validate_template(template)
        except TemplateValidationError as exc:
            raise ValueError(
                "metadata.web_clean_template is invalid: " + "; ".join(exc.errors)
            ) from exc

    return out


def _validate_max_fetch_lag_in_metadata(meta: Optional[Dict[str, Any]]) -> None:
    if not meta:
        return
    lag = meta.get("max_fetch_lag_minutes")
    if lag is None:
        return
    try:
        n = int(lag)
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata.max_fetch_lag_minutes must be an integer") from exc
    if n < _MAX_FETCH_LAG_MIN or n > _MAX_FETCH_LAG_MAX:
        raise ValueError(
            f"metadata.max_fetch_lag_minutes must be between {_MAX_FETCH_LAG_MIN} and {_MAX_FETCH_LAG_MAX}"
        )


class SourceBase(BaseModel):
    """Base schema for Source."""
    
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., pattern="^(website|rss|x|youtube|podcast)$")
    url: str = Field(..., min_length=1)
    extra_urls: List[str] = Field(default_factory=list)
    fetch_interval: int = Field(default=60, ge=15, le=1440)  # 15 min to 24 hours
    enabled: bool = True
    use_keyword_filter: bool = False
    auth_required: bool = False
    auth_config_id: Optional[UUID] = None
    metadata_: Optional[Dict[str, Any]] = Field(default_factory=dict, alias="metadata")

    @field_validator("metadata_")
    @classmethod
    def validate_metadata_lag(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        v = _normalize_source_quality_metadata(v)
        _validate_max_fetch_lag_in_metadata(v)
        return v

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v: str) -> str:
        v = normalize_source_url_input(v)
        if not v:
            raise ValueError("URL is required")
        if not urlparse(v).netloc:
            raise ValueError("URL must include a valid host")
        return v

    @field_validator("extra_urls")
    @classmethod
    def validate_extra_urls_format(cls, v: List[str]) -> List[str]:
        out: List[str] = []
        for item in v:
            item = normalize_source_url_input(item)
            if not item:
                continue
            if not urlparse(item).netloc:
                raise ValueError("Each extra URL must include a valid host")
            out.append(item)
        return out


class SourceCreate(SourceBase):
    """Schema for creating a new Source."""
    pass


class SourceUpdate(BaseModel):
    """Schema for updating a Source."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    type: Optional[str] = Field(None, pattern="^(website|rss|x|youtube|podcast)$")
    url: Optional[str] = Field(None, min_length=1)
    extra_urls: Optional[List[str]] = None
    fetch_interval: Optional[int] = Field(None, ge=15, le=1440)
    enabled: Optional[bool] = None
    use_keyword_filter: Optional[bool] = None
    auth_required: Optional[bool] = None
    auth_config_id: Optional[UUID] = None
    metadata_: Optional[Dict[str, Any]] = Field(None, alias="metadata")

    @field_validator("metadata_")
    @classmethod
    def validate_metadata_lag_update(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        v = _normalize_source_quality_metadata(v)
        _validate_max_fetch_lag_in_metadata(v)
        return v

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = normalize_source_url_input(v)
        if not v:
            raise ValueError("URL is required")
        if not urlparse(v).netloc:
            raise ValueError("URL must include a valid host")
        return v

    @field_validator("extra_urls")
    @classmethod
    def validate_extra_urls_format(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        out: List[str] = []
        for item in v:
            item = normalize_source_url_input(item)
            if not item:
                continue
            if not urlparse(item).netloc:
                raise ValueError("Each extra URL must include a valid host")
            out.append(item)
        return out


class SourceResponse(SourceBase):
    """Schema for Source response."""
    
    id: UUID
    last_fetched_at: Optional[datetime] = None
    last_content_id: Optional[str] = None
    last_error: Optional[str] = None
    error_count: int = 0
    content_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SourceListResponse(BaseModel):
    """Schema for paginated Source list response."""
    
    items: List[SourceResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class SourceBulkImport(BaseModel):
    """Schema for bulk importing sources."""
    
    sources: List[SourceCreate]


class SourceExport(BaseModel):
    """Schema for exporting sources."""
    
    sources: List[SourceResponse]
    exported_at: datetime
