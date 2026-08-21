import json

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from guidelineops.cli import app
from guidelineops.database import (
    MedicationSafetyRuleRow,
    ReviewTaskRow,
    create_engine,
    init_database,
    upsert_knowledge_unit,
    upsert_medication_safety_rule,
)
from guidelineops.knowledge import KnowledgeUnit
from guidelineops.medication_safety import (
    MedicationSafetyRule,
    SafetyCategory,
    SafetyRiskLevel,
)
from guidelineops.review_queue import (
    claim_task,
    decide_task,
    sync_medication_safety_review_tasks,
)


def test_medication_safety_rule_requires_traceable_non_prescriptive_content() -> None:
    rule = MedicationSafetyRule(
        rule_id="med-safety-001",
        source_unit_id="ku-1",
        medication_name="Example medicine",
        category=SafetyCategory.contraindication,
        risk_level=SafetyRiskLevel.high,
        statement=(
            "Avoid use when the cited source lists the documented contraindication."
        ),
        source_locator="Table 4",
        version="2024-1",
    )

    assert rule.medication_name == "Example medicine"
    assert rule.safety_review_status == "draft"


@pytest.mark.parametrize(
    "payload",
    [
        {"source_locator": ""},
        {"statement": "Take 20 mg daily."},
        {"statement": "Start this medicine for all patients."},
    ],
)
def test_medication_safety_rule_rejects_untraceable_or_prescriptive_content(
    payload: dict[str, str],
) -> None:
    values: dict[str, str] = {
        "rule_id": "med-safety-001",
        "source_unit_id": "ku-1",
        "medication_name": "Example medicine",
        "category": "contraindication",
        "risk_level": "high",
        "statement": "Avoid use when the cited source lists the contraindication.",
        "source_locator": "Table 4",
        "version": "2024-1",
    }
    values.update(payload)

    with pytest.raises(ValidationError):
        MedicationSafetyRule(**values)


def test_medication_safety_rule_is_persisted_idempotently(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'medication.db'}")
    init_database(engine)
    rule = MedicationSafetyRule(
        rule_id="med-safety-001",
        source_unit_id="ku-1",
        medication_name="Example medicine",
        category="contraindication",
        risk_level="high",
        statement=(
            "Avoid use when the cited source lists the documented contraindication."
        ),
        source_locator="Table 4",
        version="2024-1",
    )

    with Session(engine) as session:
        upsert_knowledge_unit(
            session,
            KnowledgeUnit(
                unit_id="ku-1",
                source_record_id="pubmed:1",
                domain="western_medicine",
                statement="Evidence source statement.",
                source_locator={"section": "Safety"},
                version="2024-1",
            ),
        )
        upsert_medication_safety_rule(session, rule)
        upsert_medication_safety_rule(
            session, rule.model_copy(update={"statement": "Updated source statement."})
        )
        session.commit()

        count = session.scalar(
            select(func.count()).select_from(MedicationSafetyRuleRow)
        )
        row = session.get(MedicationSafetyRuleRow, "med-safety-001")

    assert count == 1
    assert row is not None
    assert row.statement == "Updated source statement."


def test_medication_safety_rule_requires_existing_source_knowledge(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'medication.db'}")
    init_database(engine)
    rule = MedicationSafetyRule(
        rule_id="med-safety-001",
        source_unit_id="missing-unit",
        medication_name="Example medicine",
        category="contraindication",
        risk_level="high",
        statement=(
            "Avoid use when the cited source lists the documented contraindication."
        ),
        source_locator="Table 4",
        version="2024-1",
    )

    with Session(engine) as session:
        with pytest.raises(ValueError, match="source knowledge unit"):
            upsert_medication_safety_rule(session, rule)


def test_medication_safety_import_and_list_cli(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "medication.db"
    source = tmp_path / "medication.json"
    source.write_text(
        json.dumps(
            [
                {
                    "rule_id": "med-safety-001",
                    "source_unit_id": "ku-1",
                    "medication_name": "Example medicine",
                    "category": "contraindication",
                    "risk_level": "high",
                    "statement": (
                        "Avoid use when the cited source lists the contraindication."
                    ),
                    "source_locator": "Table 4",
                    "version": "2024-1",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    engine = create_engine(f"sqlite:///{database_path}")
    init_database(engine)
    with Session(engine) as session:
        upsert_knowledge_unit(
            session,
            KnowledgeUnit(
                unit_id="ku-1",
                source_record_id="pubmed:1",
                domain="western_medicine",
                statement="Evidence source statement.",
                source_locator={"section": "Safety"},
                version="2024-1",
            ),
        )
        session.commit()

    imported = CliRunner().invoke(app, ["medication-safety-import", str(source)])
    listed = CliRunner().invoke(app, ["medication-safety-list"])

    assert imported.exit_code == 0, imported.output
    assert "Imported medication safety rules: 1" in imported.output
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)["rule_id"] == "med-safety-001"


def test_medication_safety_rule_requires_two_medical_reviews(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'medication-review.db'}")
    init_database(engine)
    rule = MedicationSafetyRule(
        rule_id="med-safety-001",
        source_unit_id="ku-1",
        medication_name="Example medicine",
        category="contraindication",
        risk_level="high",
        statement=(
            "Avoid use when the cited source lists the documented contraindication."
        ),
        source_locator="Table 4",
        version="2024-1",
        safety_review_status="pending",
    )

    with Session(engine) as session:
        upsert_knowledge_unit(
            session,
            KnowledgeUnit(
                unit_id="ku-1",
                source_record_id="pubmed:1",
                domain="western_medicine",
                statement="Evidence source statement.",
                source_locator={"section": "Safety"},
                version="2024-1",
            ),
        )
        upsert_medication_safety_rule(session, rule)
        sync_medication_safety_review_tasks(session)
        primary = session.scalar(
            select(ReviewTaskRow).where(
                ReviewTaskRow.task_type == "medication_safety_review"
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
                ReviewTaskRow.task_type == "medication_safety_final_review"
            )
        )
        safety_row = session.get(MedicationSafetyRuleRow, "med-safety-001")
        assert final is not None
        assert safety_row is not None
        assert safety_row.safety_review_status == "pending"

        claim_task(
            session,
            final.id,
            reviewer="Dr Wang",
            reviewer_role="medical_lead",
        )
        decide_task(
            session,
            final.id,
            reviewer="Dr Wang",
            reviewer_role="medical_lead",
            decision="approved",
        )
        assert safety_row.safety_review_status == "approved"


def test_medication_safety_submit_cli_marks_rule_pending(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "medication.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    engine = create_engine(f"sqlite:///{database_path}")
    init_database(engine)
    with Session(engine) as session:
        upsert_knowledge_unit(
            session,
            KnowledgeUnit(
                unit_id="ku-1",
                source_record_id="pubmed:1",
                domain="western_medicine",
                statement="Evidence source statement.",
                source_locator={"section": "Safety"},
                version="2024-1",
            ),
        )
        upsert_medication_safety_rule(
            session,
            MedicationSafetyRule(
                rule_id="med-safety-001",
                source_unit_id="ku-1",
                medication_name="Example medicine",
                category="contraindication",
                risk_level="high",
                statement="Avoid use when the cited source lists the contraindication.",
                source_locator="Table 4",
                version="2024-1",
            ),
        )
        session.commit()

    submitted = CliRunner().invoke(app, ["medication-safety-submit", "med-safety-001"])

    assert submitted.exit_code == 0, submitted.output
    assert json.loads(submitted.output)["safety_review_status"] == "pending"
