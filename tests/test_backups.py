import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from guidelineops.backups import (
    BackupError,
    backup_sqlite_database,
    restore_sqlite_backup,
)
from guidelineops.database import (
    SourceRecordRow,
    create_engine,
    init_database,
    upsert_source_record,
)
from guidelineops.models import SourceRecord


def _seed_database(path: Path) -> str:
    database_url = f"sqlite:///{path}"
    engine = create_engine(database_url)
    init_database(engine)
    with Session(engine) as session:
        upsert_source_record(
            session,
            SourceRecord(
                source="demo",
                source_record_id="source-1",
                title="Backup demonstration record",
            ),
        )
        session.commit()
    return database_url


def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    source_url = _seed_database(tmp_path / "source.db")
    backup = backup_sqlite_database(source_url, tmp_path / "backups")
    target_url = f"sqlite:///{tmp_path / 'restored.db'}"

    restored = restore_sqlite_backup(backup.path, target_url)

    assert restored.sha256 == backup.sha256
    assert json.loads(backup.manifest_path.read_text(encoding="utf-8"))["sha256"] == (
        backup.sha256
    )
    with Session(create_engine(target_url)) as session:
        assert (
            session.scalar(select(SourceRecordRow.title))
            == "Backup demonstration record"
        )


def test_restore_rejects_modified_backup(tmp_path: Path) -> None:
    source_url = _seed_database(tmp_path / "source.db")
    backup = backup_sqlite_database(source_url, tmp_path / "backups")
    backup.path.write_bytes(backup.path.read_bytes() + b"tampered")

    with pytest.raises(BackupError, match="SHA-256"):
        restore_sqlite_backup(backup.path, f"sqlite:///{tmp_path / 'restored.db'}")


def test_restore_requires_force_to_replace_existing_database(tmp_path: Path) -> None:
    source_url = _seed_database(tmp_path / "source.db")
    backup = backup_sqlite_database(source_url, tmp_path / "backups")
    target_url = _seed_database(tmp_path / "target.db")

    with pytest.raises(BackupError, match="--force"):
        restore_sqlite_backup(backup.path, target_url)
