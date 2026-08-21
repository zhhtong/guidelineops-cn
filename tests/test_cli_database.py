import json
from pathlib import Path

from typer.testing import CliRunner

from guidelineops.backups import backup_sqlite_database
from guidelineops.cli import app
from guidelineops.database import create_engine, init_database


def test_database_backup_cli_writes_manifest(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "source.db"
    init_database(create_engine(f"sqlite:///{database_path}"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")

    result = CliRunner().invoke(app, ["database-backup", str(tmp_path / "backups")])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert Path(payload["path"]).is_file()
    assert Path(payload["manifest_path"]).is_file()


def test_database_restore_cli_requires_force_for_existing_target(
    tmp_path: Path, monkeypatch
) -> None:
    source_path = tmp_path / "source.db"
    source_url = f"sqlite:///{source_path}"
    init_database(create_engine(source_url))
    backup = backup_sqlite_database(source_url, tmp_path / "backups")
    target_path = tmp_path / "target.db"
    init_database(create_engine(f"sqlite:///{target_path}"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target_path}")
    runner = CliRunner()

    refused = runner.invoke(app, ["database-restore", str(backup.path)])
    restored = runner.invoke(app, ["database-restore", str(backup.path), "--force"])

    assert refused.exit_code == 2
    assert "--force" in refused.output
    assert restored.exit_code == 0, restored.output
    assert json.loads(restored.output)["schema_version"] == 1
