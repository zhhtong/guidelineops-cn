import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from guidelineops.cli import app
from guidelineops.database import (
    KnowledgeRetractionRow,
    KnowledgeUnitRow,
    KnowledgeVersionRow,
    ReviewTaskRow,
    create_engine,
    freeze_knowledge_unit,
    init_database,
    knowledge_unit_from_row,
    retract_knowledge_unit,
    submit_knowledge_unit,
    upsert_knowledge_unit,
)
from guidelineops.knowledge import KnowledgeReviewStatus, KnowledgeUnit
from guidelineops.review_queue import (
    claim_task,
    decide_task,
    sync_knowledge_review_tasks,
)


def _unit() -> KnowledgeUnit:
    return KnowledgeUnit(
        unit_id="ku-1",
        source_record_id="pubmed:1",
        domain="western_medicine",
        statement="Use a documented source statement.",
        source_locator={"section": "Recommendations"},
        version="2024-1",
    )


def test_knowledge_unit_round_trip_is_idempotent(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'knowledge.db'}")
    init_database(engine)

    with Session(engine) as session:
        row = upsert_knowledge_unit(session, _unit())
        updated = _unit().model_copy(update={"statement": "Updated statement."})
        row = upsert_knowledge_unit(session, updated)
        session.commit()

        assert session.scalar(select(func.count()).select_from(KnowledgeUnitRow)) == 1
        restored = knowledge_unit_from_row(row)

    assert restored.statement == "Updated statement."
    assert restored.source_locator.section == "Recommendations"


def test_knowledge_import_and_list_cli(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "knowledge.db"
    source = tmp_path / "knowledge.json"
    source.write_text(json.dumps([_unit().model_dump(mode="json")]), encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    runner = CliRunner()

    imported = runner.invoke(app, ["knowledge-import", str(source)])
    listed = runner.invoke(app, ["knowledge-list"])

    assert imported.exit_code == 0, imported.output
    assert "Imported knowledge units: 1" in imported.output
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output.splitlines()[0])["unit_id"] == "ku-1"


def test_knowledge_submit_cli_marks_unit_pending(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "knowledge.db"
    source = tmp_path / "knowledge.json"
    source.write_text(json.dumps([_unit().model_dump(mode="json")]), encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    runner = CliRunner()

    runner.invoke(app, ["knowledge-import", str(source)])
    submitted = runner.invoke(app, ["knowledge-submit", "ku-1"])

    assert submitted.exit_code == 0, submitted.output
    assert json.loads(submitted.output)["medical_review_status"] == "pending"


def test_submitted_knowledge_unit_flows_through_medical_review_task(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'knowledge-review.db'}")
    init_database(engine)

    with Session(engine) as session:
        row = upsert_knowledge_unit(
            session,
            _unit().model_copy(
                update={"medical_review_status": KnowledgeReviewStatus.pending}
            ),
        )
        session.commit()
        result = sync_knowledge_review_tasks(session)
        session.commit()

        assert result.created == 1
        task = session.scalar(
            select(KnowledgeUnitRow).where(KnowledgeUnitRow.unit_id == row.unit_id)
        )
        assert task is not None

        review_task = session.scalar(select(ReviewTaskRow))
        claim_task(
            session,
            review_task.id,
            reviewer="Dr Chen",
            reviewer_role="medical_reviewer",
        )
        decide_task(
            session,
            review_task.id,
            reviewer="Dr Chen",
            reviewer_role="medical_reviewer",
            decision="approved",
        )
        final_task = session.scalar(
            select(ReviewTaskRow).where(
                ReviewTaskRow.task_type == "knowledge_final_review"
            )
        )
        assert final_task is not None
        claim_task(
            session,
            final_task.id,
            reviewer="Dr Wang",
            reviewer_role="medical_lead",
        )
        decide_task(
            session,
            final_task.id,
            reviewer="Dr Wang",
            reviewer_role="medical_lead",
            decision="approved",
        )
        session.commit()
        session.refresh(task)

        assert task.medical_review_status == "approved"

        submit_knowledge_unit(session, "ku-1")
        reopened = sync_knowledge_review_tasks(session)
        session.commit()
        reopened_task = session.scalar(
            select(ReviewTaskRow).where(
                ReviewTaskRow.task_type == "knowledge_medical_review"
            )
        )

        assert reopened.created == 0
        assert reopened_task is not None
        assert reopened_task.status == "open"


def test_knowledge_approval_requires_independent_final_medical_review(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'two-reviewers.db'}")
    init_database(engine)

    with Session(engine) as session:
        upsert_knowledge_unit(
            session,
            _unit().model_copy(
                update={"medical_review_status": KnowledgeReviewStatus.pending}
            ),
        )
        sync_knowledge_review_tasks(session)
        primary_task = session.scalar(
            select(ReviewTaskRow).where(
                ReviewTaskRow.task_type == "knowledge_medical_review"
            )
        )
        assert primary_task is not None

        claim_task(
            session,
            primary_task.id,
            reviewer="Dr Chen",
            reviewer_role="medical_reviewer",
        )
        decide_task(
            session,
            primary_task.id,
            reviewer="Dr Chen",
            reviewer_role="medical_reviewer",
            decision="approved",
        )

        unit_after_primary = session.get(KnowledgeUnitRow, "ku-1")
        final_task = session.scalar(
            select(ReviewTaskRow).where(
                ReviewTaskRow.task_type == "knowledge_final_review"
            )
        )
        assert unit_after_primary is not None
        assert unit_after_primary.medical_review_status == "pending"
        assert final_task is not None
        assert final_task.payload["triage"]["required_reviewer_role"] == "medical_lead"

        with pytest.raises(ValueError, match="independent reviewer"):
            claim_task(
                session,
                final_task.id,
                reviewer="Dr Chen",
                reviewer_role="medical_lead",
            )

        claim_task(
            session,
            final_task.id,
            reviewer="Dr Wang",
            reviewer_role="medical_lead",
        )
        decide_task(
            session,
            final_task.id,
            reviewer="Dr Wang",
            reviewer_role="medical_lead",
            decision="approved",
        )
        session.commit()
        session.refresh(unit_after_primary)

        assert unit_after_primary.medical_review_status == "approved"


def test_final_knowledge_disagreement_opens_escalation_without_approving(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'knowledge-disagreement.db'}")
    init_database(engine)

    with Session(engine) as session:
        upsert_knowledge_unit(
            session,
            _unit().model_copy(
                update={"medical_review_status": KnowledgeReviewStatus.pending}
            ),
        )
        sync_knowledge_review_tasks(session)
        primary = session.scalar(
            select(ReviewTaskRow).where(
                ReviewTaskRow.task_type == "knowledge_medical_review"
            )
        )
        assert primary is not None
        claim_task(
            session,
            primary.id,
            reviewer="Dr Chen",
            reviewer_role="medical_reviewer",
        )
        decide_task(
            session,
            primary.id,
            reviewer="Dr Chen",
            reviewer_role="medical_reviewer",
            decision="approved",
        )
        final = session.scalar(
            select(ReviewTaskRow).where(
                ReviewTaskRow.task_type == "knowledge_final_review"
            )
        )
        assert final is not None
        claim_task(session, final.id, reviewer="Dr Wang", reviewer_role="medical_lead")
        decide_task(
            session,
            final.id,
            reviewer="Dr Wang",
            reviewer_role="medical_lead",
            decision="rejected",
            reason="Evidence interpretation differs",
        )
        unit = session.get(KnowledgeUnitRow, "ku-1")
        escalation = session.scalar(
            select(ReviewTaskRow).where(
                ReviewTaskRow.task_type == "knowledge_escalation"
            )
        )

        assert unit is not None
        assert escalation is not None
        assert unit.medical_review_status == "pending"
        assert escalation.status == "open"
        assert escalation.payload["reason"] == "Evidence interpretation differs"
        claim_task(
            session,
            escalation.id,
            reviewer="Dr Chair",
            reviewer_role="medical_chair",
        )
        decide_task(
            session,
            escalation.id,
            reviewer="Dr Chair",
            reviewer_role="medical_chair",
            decision="approved",
            reason="Chair adjudication accepted the source interpretation",
        )
        assert unit.medical_review_status == "approved"


def test_retraction_records_reason_and_finds_dependent_knowledge(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'retraction.db'}")
    init_database(engine)

    with Session(engine) as session:
        upsert_knowledge_unit(session, _unit())
        dependent = KnowledgeUnit(
            unit_id="ku-dependent",
            source_record_id="cnki:1",
            domain="traditional_chinese_medicine",
            statement="痰热壅肺证相关知识。",
            source_locator={"section": "证治"},
            version="2024-1",
            tcm_pattern="痰热壅肺证",
            mapping_type="conditional",
            mapped_unit_ids=["ku-1"],
        )
        upsert_knowledge_unit(session, dependent)
        impact = retract_knowledge_unit(
            session,
            "ku-1",
            reason="Source guideline was withdrawn",
            actor="medical-lead-1",
        )
        impact_ids = [item.unit_id for item in impact]
        session.commit()

        root = session.get(KnowledgeUnitRow, "ku-1")
        retraction = session.scalar(select(KnowledgeRetractionRow))
        assert retraction is not None
        retraction.reason = "tampered"
        with pytest.raises(ValueError, match="immutable"):
            session.commit()
        session.rollback()
        session.refresh(root)
        session.refresh(retraction)
        root_status = root.medical_review_status
        retraction_reason = retraction.reason
        retraction_actor = retraction.actor

    assert root_status == "retracted"
    assert retraction_reason == "Source guideline was withdrawn"
    assert retraction_actor == "medical-lead-1"
    assert impact_ids == ["ku-dependent"]


def test_knowledge_retract_and_impact_cli(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "knowledge.db"
    source = tmp_path / "knowledge.json"
    source.write_text(json.dumps([_unit().model_dump(mode="json")]), encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    runner = CliRunner()
    runner.invoke(app, ["knowledge-import", str(source)])

    retracted = runner.invoke(
        app,
        [
            "knowledge-retract",
            "ku-1",
            "--reviewer",
            "Dr Wang",
            "--role",
            "medical_lead",
            "--reason",
            "Source withdrawn",
        ],
    )
    impacted = runner.invoke(app, ["knowledge-impact", "ku-1"])

    assert retracted.exit_code == 0, retracted.output
    assert json.loads(retracted.output)["medical_review_status"] == "retracted"
    assert impacted.exit_code == 0, impacted.output
    assert json.loads(impacted.output) == []


def test_approved_knowledge_unit_can_be_frozen_as_immutable_version(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'freeze.db'}")
    init_database(engine)

    with Session(engine) as session:
        upsert_knowledge_unit(
            session,
            _unit().model_copy(
                update={"medical_review_status": KnowledgeReviewStatus.approved}
            ),
        )
        frozen = freeze_knowledge_unit(session, "ku-1", actor="Dr Wang")
        session.commit()

        version_row = session.scalar(select(KnowledgeVersionRow))
        assert version_row is not None
        version_row.snapshot = {**version_row.snapshot, "statement": "tampered"}
        with pytest.raises(ValueError, match="immutable"):
            session.commit()
        session.rollback()
        snapshot = frozen.snapshot

    assert snapshot["unit_id"] == "ku-1"
    assert snapshot["medical_review_status"] == "approved"


def test_knowledge_freeze_cli_requires_medical_lead(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "knowledge.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    engine = create_engine(f"sqlite:///{database_path}")
    init_database(engine)
    with Session(engine) as session:
        upsert_knowledge_unit(
            session,
            _unit().model_copy(
                update={"medical_review_status": KnowledgeReviewStatus.approved}
            ),
        )
        session.commit()

    denied = CliRunner().invoke(
        app,
        [
            "knowledge-freeze",
            "ku-1",
            "--reviewer",
            "Alice",
            "--role",
            "medical_reviewer",
        ],
    )
    frozen = CliRunner().invoke(
        app,
        ["knowledge-freeze", "ku-1", "--reviewer", "Dr Wang", "--role", "medical_lead"],
    )

    assert denied.exit_code == 2
    assert "medical_lead" in denied.output
    assert frozen.exit_code == 0, frozen.output
    assert json.loads(frozen.output)["snapshot_sha256"]
