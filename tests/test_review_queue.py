import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from guidelineops.database import (
    ReviewEventRow,
    ReviewTaskRow,
    create_session_factory,
    init_database,
)
from guidelineops.models import SourceRecord
from guidelineops.review_queue import (
    ReviewQueueError,
    claim_task,
    decide_task,
    event_mapping,
    list_review_events,
    sync_review_tasks,
)


def session() -> Session:
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    init_database(session_factory.kw["bind"])
    return session_factory()


def test_sync_creates_one_task_per_risk_and_duplicate() -> None:
    with session() as db_session:
        records = [
            SourceRecord(source="pubmed", source_record_id="1", title="COPD guideline"),
            SourceRecord(source="cnki", source_record_id="2", title="COPD guideline"),
        ]

        result = sync_review_tasks(db_session, records)
        db_session.commit()

        assert result.created == 7
        assert (
            db_session.scalar(select(func.count()).select_from(ReviewTaskRow)) == 7
        )
        assert (
            db_session.scalar(select(func.count()).select_from(ReviewEventRow)) == 7
        )


def test_sync_is_idempotent_and_supersedes_disappeared_active_signals() -> None:
    with session() as db_session:
        record = SourceRecord(source="pubmed", source_record_id="1", title="COPD")
        sync_review_tasks(db_session, [record])
        db_session.commit()

        repeat = sync_review_tasks(db_session, [record])
        vanished = sync_review_tasks(db_session, [])
        db_session.commit()

        assert repeat.created == 0
        assert repeat.superseded == 0
        assert vanished.superseded == 3
        assert (
            db_session.scalar(select(func.count()).select_from(ReviewEventRow)) == 6
        )
        assert {
            task.status for task in db_session.scalars(select(ReviewTaskRow))
        } == {"superseded"}


def test_claim_and_reject_require_owner_and_reason() -> None:
    with session() as db_session:
        sync_review_tasks(
            db_session,
            [SourceRecord(source="pubmed", source_record_id="1", title="COPD")],
        )
        task = db_session.scalar(select(ReviewTaskRow).order_by(ReviewTaskRow.id))
        assert task is not None

        claim_task(db_session, task.id, reviewer="李医生")
        with pytest.raises(ReviewQueueError, match="claimed by another reviewer"):
            decide_task(
                db_session,
                task.id,
                reviewer="王医生",
                decision="rejected",
                reason="非正式指南",
            )
        with pytest.raises(ReviewQueueError, match="reason is required"):
            decide_task(
                db_session,
                task.id,
                reviewer="李医生",
                decision="rejected",
                reason=" ",
            )

        decide_task(
            db_session,
            task.id,
            reviewer="李医生",
            decision="rejected",
            reason="非正式指南",
        )

        assert task.status == "rejected"
        assert task.claimed_by == "李医生"
        assert task.resolved_at is not None
        events = list_review_events(db_session, task.id)
        assert [event["event_type"] for event in map(event_mapping, events)] == [
            "synced",
            "claimed",
            "rejected",
        ]
        assert event_mapping(events[0])["created_at"].endswith("+00:00")


def test_review_sync_does_not_change_source_record_data() -> None:
    record = SourceRecord(
        source="pubmed",
        source_record_id="1",
        title="COPD",
    )
    before = record.model_dump(mode="json")

    with session() as db_session:
        sync_review_tasks(db_session, [record])

    assert record.model_dump(mode="json") == before
