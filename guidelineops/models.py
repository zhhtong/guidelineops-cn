"""Validated, normalized metadata models."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .normalization import normalize_doi, normalize_title


class DocumentType(str, Enum):
    """Broad source-document categories used during review."""

    guideline = "guideline"
    consensus = "consensus"
    standard = "standard"
    clinical_pathway = "clinical_pathway"
    expert_recommendation = "expert_recommendation"
    review = "review"
    other = "other"
    unknown = "unknown"


class AccessStatus(str, Enum):
    """Availability of the source metadata or document."""

    open_download = "open_download"
    open_preview = "open_preview"
    metadata_only = "metadata_only"
    restricted = "restricted"
    unknown = "unknown"


class ReviewStatus(str, Enum):
    """Human review state for a discovered source record."""

    candidate = "candidate"
    verified = "verified"
    rejected = "rejected"
    needs_review = "needs_review"


class SourceRecord(BaseModel):
    """A source-level bibliographic record with auditable provenance."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    source: str
    source_record_id: str
    title: str | None = None
    title_normalized: str | None = None
    authors: list[str] = Field(default_factory=list)
    organization: str | None = None
    journal: str | None = None
    publication_year: int | None = None
    publication_date: date | None = None
    document_type: DocumentType = DocumentType.unknown
    disease_tags: list[str] = Field(default_factory=list)
    doi: str | None = None
    pmid: str | None = None
    abstract: str | None = None
    source_url: str | None = None
    access_status: AccessStatus = AccessStatus.unknown
    language: str | None = None
    raw_path: Path | None = None
    raw_sha256: str | None = None
    retrieved_at: datetime | None = None
    review_status: ReviewStatus = ReviewStatus.candidate
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def derive_normalized_values(self) -> SourceRecord:
        """Keep derived title/DOI values consistent with their source fields."""

        if self.id is None and self.title is None:
            raise ValueError("at least one of id or title is required")
        self.title_normalized = normalize_title(self.title)
        self.doi = normalize_doi(self.doi)
        return self
