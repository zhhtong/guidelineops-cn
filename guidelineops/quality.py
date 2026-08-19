"""Deterministic metadata quality reporting."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from .dedup import DuplicateCandidate, group_records
from .models import SourceRecord

_COMPLETENESS_FIELDS = (
    "doi",
    "pmid",
    "publication_year",
    "source_url",
    "authors",
)


@dataclass(frozen=True)
class Completeness:
    """Presence counts and rate for one metadata field."""

    present: int
    missing: int
    rate: float


@dataclass(frozen=True)
class RiskItem:
    """A source record metadata issue requiring review."""

    source: str
    source_record_id: str
    title: str
    reason: str


@dataclass(frozen=True)
class QualityReport:
    """Deterministic quality signals for source-level records."""

    generated_at: datetime
    total_records: int
    canonical_records: int
    source_counts: dict[str, int]
    review_status_counts: dict[str, int]
    field_completeness: dict[str, Completeness]
    risk_items: list[RiskItem]
    duplicate_candidates: list[DuplicateCandidate]


def _is_present(value: object) -> bool:
    """Return whether a metadata value counts as present."""

    return value is not None and value != "" and value != []


def _field_completeness(
    records: list[SourceRecord], field_name: str
) -> Completeness:
    total = len(records)
    present = sum(
        _is_present(getattr(record, field_name))
        for record in records
    )
    missing = total - present
    rate = present / total if total else 0.0
    return Completeness(present=present, missing=missing, rate=rate)


def build_quality_report(
    records: list[SourceRecord], *, canonical_records: int
) -> QualityReport:
    """Calculate deterministic data-quality signals without modifying records."""

    source_counts = dict(sorted(Counter(record.source for record in records).items()))
    review_status_counts = dict(
        sorted(
            Counter(record.review_status.value for record in records).items()
        )
    )
    field_completeness = {
        field_name: _field_completeness(records, field_name)
        for field_name in _COMPLETENESS_FIELDS
    }

    risk_items: list[RiskItem] = []
    for record in records:
        if record.publication_year is None:
            risk_items.append(
                RiskItem(
                    source=record.source,
                    source_record_id=record.source_record_id,
                    title=record.title,
                    reason="missing_publication_year",
                )
            )
        if not _is_present(record.source_url):
            risk_items.append(
                RiskItem(
                    source=record.source,
                    source_record_id=record.source_record_id,
                    title=record.title,
                    reason="missing_source_url",
                )
            )
        if not _is_present(record.doi) and not _is_present(record.pmid):
            risk_items.append(
                RiskItem(
                    source=record.source,
                    source_record_id=record.source_record_id,
                    title=record.title,
                    reason="missing_identifiers",
                )
            )

    return QualityReport(
        generated_at=datetime.now(timezone.utc),
        total_records=len(records),
        canonical_records=canonical_records,
        source_counts=source_counts,
        review_status_counts=review_status_counts,
        field_completeness=field_completeness,
        risk_items=risk_items,
        duplicate_candidates=group_records(records).candidates,
    )
