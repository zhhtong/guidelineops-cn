import json
from pathlib import Path

from sqlalchemy.orm import Session
from typer.testing import CliRunner

from guidelineops.cli import app
from guidelineops.database import create_engine, init_database, upsert_source_record
from guidelineops.models import SourceRecord


def test_quality_report_writes_json_and_markdown_for_source_records(
    monkeypatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    database_path = tmp_path / "guidelineops.db"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")

    engine = create_engine(f"sqlite:///{database_path}")
    init_database(engine)
    with Session(engine) as session:
        upsert_source_record(
            session,
            SourceRecord(
                source="pubmed",
                source_record_id="1",
                title="COPD guideline",
                doi="10.1000/example",
                publication_year=2024,
                source_url="https://pubmed.ncbi.nlm.nih.gov/1/",
            ),
        )
        session.commit()

    result = CliRunner().invoke(app, ["quality-report"])

    assert result.exit_code == 0, result.output
    assert "Records: 1" in result.output
    assert f"JSON: {data_dir / 'quality_report.json'}" in result.output
    assert f"Markdown: {data_dir / 'quality_report.md'}" in result.output

    json_path = data_dir / "quality_report.json"
    markdown_path = data_dir / "quality_report.md"
    assert json_path.exists()
    assert markdown_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total_records"] == 1
    assert payload["canonical_records"] == 1
    assert "## Headline counts" in markdown_path.read_text(encoding="utf-8")


def test_quality_report_succeeds_for_empty_database(
    monkeypatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    database_path = tmp_path / "empty.db"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")

    result = CliRunner().invoke(app, ["quality-report"])

    assert result.exit_code == 0, result.output
    assert "Records: 0" in result.output
    assert (data_dir / "quality_report.json").exists()
    assert (data_dir / "quality_report.md").exists()
