"""Deterministic review-task synchronization and audited state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .database import KnowledgeUnitRow, ReviewEventRow, ReviewTaskRow
from .models import SourceRecord
from .quality import build_quality_report

_ACTIVE_STATUSES = {"open", "claimed", "deferred"}
_DECISIONS = {"approved", "rejected", "deferred"}
_TASK_STATUSES = _ACTIVE_STATUSES | _DECISIONS | {"superseded"}
_METADATA_TRIAGE = {
    "missing_publication_year": {
        "risk_level": "low",
        "required_reviewer_role": "data_curator",
        "medical_review_required": False,
    },
    "missing_source_url": {
        "risk_level": "medium",
        "required_reviewer_role": "evidence_curator",
        "medical_review_required": False,
    },
    "missing_identifiers": {
        "risk_level": "medium",
        "required_reviewer_role": "evidence_curator",
        "medical_review_required": False,
    },
}
_DUPLICATE_TRIAGE = {
    "risk_level": "medium",
    "required_reviewer_role": "medical_reviewer",
    "medical_review_required": True,
}


class ReviewQueueError(ValueError):
    """Raised when a review workflow action is not allowed."""


@dataclass(frozen=True)
class ReviewSignal:
    """A quality signal normalized into one stable review task."""

    fingerprint: str
    task_type: str
    payload: dict[str, object]


@dataclass(frozen=True)
class SyncResult:
    """Counts reported after an idempotent review-task synchronization."""

    created: int
    refreshed: int
    superseded: int


def review_signals(records: list[SourceRecord]) -> list[ReviewSignal]:
    """Create deterministic task signals from existing quality rules."""

    report = build_quality_report(records, canonical_records=0)
    signals: list[ReviewSignal] = []
    for item in report.risk_items:
        payload = {
            "source": item.source,
            "source_record_id": item.source_record_id,
            "title": item.title,
            "reason": item.reason,
            "triage": _METADATA_TRIAGE[item.reason],
        }
        signals.append(
            ReviewSignal(
                fingerprint=f"risk:{item.source}:{item.source_record_id}:{item.reason}",
                task_type="metadata_risk",
                payload=payload,
            )
        )
    for candidate in report.duplicate_candidates:
        left, right = sorted(
            (candidate.left_source_record_id, candidate.right_source_record_id)
        )
        signals.append(
            ReviewSignal(
                fingerprint=f"duplicate:{candidate.kind}:{left}:{right}",
                task_type="duplicate_candidate",
                payload={
                    "left_source_record_id": left,
                    "right_source_record_id": right,
                    "kind": candidate.kind,
                    "confidence": candidate.confidence,
                    "score": candidate.score,
                    "triage": _DUPLICATE_TRIAGE,
                },
            )
        )
    return signals


def sync_review_tasks(session: Session, records: list[SourceRecord]) -> SyncResult:
    """Create, refresh, or supersede tasks without changing source records."""

    now = datetime.utcnow()
    signals = review_signals(records)
    signal_by_fingerprint = {signal.fingerprint: signal for signal in signals}
    tasks = list(session.scalars(select(ReviewTaskRow).order_by(ReviewTaskRow.id)))
    existing = {task.fingerprint: task for task in tasks}
    created = 0
    refreshed = 0
    superseded = 0

    for signal in signals:
        task = existing.get(signal.fingerprint)
        if task is None:
            task = ReviewTaskRow(
                fingerprint=signal.fingerprint,
                task_type=signal.task_type,
                status="open",
                payload=signal.payload,
                last_seen_at=now,
            )
            session.add(task)
            session.flush()
            _add_event(session, task, event_type="synced", actor="system")
            created += 1
        else:
            task.payload = signal.payload
            task.last_seen_at = now
            task.updated_at = now
            refreshed += 1

    for task in tasks:
        if (
            task.fingerprint not in signal_by_fingerprint
            and task.status in _ACTIVE_STATUSES
        ):
            task.status = "superseded"
            task.updated_at = now
            _add_event(session, task, event_type="superseded", actor="system")
            superseded += 1

    session.flush()
    return SyncResult(created=created, refreshed=refreshed, superseded=superseded)


def sync_knowledge_review_tasks(session: Session) -> SyncResult:
    """Create medical-review tasks for knowledge units submitted as pending."""

    units = list(
        session.scalars(
            select(KnowledgeUnitRow)
            .where(KnowledgeUnitRow.medical_review_status == "pending")
            .order_by(KnowledgeUnitRow.unit_id)
        )
    )
    fingerprints = {
        f"knowledge:{unit.unit_id}:{unit.version}" for unit in units
    }
    tasks = list(
        session.scalars(
            select(ReviewTaskRow).where(
                ReviewTaskRow.task_type == "knowledge_medical_review"
            )
        )
    )
    existing = {task.fingerprint: task for task in tasks}
    created = 0
    refreshed = 0
    superseded = 0
    now = datetime.utcnow()

    for unit in units:
        fingerprint = f"knowledge:{unit.unit_id}:{unit.version}"
        payload = {
            "unit_id": unit.unit_id,
            "source_record_id": unit.source_record_id,
            "domain": unit.domain,
            "statement": unit.statement,
            "version": unit.version,
            "triage": {
                "risk_level": "high",
                "required_reviewer_role": "medical_reviewer",
                "medical_review_required": True,
            },
        }
        task = existing.get(fingerprint)
        if task is None:
            task = ReviewTaskRow(
                fingerprint=fingerprint,
                task_type="knowledge_medical_review",
                status="open",
                payload=payload,
                last_seen_at=now,
            )
            session.add(task)
            session.flush()
            _add_event(session, task, event_type="synced", actor="system")
            created += 1
        else:
            task.payload = payload
            task.last_seen_at = now
            task.updated_at = now
            if task.status in _DECISIONS | {"superseded"}:
                task.status = "open"
                task.claimed_by = None
                task.claimed_at = None
                task.resolved_at = None
                _add_event(session, task, event_type="reopened", actor="system")
            refreshed += 1

    for task in tasks:
        if task.fingerprint not in fingerprints and task.status in _ACTIVE_STATUSES:
            task.status = "superseded"
            task.updated_at = now
            _add_event(session, task, event_type="superseded", actor="system")
            superseded += 1

    session.flush()
    return SyncResult(created=created, refreshed=refreshed, superseded=superseded)


def list_review_tasks(
    session: Session, *, status: str | None = None
) -> list[ReviewTaskRow]:
    """Return tasks in stable ID order, optionally filtered by state."""

    statement = select(ReviewTaskRow).order_by(ReviewTaskRow.id)
    if status is not None:
        _require_status(status)
        statement = statement.where(ReviewTaskRow.status == status)
    return list(session.scalars(statement))


def list_review_events(session: Session, task_id: int) -> list[ReviewEventRow]:
    """Return append-only audit events for one task in insertion order."""

    _task_or_error(session, task_id)
    return list(
        session.scalars(
            select(ReviewEventRow)
            .where(ReviewEventRow.task_id == task_id)
            .order_by(ReviewEventRow.id)
        )
    )


def claim_task(
    session: Session,
    task_id: int,
    *,
    reviewer: str,
    reviewer_role: str | None = None,
) -> ReviewTaskRow:
    """Claim one open or deferred task for the named reviewer."""

    reviewer = _require_nonblank(reviewer, "reviewer")
    task = _task_or_error(session, task_id)
    reviewer_role = _resolved_reviewer_role(task, reviewer_role)
    _require_reviewer_role(task, reviewer_role)
    if task.status not in {"open", "deferred"}:
        raise ReviewQueueError(f"task {task_id} cannot be claimed from {task.status}")
    now = datetime.utcnow()
    result = session.execute(
        update(ReviewTaskRow)
        .where(
            ReviewTaskRow.id == task_id,
            ReviewTaskRow.status.in_(("open", "deferred")),
        )
        .values(
            status="claimed",
            claimed_by=reviewer,
            claimed_at=now,
            resolved_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount != 1:
        session.refresh(task)
        raise ReviewQueueError(f"task {task_id} cannot be claimed from {task.status}")
    session.refresh(task)
    _add_event(
        session,
        task,
        event_type="claimed",
        actor=reviewer,
        payload={"reviewer_role": reviewer_role},
    )
    session.flush()
    return task


def decide_task(
    session: Session,
    task_id: int,
    *,
    reviewer: str,
    reviewer_role: str | None = None,
    decision: str,
    reason: str | None = None,
) -> ReviewTaskRow:
    """Record a reviewer-owned approval, rejection, or deferral."""

    reviewer = _require_nonblank(reviewer, "reviewer")
    if decision not in _DECISIONS:
        raise ReviewQueueError(f"unsupported decision: {decision}")
    if decision in {"rejected", "deferred"}:
        reason = _require_nonblank(reason, "reason")
    elif reason is not None:
        reason = reason.strip() or None

    task = _task_or_error(session, task_id)
    reviewer_role = _resolved_reviewer_role(task, reviewer_role)
    _require_reviewer_role(task, reviewer_role)
    if task.status != "claimed":
        raise ReviewQueueError(f"task {task_id} is not claimed")
    if task.claimed_by != reviewer:
        raise ReviewQueueError(f"task {task_id} is claimed by another reviewer")

    now = datetime.utcnow()
    values: dict[str, object] = {"status": decision, "updated_at": now}
    if decision == "deferred":
        values.update(claimed_by=None, claimed_at=None, resolved_at=None)
    else:
        values["resolved_at"] = now
    result = session.execute(
        update(ReviewTaskRow)
        .where(
            ReviewTaskRow.id == task_id,
            ReviewTaskRow.status == "claimed",
            ReviewTaskRow.claimed_by == reviewer,
        )
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount != 1:
        session.refresh(task)
        if task.status != "claimed":
            raise ReviewQueueError(f"task {task_id} is not claimed")
        raise ReviewQueueError(f"task {task_id} is claimed by another reviewer")
    session.refresh(task)
    _update_knowledge_review_status(session, task, decision)
    _add_event(
        session,
        task,
        event_type=decision,
        actor=reviewer,
        reason=reason,
        payload={"reviewer_role": reviewer_role},
    )
    session.flush()
    return task


def task_mapping(task: ReviewTaskRow) -> dict[str, object]:
    """Return a JSON-compatible, externally safe representation of a task."""

    triage = _task_triage(task)
    return {
        "id": task.id,
        "fingerprint": task.fingerprint,
        "task_type": task.task_type,
        "status": task.status,
        "payload": task.payload,
        "risk_level": triage["risk_level"],
        "required_reviewer_role": triage["required_reviewer_role"],
        "medical_review_required": triage["medical_review_required"],
        "claimed_by": task.claimed_by,
        "claimed_at": _isoformat(task.claimed_at),
        "resolved_at": _isoformat(task.resolved_at),
        "created_at": _isoformat(task.created_at),
        "updated_at": _isoformat(task.updated_at),
        "last_seen_at": _isoformat(task.last_seen_at),
    }


def event_mapping(event: ReviewEventRow) -> dict[str, object]:
    """Return a JSON-compatible representation of one audit event."""

    return {
        "id": event.id,
        "task_id": event.task_id,
        "event_type": event.event_type,
        "actor": event.actor,
        "reason": event.reason,
        "payload": event.payload,
        "created_at": _isoformat(event.created_at),
    }


def _add_event(
    session: Session,
    task: ReviewTaskRow,
    *,
    event_type: str,
    actor: str,
    reason: str | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    session.add(
        ReviewEventRow(
            task=task,
            event_type=event_type,
            actor=actor,
            reason=reason,
            payload=payload or {},
        )
    )


def _task_or_error(session: Session, task_id: int) -> ReviewTaskRow:
    task = session.get(ReviewTaskRow, task_id)
    if task is None:
        raise ReviewQueueError(f"review task not found: {task_id}")
    return task


def _require_nonblank(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise ReviewQueueError(f"{field_name} is required")
    return value.strip()


def _require_status(status: str) -> None:
    if status not in _TASK_STATUSES:
        allowed = ", ".join(sorted(_TASK_STATUSES))
        raise ReviewQueueError(f"invalid status {status!r}; expected one of: {allowed}")


def _task_triage(task: ReviewTaskRow) -> dict[str, object]:
    """Read persisted triage, with a safe policy fallback for older databases."""

    triage = task.payload.get("triage")
    if isinstance(triage, dict):
        return triage
    if task.task_type == "duplicate_candidate":
        return _DUPLICATE_TRIAGE
    return _METADATA_TRIAGE["missing_source_url"]


def _require_reviewer_role(task: ReviewTaskRow, reviewer_role: str) -> None:
    required_role = _task_triage(task)["required_reviewer_role"]
    if reviewer_role != required_role:
        raise ReviewQueueError(
            f"task {task.id} requires reviewer role {required_role}"
        )


def _update_knowledge_review_status(
    session: Session, task: ReviewTaskRow, decision: str
) -> None:
    """Reflect a terminal review decision on its originating knowledge unit."""

    if task.task_type != "knowledge_medical_review" or decision == "deferred":
        return
    unit_id = task.payload.get("unit_id")
    if not isinstance(unit_id, str):
        raise ReviewQueueError(f"knowledge task {task.id} has no unit_id")
    unit = session.get(KnowledgeUnitRow, unit_id)
    if unit is None:
        raise ReviewQueueError(f"knowledge unit not found: {unit_id}")
    unit.medical_review_status = decision


def _resolved_reviewer_role(task: ReviewTaskRow, reviewer_role: str | None) -> str:
    """Use task policy for backwards-compatible Python callers without a role."""

    if reviewer_role is None:
        return str(_task_triage(task)["required_reviewer_role"])
    reviewer_role = _require_nonblank(reviewer_role, "reviewer_role")
    return reviewer_role


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
