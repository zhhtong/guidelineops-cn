import json
import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import Session
from typer.testing import CliRunner

import guidelineops.cli as cli_module
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

    replace_calls: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def record_replace(source: str, destination: str) -> None:
        replace_calls.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", record_replace)
    result = CliRunner().invoke(app, ["quality-report"])

    assert result.exit_code == 0, result.output
    assert "Records: 1" in result.output
    assert f"JSON: {data_dir / 'quality_report.json'}" in result.output
    assert f"Markdown: {data_dir / 'quality_report.md'}" in result.output

    json_path = data_dir / "quality_report.json"
    markdown_path = data_dir / "quality_report.md"
    assert json_path.exists()
    assert markdown_path.exists()
    assert [destination for _, destination in replace_calls] == [
        json_path,
        markdown_path,
    ]
    assert all(
        source.parent == destination.parent and source != destination
        for source, destination in replace_calls
    )
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


def test_quality_report_orders_source_rows_by_primary_key(
    monkeypatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    database_path = tmp_path / "ordered.db"
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    engine = create_engine(f"sqlite:///{database_path}")

    @event.listens_for(engine, "connect")
    def reverse_unordered_selects(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA reverse_unordered_selects = ON")

    init_database(engine)
    with Session(engine) as session:
        for source_record_id in ("first", "second"):
            upsert_source_record(
                session,
                SourceRecord(
                    source="test",
                    source_record_id=source_record_id,
                    title=source_record_id,
                ),
            )
        session.commit()

    monkeypatch.setattr(cli_module, "_database_engine", lambda settings: engine)
    result = CliRunner().invoke(app, ["quality-report"])

    assert result.exit_code == 0, result.output
    payload = json.loads(
        (data_dir / "quality_report.json").read_text(encoding="utf-8")
    )
    assert [item["source_record_id"] for item in payload["risk_items"][::3]] == [
        "first",
        "second",
    ]


def test_quality_report_accepts_sqlite_pysqlite_url(
    monkeypatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    database_path = tmp_path / "driver.db"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")

    result = CliRunner().invoke(app, ["quality-report"])

    assert result.exit_code == 0, result.output
    assert "Records: 0" in result.output
    assert (data_dir / "quality_report.json").exists()
    assert (data_dir / "quality_report.md").exists()


def test_quality_report_does_not_leave_json_when_markdown_target_is_directory(
    monkeypatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    database_path = tmp_path / "directory-target.db"
    data_dir.mkdir()
    (data_dir / "quality_report.md").mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")

    result = CliRunner().invoke(app, ["quality-report"])

    assert result.exit_code != 0
    assert not (data_dir / "quality_report.json").exists()
    assert (data_dir / "quality_report.md").is_dir()
