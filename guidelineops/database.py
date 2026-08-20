"""SQLite persistence for auditable source records and canonical groups."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    event,
    select,
)
from sqlalchemy import create_engine as _create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from .models import SourceRecord


class Base(DeclarativeBase):
    """Base for GuidelineOps persistence tables."""


class SourceRecordRow(Base):
    __tablename__ = "source_records"
    __table_args__ = (UniqueConstraint("source", "source_record_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    title_normalized: Mapped[str] = mapped_column(String, nullable=False)
    doi: Mapped[str | None] = mapped_column(String(512))
    pmid: Mapped[str | None] = mapped_column(String(64))
    publication_year: Mapped[int | None]
    record_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    links: Mapped[list[GuidelineSourceLinkRow]] = relationship(
        back_populates="source_record"
    )


class CanonicalGuidelineRow(Base):
    __tablename__ = "canonical_guidelines"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    links: Mapped[list[GuidelineSourceLinkRow]] = relationship(
        back_populates="canonical"
    )


class GuidelineSourceLinkRow(Base):
    __tablename__ = "guideline_source_links"
    __table_args__ = (UniqueConstraint("canonical_guideline_id", "source_record_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_guideline_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_guidelines.id"), nullable=False
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id"), nullable=False
    )
    canonical: Mapped[CanonicalGuidelineRow] = relationship(back_populates="links")
    source_record: Mapped[SourceRecordRow] = relationship(back_populates="links")


class IngestionRunRow(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )


class ReviewTaskRow(Base):
    """A current human-review task generated from a quality signal."""

    __tablename__ = "review_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(
        String(1024), unique=True, nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    claimed_by: Mapped[str | None] = mapped_column(String(255))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    events: Mapped[list[ReviewEventRow]] = relationship(back_populates="task")


class ReviewEventRow(Base):
    """An immutable audit event for one review-task workflow action."""

    __tablename__ = "review_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("review_tasks.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    task: Mapped[ReviewTaskRow] = relationship(back_populates="events")


@event.listens_for(ReviewEventRow, "before_update")
def _reject_review_event_update(
    mapper: object, connection: object, target: ReviewEventRow
) -> None:
    """Keep the audit trail append-only at the ORM boundary."""

    raise ValueError(f"review event {target.id} is immutable")


@event.listens_for(ReviewEventRow, "before_delete")
def _reject_review_event_delete(
    mapper: object, connection: object, target: ReviewEventRow
) -> None:
    """Prevent deletion of audit events through ORM sessions."""

    raise ValueError(f"review event {target.id} is immutable")


def create_engine(database_url: str = "sqlite+pysqlite:///guidelineops.db") -> Engine:
    """Create a SQLAlchemy 2 engine suitable for SQLite."""

    engine = _create_engine(database_url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine


def create_session_factory(
    database_url: str = "sqlite+pysqlite:///guidelineops.db",
) -> sessionmaker[Session]:
    """Create a non-expiring session factory; call :func:`init_database` once."""

    return sessionmaker(create_engine(database_url), expire_on_commit=False)


def init_database(engine: Engine) -> None:
    """Create all persistence tables if they do not exist."""

    Base.metadata.create_all(engine)


def upsert_source_record(session: Session, record: SourceRecord) -> SourceRecordRow:
    """Persist one record idempotently and attach it to a canonical group.

    Existing `(source, source_record_id)` rows are updated in place.  New rows
    join exactly one matching DOI or PMID canonical group.  Conflicting DOI and
    PMID matches keep existing groups intact, with DOI taking precedence.
    """

    row = session.scalar(
        select(SourceRecordRow).where(
            SourceRecordRow.source == record.source,
            SourceRecordRow.source_record_id == record.source_record_id,
        )
    )
    if row is None:
        # Assign non-nullable bibliographic fields before the first flush.  The
        # session may autoflush while resolving a matching canonical record.
        row = SourceRecordRow(
            source=record.source,
            source_record_id=record.source_record_id,
            title=record.title,
            title_normalized=record.title_normalized or record.title,
        )
        session.add(row)
    row.title = record.title
    row.title_normalized = record.title_normalized or record.title
    row.doi = record.doi
    row.pmid = record.pmid
    row.publication_year = record.publication_year
    row.record_data = record.model_dump(mode="json")
    session.flush()

    link = session.scalar(
        select(GuidelineSourceLinkRow).where(
            GuidelineSourceLinkRow.source_record_id == row.id
        )
    )
    if link is None:
        canonical = _matching_canonical(session, record)
        if canonical is None:
            canonical = CanonicalGuidelineRow()
            session.add(canonical)
            session.flush()
        session.add(GuidelineSourceLinkRow(canonical=canonical, source_record=row))
    return row


def _matching_canonical(
    session: Session, record: SourceRecord
) -> CanonicalGuidelineRow | None:
    def matches(column: Any, value: str | None) -> list[CanonicalGuidelineRow]:
        if not value:
            return []
        return list(
            session.scalars(
                select(CanonicalGuidelineRow)
                .join(GuidelineSourceLinkRow)
                .join(SourceRecordRow)
                .where(column == value)
                .distinct()
            )
        )

    doi_matches = matches(SourceRecordRow.doi, record.doi)
    pmid_matches = matches(SourceRecordRow.pmid, record.pmid)
    all_matches = {item.id: item for item in [*doi_matches, *pmid_matches]}
    if len(all_matches) <= 1:
        return next(iter(all_matches.values()), None)
    return doi_matches[0] if doi_matches else pmid_matches[0]
