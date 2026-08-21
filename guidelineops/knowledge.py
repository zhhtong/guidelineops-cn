"""Traceable, reviewable medical knowledge-unit contracts.

These models describe extracted evidence for research and governance. They do
not generate diagnoses, prescriptions, or patient-specific recommendations.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class KnowledgeDomain(str, Enum):
    """Medical perspective represented by a knowledge unit."""

    western_medicine = "western_medicine"
    traditional_chinese_medicine = "traditional_chinese_medicine"
    integrative = "integrative"


class EvidenceGrade(str, Enum):
    """Evidence certainty recorded by a human or source methodologist."""

    high = "high"
    moderate = "moderate"
    low = "low"
    very_low = "very_low"
    not_rated = "not_rated"


class RecommendationStrength(str, Enum):
    """Strength of a source recommendation, separate from certainty."""

    strong = "strong"
    conditional = "conditional"
    consensus = "consensus"
    not_applicable = "not_applicable"


class KnowledgeReviewStatus(str, Enum):
    """Workflow status, never a claim of clinical validity."""

    draft = "draft"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    retracted = "retracted"


class MappingType(str, Enum):
    """Relationship between a unit and another biomedical/TCM unit."""

    equivalent = "equivalent"
    related = "related"
    conditional = "conditional"
    not_mappable = "not_mappable"
    not_applicable = "not_applicable"


class SourceLocator(BaseModel):
    """Location that lets a reviewer find the original statement."""

    model_config = ConfigDict(extra="forbid")

    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    table: str | None = None
    quote: str | None = None

    @field_validator("section", "table", "quote")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_location(self) -> SourceLocator:
        if not any((self.page, self.section, self.table, self.quote)):
            raise ValueError("source_locator requires page, section, table, or quote")
        return self


class KnowledgeUnit(BaseModel):
    """One source-grounded statement awaiting or undergoing human review."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str
    source_record_id: str
    domain: KnowledgeDomain
    statement: str
    source_locator: SourceLocator
    version: str
    population: str | None = None
    exclusions: list[str] = Field(default_factory=list)
    evidence_grade: EvidenceGrade = EvidenceGrade.not_rated
    recommendation_strength: RecommendationStrength = (
        RecommendationStrength.not_applicable
    )
    medical_review_status: KnowledgeReviewStatus = KnowledgeReviewStatus.draft
    conflict_of_interest: str | None = None
    tcm_pattern: str | None = None
    western_concept: str | None = None
    mapping_type: MappingType = MappingType.not_applicable
    mapped_unit_ids: list[str] = Field(default_factory=list)

    @field_validator("unit_id", "source_record_id", "statement", "version")
    @classmethod
    def require_nonblank_identity(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("knowledge-unit identity fields must not be empty")
        return value

    @field_validator(
        "population", "conflict_of_interest", "tcm_pattern", "western_concept"
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("exclusions", "mapped_unit_ids")
    @classmethod
    def normalize_id_lists(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("knowledge-unit lists must not contain blank values")
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def validate_mapping(self) -> KnowledgeUnit:
        has_mapping = bool(self.mapped_unit_ids)
        expects_mapping = self.mapping_type is not MappingType.not_applicable
        if has_mapping != expects_mapping:
            raise ValueError(
                "mapped_unit_ids must be present exactly when mapping_type is set"
            )
        return self
