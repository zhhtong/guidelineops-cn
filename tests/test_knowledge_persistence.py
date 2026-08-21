import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from guidelineops.cli import app
from guidelineops.database import (
    KnowledgeUnitRow,
    create_engine,
    init_database,
    knowledge_unit_from_row,
    upsert_knowledge_unit,
)
from guidelineops.knowledge import KnowledgeUnit


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
