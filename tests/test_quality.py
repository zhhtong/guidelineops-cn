from datetime import timezone

from guidelineops.models import ReviewStatus, SourceRecord
from guidelineops.quality import Completeness, build_quality_report


def test_build_quality_report_returns_zero_safe_empty_report() -> None:
    report = build_quality_report([], canonical_records=0)

    assert report.generated_at.tzinfo is not None
    assert report.generated_at.utcoffset() == timezone.utc.utcoffset(
        report.generated_at
    )
    assert report.total_records == 0
    assert report.canonical_records == 0
    assert report.source_counts == {}
    assert report.review_status_counts == {}
    assert set(report.field_completeness) == {
        "doi",
        "pmid",
        "publication_year",
        "source_url",
        "authors",
    }
    assert all(
        completeness.present == 0
        and completeness.missing == 0
        and completeness.rate == 0.0
        for completeness in report.field_completeness.values()
    )
    assert report.risk_items == []
    assert report.duplicate_candidates == []


def test_build_quality_report_counts_fields_statuses_and_risks() -> None:
    records = [
        SourceRecord(
            source="pubmed",
            source_record_id="1",
            title="COPD guideline",
            doi="10.1000/example",
            pmid="1",
            publication_year=2024,
            source_url="https://pubmed.ncbi.nlm.nih.gov/1/",
            authors=["Li"],
            review_status=ReviewStatus.verified,
        ),
        SourceRecord(
            source="cnki",
            source_record_id="2",
            title="COPD guideline",
            review_status=ReviewStatus.needs_review,
        ),
    ]

    report = build_quality_report(records, canonical_records=2)

    assert report.total_records == 2
    assert report.canonical_records == 2
    assert report.source_counts == {"cnki": 1, "pubmed": 1}
    assert report.review_status_counts == {"needs_review": 1, "verified": 1}
    assert list(report.source_counts) == sorted(report.source_counts)
    assert list(report.review_status_counts) == sorted(report.review_status_counts)
    assert report.field_completeness == {
        "doi": Completeness(1, 1, 0.5),
        "pmid": Completeness(1, 1, 0.5),
        "publication_year": Completeness(1, 1, 0.5),
        "source_url": Completeness(1, 1, 0.5),
        "authors": Completeness(1, 1, 0.5),
    }
    assert [item.reason for item in report.risk_items] == [
        "missing_publication_year",
        "missing_source_url",
        "missing_identifiers",
    ]
    assert report.risk_items[0].source == "cnki"
    assert report.risk_items[0].source_record_id == "2"
    assert report.risk_items[0].title == "COPD guideline"
    assert len(report.duplicate_candidates) == 1
    assert report.duplicate_candidates[0].kind == "exact_title"
