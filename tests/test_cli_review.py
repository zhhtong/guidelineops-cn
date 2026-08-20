import json
from pathlib import Path

from sqlalchemy.orm import Session
from typer.testing import CliRunner

from guidelineops.cli import app
from guidelineops.database import create_engine, init_database, upsert_source_record
from guidelineops.models import SourceRecord


def _seed_source_record(database_path: Path) -> None:
    engine = create_engine(f"sqlite:///{database_path}")
    init_database(engine)
    with Session(engine) as session:
        upsert_source_record(
            session,
            SourceRecord(
                source="pubmed",
                source_record_id="1",
                title="COPD guideline",
            ),
        )
        session.commit()


def test_review_cli_sync_claim_and_reject(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "review.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    _seed_source_record(database_path)
    runner = CliRunner()

    synced = runner.invoke(app, ["review-sync"])
    listed = runner.invoke(app, ["review-list", "--status", "open"])
    task_id = json.loads(listed.output.splitlines()[0])["id"]
    claimed = runner.invoke(
        app,
        [
            "review-claim",
            str(task_id),
            "--reviewer",
            "Alice",
            "--role",
            "data_curator",
        ],
    )
    rejected = runner.invoke(
        app,
        [
            "review-reject",
            str(task_id),
            "--reviewer",
            "Alice",
            "--role",
            "data_curator",
            "--reason",
            "Out of scope",
        ],
    )

    assert synced.exit_code == 0, synced.output
    assert "Created: 3" in synced.output
    assert listed.exit_code == 0, listed.output
    assert claimed.exit_code == 0, claimed.output
    assert rejected.exit_code == 0, rejected.output
    assert json.loads(rejected.output)["status"] == "rejected"
    events = runner.invoke(app, ["review-events", str(task_id)])
    assert events.exit_code == 0, events.output
    assert [json.loads(line)["event_type"] for line in events.output.splitlines()] == [
        "synced",
        "claimed",
        "rejected",
    ]
    assert json.loads(events.output.splitlines()[-1])["payload"] == {
        "reviewer_role": "data_curator"
    }


def test_review_cli_requires_declared_reviewer_role(
    monkeypatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "review.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    _seed_source_record(database_path)
    runner = CliRunner()
    runner.invoke(app, ["review-sync"])
    listed = runner.invoke(app, ["review-list"])
    task_id = json.loads(listed.output.splitlines()[0])["id"]

    result = runner.invoke(
        app, ["review-claim", str(task_id), "--reviewer", "Alice"]
    )

    assert result.exit_code == 2
    assert "--role" in result.output


def test_review_cli_enforces_configured_reviewer_registry(
    monkeypatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "review.db"
    registry_path = tmp_path / "reviewers.json"
    registry_path.write_text(
        '{"reviewers": [{"id": "alice", "roles": ["data_curator"]}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("REVIEWER_REGISTRY_PATH", str(registry_path))
    _seed_source_record(database_path)
    runner = CliRunner()
    runner.invoke(app, ["review-sync"])
    listed = runner.invoke(app, ["review-list"])
    task_id = json.loads(listed.output.splitlines()[0])["id"]

    denied = runner.invoke(
        app,
        [
            "review-claim",
            str(task_id),
            "--reviewer",
            "mallory",
            "--role",
            "data_curator",
        ],
    )
    allowed = runner.invoke(
        app,
        [
            "review-claim",
            str(task_id),
            "--reviewer",
            "alice",
            "--role",
            "data_curator",
        ],
    )

    assert denied.exit_code == 2
    assert "not authorized" in denied.output
    assert allowed.exit_code == 0, allowed.output


def test_review_cli_reject_requires_reason(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "review.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    _seed_source_record(database_path)
    runner = CliRunner()
    runner.invoke(app, ["review-sync"])
    listed = runner.invoke(app, ["review-list"])
    task_id = json.loads(listed.output.splitlines()[0])["id"]
    runner.invoke(
        app,
        [
            "review-claim",
            str(task_id),
            "--reviewer",
            "Alice",
            "--role",
            "data_curator",
        ],
    )

    result = runner.invoke(
        app,
        [
            "review-reject",
            str(task_id),
            "--reviewer",
            "Alice",
            "--role",
            "data_curator",
            "--reason",
            " ",
        ],
    )

    assert result.exit_code == 2
    assert "reason is required" in result.output
