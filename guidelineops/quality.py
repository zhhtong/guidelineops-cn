"""Deterministic metadata quality reporting."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
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


def _generated_at_isoformat(generated_at: datetime) -> str:
    """Return an aware UTC ISO-8601 representation of a report timestamp."""

    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("QualityReport.generated_at must be timezone-aware")
    return generated_at.astimezone(timezone.utc).isoformat()


def _report_mapping(report: QualityReport) -> dict[str, object]:
    """Convert a report and all nested dataclasses into JSON-compatible values."""

    payload = asdict(report)
    payload["generated_at"] = _generated_at_isoformat(report.generated_at)
    return payload


def report_json(report: QualityReport) -> str:
    """Serialize a quality report as indented UTF-8-compatible JSON text."""

    return json.dumps(_report_mapping(report), ensure_ascii=False, indent=2) + "\n"


def _markdown_cell(value: object) -> str:
    """Escape values that could break a Markdown table cell."""

    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_count_table(
    headers: tuple[str, ...], rows: list[tuple[object, ...]]
) -> list[str]:
    """Render a simple right-aligned Markdown table."""

    separator = tuple("---:" if index else "---" for index in range(len(headers)))
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_markdown_cell(value) for value in row) + " |"
        for row in rows
    )
    return lines


def render_markdown(report: QualityReport) -> str:
    """Render counts, tables, and explicit empty review sections in Markdown."""

    lines = [
        "# Quality report",
        "",
        f"Generated at: {_generated_at_isoformat(report.generated_at)}",
        "",
        "## Headline counts",
        "",
        f"- Total records: {report.total_records}",
        f"- Canonical records: {report.canonical_records}",
        f"- Risk items: {len(report.risk_items)}",
        f"- Duplicate candidates: {len(report.duplicate_candidates)}",
        "",
        "## Source counts",
        "",
    ]
    lines.extend(
        _markdown_count_table(
            ("Source", "Count"),
            list(report.source_counts.items()),
        )
    )
    lines.extend(["", "## Review status counts", ""])
    lines.extend(
        _markdown_count_table(
            ("Review status", "Count"),
            list(report.review_status_counts.items()),
        )
    )
    lines.extend(["", "## Field completeness", ""])
    lines.extend(
        _markdown_count_table(
            ("Field", "Present", "Missing", "Rate"),
            [
                (field_name, value.present, value.missing, f"{value.rate:.1%}")
                for field_name, value in report.field_completeness.items()
            ],
        )
    )

    lines.extend(["", "## Risk items", ""])
    if report.risk_items:
        lines.extend(
            f"{index}. `{item.reason}` — {_markdown_cell(item.source)}"
            f":{_markdown_cell(item.source_record_id)} — {_markdown_cell(item.title)}"
            for index, item in enumerate(report.risk_items, start=1)
        )
    else:
        lines.append("No risk items found.")

    lines.extend(["", "## Duplicate candidates", ""])
    if report.duplicate_candidates:
        for index, candidate in enumerate(report.duplicate_candidates, start=1):
            score = (
                f", score={candidate.score:.2f}"
                if candidate.score is not None
                else ""
            )
            lines.append(
                f"{index}. `{_markdown_cell(candidate.left_source_record_id)}` ↔ "
                f"`{_markdown_cell(candidate.right_source_record_id)}` — "
                f"{_markdown_cell(candidate.kind)} ("
                f"{_markdown_cell(candidate.confidence)}"
                f"{score})"
            )
    else:
        lines.append("No duplicate candidates found.")

    return "\n".join(lines) + "\n"
