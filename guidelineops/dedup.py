"""Conservative, explainable grouping of source-level records."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz.fuzz import ratio

from .models import SourceRecord


@dataclass(frozen=True)
class CanonicalGroup:
    """One automatically grouped canonical work."""

    source_record_ids: tuple[str, ...]


@dataclass(frozen=True)
class DuplicateCandidate:
    """A review-only duplicate suggestion; it never changes grouping."""

    left_source_record_id: str
    right_source_record_id: str
    kind: str
    confidence: str
    score: float | None = None


@dataclass(frozen=True)
class GroupingResult:
    """Automatic canonical groups plus reviewable, non-destructive candidates."""

    canonical_groups: tuple[CanonicalGroup, ...]
    candidates: list[DuplicateCandidate]


def _identity(record: SourceRecord) -> str:
    return f"{record.source}:{record.source_record_id}"


def group_records(records: list[SourceRecord]) -> GroupingResult:
    """Group only unambiguous DOI, PMID, and source-identity matches.

    When a later record would bridge two established identifier groups, DOI has
    deterministic precedence and groups remain separate for human review.
    """

    groups: list[list[SourceRecord]] = []
    by_source_identity: dict[tuple[str, str], int] = {}
    by_doi: dict[str, int] = {}
    by_pmid: dict[str, int] = {}

    for record in records:
        source_key = (record.source, record.source_record_id)
        targets = {
            index
            for index in (
                by_source_identity.get(source_key),
                by_doi.get(record.doi) if record.doi else None,
                by_pmid.get(record.pmid) if record.pmid else None,
            )
            if index is not None
        }
        if not targets:
            target = len(groups)
            groups.append([])
        elif len(targets) == 1:
            target = targets.pop()
        elif record.doi and record.doi in by_doi:
            target = by_doi[record.doi]
        elif record.pmid and record.pmid in by_pmid:
            target = by_pmid[record.pmid]
        else:
            target = min(targets)
        groups[target].append(record)
        by_source_identity[source_key] = target
        if record.doi:
            by_doi.setdefault(record.doi, target)
        if record.pmid:
            by_pmid.setdefault(record.pmid, target)

    candidates: list[DuplicateCandidate] = []
    for left_index, left in enumerate(records):
        for right in records[left_index + 1 :]:
            if _same_group(left, right, by_source_identity):
                continue
            if left.title_normalized == right.title_normalized:
                candidates.append(
                    DuplicateCandidate(
                        _identity(left), _identity(right), "exact_title", "high"
                    )
                )
                continue
            if (
                left.publication_year is not None
                and right.publication_year is not None
                and abs(left.publication_year - right.publication_year) <= 1
            ):
                score = ratio(left.title_normalized, right.title_normalized)
                if score >= 95:
                    candidates.append(
                        DuplicateCandidate(
                            _identity(left),
                            _identity(right),
                            "fuzzy_title",
                            "possible",
                            score,
                        )
                    )

    return GroupingResult(
        tuple(
            CanonicalGroup(tuple(_identity(item) for item in group)) for group in groups
        ),
        candidates,
    )


def _same_group(
    left: SourceRecord,
    right: SourceRecord,
    groups: dict[tuple[str, str], int],
) -> bool:
    return (
        groups[(left.source, left.source_record_id)]
        == groups[(right.source, right.source_record_id)]
    )
