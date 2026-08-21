"""SQLite persistence for auditable source records and canonical groups."""

from __future__ import annotations

import hashlib
import json
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

from .knowledge import KnowledgeUnit
from .medication_safety import MedicationSafetyRule
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


class KnowledgeUnitRow(Base):
    """Persisted source-grounded knowledge unit awaiting medical governance."""

    __tablename__ = "knowledge_units"

    unit_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(String, nullable=False)
    source_locator: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    population: Mapped[str | None] = mapped_column(String)
    exclusions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_grade: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_rated"
    )
    recommendation_strength: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_applicable"
    )
    medical_review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft"
    )
    conflict_of_interest: Mapped[str | None] = mapped_column(String)
    tcm_pattern: Mapped[str | None] = mapped_column(String)
    western_concept: Mapped[str | None] = mapped_column(String)
    mapping_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_applicable"
    )
    mapped_unit_ids: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class KnowledgeRetractionRow(Base):
    """Append-only record explaining why a knowledge unit was withdrawn."""

    __tablename__ = "knowledge_retractions"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_units.unit_id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgeVersionRow(Base):
    """An immutable, approved snapshot of one medical knowledge version."""

    __tablename__ = "knowledge_versions"
    __table_args__ = (UniqueConstraint("unit_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_units.unit_id"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    frozen_by: Mapped[str] = mapped_column(String(255), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MedicationSafetyRuleRow(Base):
    """A source-grounded medication safety statement, never a prescription."""

    __tablename__ = "medication_safety_rules"

    rule_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_unit_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_units.unit_id"), nullable=False
    )
    medication_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    statement: Mapped[str] = mapped_column(String, nullable=False)
    source_locator: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    safety_review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft"
    )
    affected_population: Mapped[str | None] = mapped_column(String)
    related_medications: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


@event.listens_for(KnowledgeRetractionRow, "before_update")
def _reject_knowledge_retraction_update(
    mapper: object, connection: object, target: KnowledgeRetractionRow
) -> None:
    """Keep withdrawal evidence append-only at the ORM boundary."""

    raise ValueError(f"knowledge retraction {target.id} is immutable")


@event.listens_for(KnowledgeRetractionRow, "before_delete")
def _reject_knowledge_retraction_delete(
    mapper: object, connection: object, target: KnowledgeRetractionRow
) -> None:
    """Prevent deletion of recorded withdrawal evidence through ORM sessions."""

    raise ValueError(f"knowledge retraction {target.id} is immutable")


@event.listens_for(KnowledgeVersionRow, "before_update")
def _reject_knowledge_version_update(
    mapper: object, connection: object, target: KnowledgeVersionRow
) -> None:
    """Frozen knowledge snapshots cannot be altered through ORM sessions."""

    raise ValueError(f"knowledge version {target.id} is immutable")


@event.listens_for(KnowledgeVersionRow, "before_delete")
def _reject_knowledge_version_delete(
    mapper: object, connection: object, target: KnowledgeVersionRow
) -> None:
    """Frozen knowledge snapshots cannot be removed through ORM sessions."""

    raise ValueError(f"knowledge version {target.id} is immutable")


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


def upsert_knowledge_unit(session: Session, unit: KnowledgeUnit) -> KnowledgeUnitRow:
    """Persist one validated knowledge unit by stable unit ID."""

    payload = unit.model_dump(mode="json")
    row = session.get(KnowledgeUnitRow, unit.unit_id)
    if row is None:
        row = KnowledgeUnitRow(unit_id=unit.unit_id)
        session.add(row)
    for field in (
        "source_record_id",
        "domain",
        "statement",
        "source_locator",
        "version",
        "population",
        "exclusions",
        "evidence_grade",
        "recommendation_strength",
        "medical_review_status",
        "conflict_of_interest",
        "tcm_pattern",
        "western_concept",
        "mapping_type",
        "mapped_unit_ids",
    ):
        setattr(row, field, payload[field])
    session.flush()
    return row


def knowledge_unit_from_row(row: KnowledgeUnitRow) -> KnowledgeUnit:
    """Revalidate and reconstruct a domain model from persisted fields."""

    return KnowledgeUnit.model_validate(
        {
            "unit_id": row.unit_id,
            "source_record_id": row.source_record_id,
            "domain": row.domain,
            "statement": row.statement,
            "source_locator": row.source_locator,
            "version": row.version,
            "population": row.population,
            "exclusions": row.exclusions,
            "evidence_grade": row.evidence_grade,
            "recommendation_strength": row.recommendation_strength,
            "medical_review_status": row.medical_review_status,
            "conflict_of_interest": row.conflict_of_interest,
            "tcm_pattern": row.tcm_pattern,
            "western_concept": row.western_concept,
            "mapping_type": row.mapping_type,
            "mapped_unit_ids": row.mapped_unit_ids,
        }
    )


def submit_knowledge_unit(session: Session, unit_id: str) -> KnowledgeUnitRow:
    """Move a draft/rejected knowledge unit into the medical-review queue."""

    row = session.get(KnowledgeUnitRow, unit_id)
    if row is None:
        raise ValueError(f"knowledge unit not found: {unit_id}")
    if row.medical_review_status == "retracted":
        raise ValueError(f"knowledge unit is retracted: {unit_id}")
    row.medical_review_status = "pending"
    session.flush()
    return row


def retract_knowledge_unit(
    session: Session, unit_id: str, *, reason: str, actor: str
) -> list[KnowledgeUnitRow]:
    """Withdraw one unit and return every mapping-dependent unit it may affect."""

    reason = _require_nonblank(reason, "retraction reason")
    actor = _require_nonblank(actor, "retraction actor")
    row = session.get(KnowledgeUnitRow, unit_id)
    if row is None:
        raise ValueError(f"knowledge unit not found: {unit_id}")
    if row.medical_review_status == "retracted":
        raise ValueError(f"knowledge unit is already retracted: {unit_id}")

    row.medical_review_status = "retracted"
    session.add(KnowledgeRetractionRow(unit_id=unit_id, reason=reason, actor=actor))
    session.flush()
    return knowledge_impact(session, unit_id)


def knowledge_impact(session: Session, unit_id: str) -> list[KnowledgeUnitRow]:
    """Find transitive units whose mapping depends on the given unit ID."""

    rows = list(session.scalars(select(KnowledgeUnitRow)))
    pending_ids = [unit_id]
    seen_ids = {unit_id}
    impacted: list[KnowledgeUnitRow] = []
    while pending_ids:
        dependency_id = pending_ids.pop(0)
        for row in rows:
            if row.unit_id in seen_ids or dependency_id not in row.mapped_unit_ids:
                continue
            seen_ids.add(row.unit_id)
            pending_ids.append(row.unit_id)
            impacted.append(row)
    return sorted(impacted, key=lambda row: row.unit_id)


def freeze_knowledge_unit(
    session: Session, unit_id: str, *, actor: str
) -> KnowledgeVersionRow:
    """Create or return an immutable snapshot of an approved knowledge unit."""

    actor = _require_nonblank(actor, "freezing actor")
    row = session.get(KnowledgeUnitRow, unit_id)
    if row is None:
        raise ValueError(f"knowledge unit not found: {unit_id}")
    if row.medical_review_status != "approved":
        raise ValueError(f"knowledge unit must be approved before freezing: {unit_id}")
    existing = session.scalar(
        select(KnowledgeVersionRow).where(
            KnowledgeVersionRow.unit_id == unit_id,
            KnowledgeVersionRow.version == row.version,
        )
    )
    if existing is not None:
        return existing
    snapshot = knowledge_unit_from_row(row).model_dump(mode="json")
    snapshot_json = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    frozen = KnowledgeVersionRow(
        unit_id=unit_id,
        version=row.version,
        snapshot=snapshot,
        snapshot_sha256=hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest(),
        frozen_by=actor,
    )
    session.add(frozen)
    session.flush()
    return frozen


def upsert_medication_safety_rule(
    session: Session, rule: MedicationSafetyRule
) -> MedicationSafetyRuleRow:
    """Persist one validated medication safety statement by stable rule ID."""

    if session.get(KnowledgeUnitRow, rule.source_unit_id) is None:
        raise ValueError(f"source knowledge unit not found: {rule.source_unit_id}")
    payload = rule.model_dump(mode="json")
    row = session.get(MedicationSafetyRuleRow, rule.rule_id)
    if row is None:
        row = MedicationSafetyRuleRow(rule_id=rule.rule_id)
        session.add(row)
    for field in (
        "source_unit_id",
        "medication_name",
        "category",
        "risk_level",
        "statement",
        "source_locator",
        "version",
        "safety_review_status",
        "affected_population",
        "related_medications",
    ):
        setattr(row, field, payload[field])
    session.flush()
    return row


def submit_medication_safety_rule(
    session: Session, rule_id: str
) -> MedicationSafetyRuleRow:
    """Move one safety rule into the high-risk medical-review workflow."""

    row = session.get(MedicationSafetyRuleRow, rule_id)
    if row is None:
        raise ValueError(f"medication safety rule not found: {rule_id}")
    row.safety_review_status = "pending"
    session.flush()
    return row


def _require_nonblank(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} is required")
    return value


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
