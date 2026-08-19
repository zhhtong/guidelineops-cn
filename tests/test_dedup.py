from guidelineops.dedup import group_records
from guidelineops.models import SourceRecord


def make_record(**overrides: object) -> SourceRecord:
    values: dict[str, object] = {
        "source": "pubmed",
        "source_record_id": "1",
        "title": "Guideline for Chronic Disease",
        "publication_year": 2024,
    }
    values.update(overrides)
    return SourceRecord(**values)


def test_same_doi_forms_one_canonical_group() -> None:
    records = [
        make_record(source=source, source_record_id=str(index), doi="10.1000/same")
        for index, source in enumerate(("pubmed", "crossref", "cnki", "wanfang"))
    ]
    result = group_records(records)
    assert len(result.canonical_groups) == 1
    assert len(result.canonical_groups[0].source_record_ids) == 4


def test_exact_normalized_title_is_review_candidate_not_merge() -> None:
    result = group_records(
        [
            make_record(doi="10.1/a"),
            make_record(source="crossref", source_record_id="2", doi="10.1/b"),
        ]
    )
    assert len(result.canonical_groups) == 2
    assert result.candidates[0].kind == "exact_title"
    assert result.candidates[0].confidence == "high"


def test_similar_title_with_nearby_year_is_possible_candidate() -> None:
    result = group_records(
        [
            make_record(title="Guideline for Chronic Disease", doi="10.1/a"),
            make_record(
                source="crossref",
                source_record_id="2",
                title="Guideline for Chronic Diseases",
                doi="10.1/b",
                publication_year=2025,
            ),
        ]
    )
    assert len(result.canonical_groups) == 2
    assert result.candidates[0].kind == "fuzzy_title"
    assert result.candidates[0].confidence == "possible"


def test_different_doi_and_distant_year_are_not_grouped_or_candidates() -> None:
    result = group_records(
        [
            make_record(doi="10.1/a", publication_year=2019),
            make_record(
                source="crossref",
                source_record_id="2",
                doi="10.1/b",
                title="Unrelated treatment recommendation",
                publication_year=2025,
            ),
        ]
    )
    assert len(result.canonical_groups) == 2
    assert result.candidates == []
