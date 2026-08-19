from datetime import datetime

from sqlalchemy import func, select

from guidelineops.database import (
    CanonicalGuidelineRow,
    GuidelineSourceLinkRow,
    IngestionRunRow,
    SourceRecordRow,
    create_session_factory,
    init_database,
    upsert_source_record,
)
from guidelineops.models import SourceRecord


def make_record(**overrides: object) -> SourceRecord:
    values: dict[str, object] = {
        "source": "pubmed",
        "source_record_id": "1",
        "title": "Example guideline",
        "doi": "10.1000/example",
        "pmid": "1",
        "publication_year": 2024,
        "metadata": {"origin": "test"},
    }
    values.update(overrides)
    return SourceRecord(**values)


def test_upsert_is_idempotent_and_updates_metadata() -> None:
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    init_database(session_factory.kw["bind"])
    with session_factory() as session:
        upsert_source_record(session, make_record())
        upsert_source_record(session, make_record(title="Updated guideline"))
        session.commit()
        assert session.scalar(select(func.count()).select_from(SourceRecordRow)) == 1
        assert session.scalar(select(SourceRecordRow.title)) == "Updated guideline"


def test_grouping_persists_one_canonical_with_four_source_links() -> None:
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    init_database(session_factory.kw["bind"])
    with session_factory() as session:
        for index, source in enumerate(("pubmed", "crossref", "cnki", "wanfang")):
            upsert_source_record(
                session,
                make_record(source=source, source_record_id=str(index), pmid=None),
            )
        session.commit()
        assert (
            session.scalar(select(func.count()).select_from(CanonicalGuidelineRow)) == 1
        )
        assert (
            session.scalar(select(func.count()).select_from(GuidelineSourceLinkRow))
            == 4
        )


def test_doi_and_pmid_conflict_does_not_merge_distinct_existing_groups() -> None:
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    init_database(session_factory.kw["bind"])
    with session_factory() as session:
        upsert_source_record(session, make_record(doi="10.1/a", pmid="10"))
        upsert_source_record(
            session,
            make_record(
                source="crossref", source_record_id="2", doi="10.2/b", pmid="20"
            ),
        )
        upsert_source_record(
            session,
            make_record(source="cnki", source_record_id="3", doi="10.1/a", pmid="20"),
        )
        session.commit()
        assert (
            session.scalar(select(func.count()).select_from(CanonicalGuidelineRow)) == 2
        )


def test_ingestion_run_is_persisted() -> None:
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    init_database(session_factory.kw["bind"])
    with session_factory() as session:
        run = IngestionRunRow(source="pubmed", started_at=datetime.now())
        session.add(run)
        session.commit()
        assert session.scalar(select(func.count()).select_from(IngestionRunRow)) == 1
