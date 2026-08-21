"""Verified backup and guarded restore operations for file-backed SQLite data."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from .database import create_engine
from .migrations import LATEST_SCHEMA_VERSION, migrate_database, schema_status


class BackupError(ValueError):
    """Raised when a backup artifact cannot be safely created or restored."""


@dataclass(frozen=True)
class BackupResult:
    """Verified SQLite backup artifact and its metadata manifest."""

    path: Path
    manifest_path: Path
    sha256: str
    byte_count: int
    schema_version: int
    created_at: str

    def mapping(self) -> dict[str, object]:
        """Return JSON-safe backup metadata with portable string paths."""

        payload = asdict(self)
        payload["path"] = str(self.path)
        payload["manifest_path"] = str(self.manifest_path)
        return payload


@dataclass(frozen=True)
class RestoreResult:
    """Verified restore result for one SQLite target database."""

    path: Path
    sha256: str
    schema_version: int
    restored_at: str

    def mapping(self) -> dict[str, object]:
        """Return JSON-safe restore metadata with a portable string path."""

        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


def backup_sqlite_database(database_url: str, destination_dir: Path) -> BackupResult:
    """Create a SHA-256 verified online backup of one managed SQLite database."""

    source_path = _sqlite_file_path(database_url)
    if not source_path.exists():
        raise BackupError(f"database file does not exist: {source_path}")
    engine = create_engine(database_url)
    status = migrate_database(engine)
    destination_dir = destination_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc)
    artifact_path = _artifact_path(destination_dir, created_at)
    temporary_path = artifact_path.with_suffix(".partial")
    try:
        _sqlite_backup(source_path, temporary_path)
        _verify_sqlite_integrity(temporary_path)
        os.replace(temporary_path, artifact_path)
        digest = _sha256(artifact_path)
        result = BackupResult(
            path=artifact_path,
            manifest_path=artifact_path.with_suffix(".json"),
            sha256=digest,
            byte_count=artifact_path.stat().st_size,
            schema_version=status.current_version,
            created_at=created_at.isoformat(),
        )
        _write_manifest(result)
        return result
    finally:
        temporary_path.unlink(missing_ok=True)


def restore_sqlite_backup(
    backup_path: Path, database_url: str, *, force: bool = False
) -> RestoreResult:
    """Restore a verified artifact, refusing target replacement unless forced."""

    backup_path = backup_path.resolve()
    manifest = _load_and_verify_manifest(backup_path)
    target_path = _sqlite_file_path(database_url)
    if target_path.exists() and not force:
        raise BackupError(
            f"restore target already exists: {target_path}; pass --force to replace it"
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_restore_path(target_path)
    try:
        shutil.copyfile(backup_path, temporary_path)
        _verify_sqlite_integrity(temporary_path)
        _verify_schema_version(temporary_path, manifest["schema_version"])
        os.replace(temporary_path, target_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return RestoreResult(
        path=target_path,
        sha256=str(manifest["sha256"]),
        schema_version=int(manifest["schema_version"]),
        restored_at=datetime.now(timezone.utc).isoformat(),
    )


def _sqlite_file_path(database_url: str) -> Path:
    """Resolve a persistent SQLite URL to a local database path."""

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise BackupError("backup and restore currently support SQLite only")
    if not url.database or url.database == ":memory:":
        raise BackupError("backup and restore require a file-backed SQLite database")
    return Path(url.database).resolve()


def _artifact_path(destination_dir: Path, created_at: datetime) -> Path:
    """Choose a unique, timestamped backup path without replacing an artifact."""

    stem = f"guidelineops-backup-{created_at.strftime('%Y%m%dT%H%M%SZ')}"
    candidate = destination_dir / f"{stem}.db"
    suffix = 1
    while candidate.exists() or candidate.with_suffix(".json").exists():
        candidate = destination_dir / f"{stem}-{suffix}.db"
        suffix += 1
    return candidate


def _sqlite_backup(source_path: Path, target_path: Path) -> None:
    """Use SQLite's backup API so the artifact is a consistent database copy."""

    source = sqlite3.connect(source_path)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _verify_sqlite_integrity(path: Path) -> None:
    """Reject a database artifact that SQLite cannot validate as internally sound."""

    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        raise BackupError(f"SQLite integrity check failed: {error}") from error
    result = row[0] if row is not None else None
    if result != "ok":
        raise BackupError(f"SQLite integrity check failed: {result}")


def _sha256(path: Path) -> str:
    """Compute the SHA-256 of raw backup bytes without loading the whole file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(result: BackupResult) -> None:
    """Atomically write artifact metadata after the artifact has been verified."""

    payload = json.dumps(result.mapping(), ensure_ascii=False, indent=2, sort_keys=True)
    payload += "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=result.manifest_path.parent,
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary_path = Path(handle.name)
    try:
        os.replace(temporary_path, result.manifest_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _load_and_verify_manifest(backup_path: Path) -> dict[str, object]:
    """Read a matching manifest and verify the artifact hash before restoration."""

    if not backup_path.is_file():
        raise BackupError(f"backup artifact does not exist: {backup_path}")
    manifest_path = backup_path.with_suffix(".json")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BackupError(f"backup manifest does not exist: {manifest_path}") from error
    except json.JSONDecodeError as error:
        raise BackupError(
            f"backup manifest is invalid JSON: {manifest_path}"
        ) from error
    if not isinstance(payload, dict):
        raise BackupError("backup manifest must contain a JSON object")
    required = {"path", "sha256", "byte_count", "schema_version", "created_at"}
    if not required <= payload.keys():
        raise BackupError("backup manifest is missing required fields")
    if Path(str(payload["path"])).name != backup_path.name:
        raise BackupError("backup manifest does not match the selected artifact")
    if _sha256(backup_path) != payload["sha256"]:
        raise BackupError("backup SHA-256 does not match its manifest")
    if backup_path.stat().st_size != int(payload["byte_count"]):
        raise BackupError("backup byte count does not match its manifest")
    if int(payload["schema_version"]) > LATEST_SCHEMA_VERSION:
        raise BackupError(
            "backup schema version is newer than this GuidelineOps release"
        )
    return payload


def _temporary_restore_path(target_path: Path) -> Path:
    """Create a private temporary filename on the target filesystem."""

    with tempfile.NamedTemporaryFile(
        suffix=".restore", dir=target_path.parent, delete=False
    ) as handle:
        return Path(handle.name)


def _verify_schema_version(path: Path, expected_version: object) -> None:
    """Ensure a manifest's managed-schema version matches its SQLite artifact."""

    database_url = f"sqlite:///{path.as_posix()}"
    engine = create_engine(database_url)
    try:
        version = schema_status(engine).current_version
    finally:
        engine.dispose()
    if version != int(expected_version):
        raise BackupError("backup schema version does not match its manifest")
