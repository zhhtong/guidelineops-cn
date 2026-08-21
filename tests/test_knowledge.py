import pytest
from pydantic import ValidationError

from guidelineops.knowledge import (
    EvidenceGrade,
    KnowledgeDomain,
    KnowledgeReviewStatus,
    KnowledgeUnit,
    MappingType,
    RecommendationStrength,
    SourceLocator,
)


def test_knowledge_unit_captures_traceable_western_guideline_statement() -> None:
    unit = KnowledgeUnit(
        unit_id="ku-copd-001",
        source_record_id="pubmed:123",
        domain=KnowledgeDomain.western_medicine,
        statement="Offer smoking cessation support to adults with COPD.",
        source_locator=SourceLocator(page=12, section="Non-pharmacological care"),
        evidence_grade=EvidenceGrade.high,
        recommendation_strength=RecommendationStrength.strong,
        version="2024-1",
        population="Adults with confirmed COPD",
    )

    assert unit.source_locator.page == 12
    assert unit.medical_review_status is KnowledgeReviewStatus.draft
    assert unit.mapping_type is MappingType.not_applicable


def test_knowledge_unit_supports_tcm_mapping_without_equating_concepts() -> None:
    unit = KnowledgeUnit(
        unit_id="ku-copd-tcm-001",
        source_record_id="cnki:abc",
        domain=KnowledgeDomain.traditional_chinese_medicine,
        statement="痰热壅肺证宜清热化痰。",
        source_locator=SourceLocator(section="证治"),
        version="2024-1",
        tcm_pattern="痰热壅肺证",
        mapping_type=MappingType.conditional,
        mapped_unit_ids=["ku-copd-001"],
    )

    assert unit.tcm_pattern == "痰热壅肺证"
    assert unit.mapped_unit_ids == ["ku-copd-001"]


def test_knowledge_unit_rejects_untraceable_or_inconsistent_mapping() -> None:
    with pytest.raises(ValidationError):
        KnowledgeUnit(
            unit_id="ku-1",
            source_record_id="pubmed:1",
            domain="western_medicine",
            statement="A statement",
            source_locator=SourceLocator(),
            version="2024-1",
        )

    with pytest.raises(ValidationError):
        KnowledgeUnit(
            unit_id="ku-2",
            source_record_id="pubmed:1",
            domain="western_medicine",
            statement="A statement",
            source_locator=SourceLocator(section="Recommendations"),
            version="2024-1",
            mapping_type=MappingType.equivalent,
        )
