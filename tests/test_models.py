from datetime import date

import pytest
from pydantic import ValidationError

from guidelineops.config import Settings
from guidelineops.models import (
    AccessStatus,
    DocumentType,
    ReviewStatus,
    SourceRecord,
)


def test_string_enums_expose_the_normalized_values() -> None:
    assert [item.value for item in DocumentType] == [
        "guideline",
        "consensus",
        "standard",
        "clinical_pathway",
        "expert_recommendation",
        "review",
        "other",
        "unknown",
    ]
    assert [item.value for item in AccessStatus] == [
        "open_download",
        "open_preview",
        "metadata_only",
        "restricted",
        "unknown",
    ]
    assert [item.value for item in ReviewStatus] == [
        "candidate",
        "verified",
        "rejected",
        "needs_review",
    ]


def test_source_record_requires_only_the_three_identity_fields() -> None:
    record = SourceRecord(id="r-1", source="pubmed", source_record_id="123")

    assert record.id == "r-1"
    assert record.source == "pubmed"
    assert record.source_record_id == "123"
    assert record.title is None
    assert record.title_normalized is None
    assert record.authors == []
    assert record.disease_tags == []
    assert record.document_type is DocumentType.unknown
    assert record.access_status is AccessStatus.unknown
    assert record.review_status is ReviewStatus.candidate
    assert record.metadata == {}


def test_source_record_normalizes_a_supplied_title_and_keeps_metadata() -> None:
    record = SourceRecord(
        id="r-2",
        source="crossref",
        source_record_id="10",
        title="  Ａ Clinical  指南  ",
        authors=["张三"],
        publication_date="2024-05-01",
        metadata={"source_payload": {"score": 1}},
    )

    assert record.title_normalized == "a clinical 指南"
    assert record.authors == ["张三"]
    assert record.publication_date == date(2024, 5, 1)
    assert record.metadata["source_payload"]["score"] == 1


def test_source_record_rejects_missing_identity_fields() -> None:
    with pytest.raises(ValidationError):
        SourceRecord(source="pubmed", source_record_id="123")


def test_settings_are_optional_and_have_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "NCBI_EMAIL",
        "NCBI_TOOL",
        "NCBI_API_KEY",
        "CROSSREF_MAILTO",
        "WANFANG_APP_KEY",
        "WANFANG_APP_SECRET",
        "DATABASE_URL",
        "DATA_DIR",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings()

    assert settings.ncbi_email is None
    assert settings.ncbi_tool == "guidelineops-cn"
    assert settings.ncbi_api_key is None
    assert settings.crossref_mailto is None
    assert settings.wanfang_app_key is None
    assert settings.wanfang_app_secret is None
    assert str(settings.database_url) == "sqlite:///./data/guidelineops.db"
    assert str(settings.data_dir) == "data"
