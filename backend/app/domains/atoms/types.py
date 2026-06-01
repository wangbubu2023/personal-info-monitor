"""Pydantic models for normalized news atoms (Schema v2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.atoms.vocab import (
    AtomStatus,
    AtomType,
    ChinaStance,
    DataSourceType,
    Domain,
    Intensity,
    PeriodType,
    PoliticalSpectrum,
    RelationDirection,
    RelationType,
    Role,
    Sentiment,
    SubjectType,
    Unit,
    Validity,
    WhatType,
)


class WhoEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: SubjectType


class InfoAtomPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    when: str | None = None
    where: str | None = None
    who: list[WhoEntry] = Field(min_length=1)
    why: str | None = None
    what_type: WhatType
    what: str = Field(min_length=1)
    how: str | None = None
    result: str | None = None
    entities: list[str] = Field(min_length=1)
    validity: Validity


class OpinionAtomPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    who: list[WhoEntry] = Field(min_length=1)
    role: Role
    say_what: str = Field(min_length=1)
    is_quote: bool
    context: str | None = None
    sentiment: Sentiment
    intensity: Intensity
    political_spectrum: PoliticalSpectrum | None = None
    china_stance: ChinaStance | None = None


class DataAtomPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_org: str = Field(min_length=1)
    source_type: DataSourceType
    metric: str = Field(min_length=1)
    value: float
    unit: Unit
    caliber: str | None = None
    period: str = Field(min_length=1)
    period_type: PeriodType
    is_relative: bool
    base_value: float | None = None
    base_period: str | None = None
    validity: Validity




AtomPayload = Union[InfoAtomPayload, OpinionAtomPayload, DataAtomPayload]


class AtomBaseFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: str
    source_url: str
    source_sentence: str = Field(min_length=1)
    domain: Domain
    atom_source: str = Field(min_length=1)
    source_credibility: float = Field(ge=0.0, le=1.0)
    fact_confidence: float = Field(ge=0.0, le=1.0)
    verified: bool = False


class AtomCreate(AtomBaseFields):
    atom_type: AtomType
    payload: InfoAtomPayload | OpinionAtomPayload | DataAtomPayload
    canonical_text: str | None = None
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_flags: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    extraction_run_id: str | None = None

    @model_validator(mode="after")
    def payload_matches_type(self) -> AtomCreate:
        expected = {
            AtomType.INFO: InfoAtomPayload,
            AtomType.OPINION: OpinionAtomPayload,
            AtomType.DATA: DataAtomPayload,
        }[self.atom_type]
        if not isinstance(self.payload, expected):
            raise ValueError(f"payload type mismatch for atom_type={self.atom_type!r}")
        return self


class AtomUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Domain | None = None
    atom_source: str | None = None
    source_credibility: float | None = Field(default=None, ge=0.0, le=1.0)
    fact_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verified: bool | None = None
    payload: InfoAtomPayload | OpinionAtomPayload | DataAtomPayload | None = None


class AtomRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    atom_id: str
    content_id: str
    atom_type: AtomType
    domain: Domain
    source_sentence: str
    source_url: str
    atom_source: str
    payload: dict[str, Any]
    verified: bool
    source_credibility: float
    fact_confidence: float
    schema_version: int
    status: AtomStatus = AtomStatus.ACTIVE
    is_latest: bool = True
    supersedes_atom_id: str | None = None
    superseded_by_atom_id: str | None = None
    reconcile_group_id: str | None = None
    canonical_text: str | None = None
    quality_score: float | None = None
    quality_flags: list[str] = Field(default_factory=list)
    evidence_count: int = 1
    tags: list[str] = Field(default_factory=list)
    extraction_run_id: str | None = None
    reconcile_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class AtomListResponse(BaseModel):
    items: list[AtomRecord]
    total: int
    page: int
    page_size: int


class AtomStatsResponse(BaseModel):
    total: int
    by_type: dict[str, int]
    by_domain: dict[str, int]
    verified_count: int
    unverified_count: int


class AtomQualityResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    total_atoms: int
    active_atoms: int
    shadow_atoms: int
    superseded_atoms: int
    conflicted_atoms: int
    archived_atoms: int
    rejected_atoms: int
    short_sentence_rate: float
    avg_atoms_per_content: float
    p95_atoms_per_content: int
    p99_atoms_per_content: int
    max_atoms_per_content: int
    top_sources_by_atom_count: dict[str, int]
    fact_confidence_histogram: dict[str, int]
    quality_flags_distribution: dict[str, int]
    rejected_by_reason: dict[str, int]


class AtomBackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=500, ge=1, le=5000)
    since: str | None = None
    content_id: str | None = None
    dry_run: bool = False


class AtomBackfillResponse(BaseModel):
    job_id: str
    status: str


class AtomBackfillStatusResponse(BaseModel):
    job_id: str
    status: str
    processed: int
    total: int
    errors: list[str]
    created_at: str
    finished_at: str | None = None


class AtomizeResponse(BaseModel):
    content_id: str
    ok: bool


class RelationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom_a: str = Field(min_length=1)
    atom_b: str = Field(min_length=1)
    relation_type: RelationType
    direction: RelationDirection
    fact_confidence: float = Field(ge=0.0, le=1.0)
    verified: bool = False


class RelationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_type: RelationType | None = None
    direction: RelationDirection | None = None
    fact_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verified: bool | None = None


class RelationRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rel_id: str
    atom_a: str
    atom_b: str
    relation_type: RelationType
    direction: RelationDirection
    verified: bool
    fact_confidence: float
    created_at: datetime
    updated_at: datetime


class RelationListResponse(BaseModel):
    items: list[RelationRecord]
    total: int = 0
    page: int = 1
    page_size: int = 20


class RelationReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=1000, ge=1, le=5000)
    since: str | None = None
    atom_id: str | None = None
    dry_run: bool = False


class RelationReconcileResponse(BaseModel):
    job_id: str
    status: str


class RelationReconcileStatusResponse(BaseModel):
    job_id: str
    status: str
    processed: int
    total: int
    relations_created: int
    errors: list[str]
    created_at: str
    finished_at: str | None = None


def payload_from_dict(atom_type: AtomType, data: dict[str, Any]) -> InfoAtomPayload | OpinionAtomPayload | DataAtomPayload:
    if atom_type == AtomType.INFO:
        return InfoAtomPayload.model_validate(data)
    if atom_type == AtomType.OPINION:
        return OpinionAtomPayload.model_validate(data)
    return DataAtomPayload.model_validate(data)


def record_to_create(record: AtomRecord) -> AtomCreate:
    return AtomCreate(
        content_id=record.content_id,
        source_url=record.source_url,
        source_sentence=record.source_sentence,
        domain=record.domain,
        atom_source=record.atom_source,
        source_credibility=record.source_credibility,
        fact_confidence=record.fact_confidence,
        verified=record.verified,
        atom_type=record.atom_type,
        payload=payload_from_dict(record.atom_type, record.payload),
        canonical_text=record.canonical_text,
        quality_score=record.quality_score,
        quality_flags=list(record.quality_flags),
        tags=list(record.tags),
        extraction_run_id=record.extraction_run_id,
    )
