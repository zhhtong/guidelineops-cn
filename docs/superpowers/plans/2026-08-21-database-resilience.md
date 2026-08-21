# Database Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add managed SQLite schema versions plus verified, guarded database backup and restore operations.

**Architecture:** A migration registry stores applied versions in a `schema_migrations` ledger and becomes the single implementation behind `init_database`. A backup module uses SQLite's backup API and a SHA-256 manifest; CLI commands call these small domain functions without duplicating file handling.

**Tech Stack:** Python 3.11+, SQLAlchemy 2, SQLite standard library, Typer, pytest.

---

### Task 1: Schema migration ledger

**Files:**
- Create: `guidelineops/migrations.py`
- Modify: `guidelineops/database.py:303-306`
- Test: `tests/test_migrations.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_migrate_database_records_initial_schema(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'managed.db'}")
    status = migrate_database(engine)
    assert status.current_version == 1
    assert status.pending_versions == ()


def test_migrate_database_baselines_legacy_current_schema(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    status = migrate_database(engine)
    assert status.current_version == 1
    assert status.baselined_legacy_database is True
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `uv run pytest -q tests/test_migrations.py`

Expected: FAIL because `guidelineops.migrations` does not exist.

- [ ] **Step 3: Implement the migration registry and wire initialization to it**

```python
LATEST_SCHEMA_VERSION = 1

def migrate_database(engine: Engine) -> SchemaStatus:
    # create/read schema_migrations; create current tables on an empty DB;
    # baseline only a complete legacy schema; record version 1 atomically
```

Change `init_database` to call `migrate_database(engine)`.

- [ ] **Step 4: Run focused migration tests**

Run: `uv run pytest -q tests/test_migrations.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add guidelineops/migrations.py guidelineops/database.py tests/test_migrations.py
git commit -m "feat: add managed schema migration ledger"
```

### Task 2: Verified backup and guarded restore

**Files:**
- Create: `guidelineops/backups.py`
- Test: `tests/test_backups.py`

- [ ] **Step 1: Write failing backup tests**

```python
def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    backup = backup_sqlite_database(source_url, tmp_path / "backups")
    restored = restore_sqlite_backup(backup.path, target_url)
    assert restored.sha256 == backup.sha256


def test_restore_rejects_modified_backup(tmp_path: Path) -> None:
    backup = backup_sqlite_database(source_url, tmp_path / "backups")
    backup.path.write_bytes(backup.path.read_bytes() + b"tampered")
    with pytest.raises(BackupError, match="SHA-256"):
        restore_sqlite_backup(backup.path, target_url)
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `uv run pytest -q tests/test_backups.py`

Expected: FAIL because `guidelineops.backups` does not exist.

- [ ] **Step 3: Implement SQLite artifact and manifest operations**

```python
def backup_sqlite_database(database_url: str, destination_dir: Path) -> BackupResult:
    # SQLite backup API, integrity check, SHA-256 manifest and atomic manifest write

def restore_sqlite_backup(backup_path: Path, database_url: str, *, force: bool = False) -> RestoreResult:
    # verify manifest hash and integrity; atomically copy only when target is absent or force is true
```

- [ ] **Step 4: Add overwrite and unsupported-URL cases, then run tests**

Run: `uv run pytest -q tests/test_backups.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add guidelineops/backups.py tests/test_backups.py
git commit -m "feat: add verified SQLite backup and restore"
```

### Task 3: CLI and operational documentation

**Files:**
- Modify: `guidelineops/cli.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/release-readiness.md`
- Test: `tests/test_cli_database.py`

- [ ] **Step 1: Write failing CLI tests**

```python
def test_database_backup_cli_writes_manifest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'source.db'}")
    result = CliRunner().invoke(app, ["database-backup", str(tmp_path / "backups")])
    assert result.exit_code == 0
    assert '"sha256"' in result.output
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `uv run pytest -q tests/test_cli_database.py`

Expected: FAIL because the command is not registered.

- [ ] **Step 3: Add status, backup and restore commands**

```python
@app.command("database-backup")
def database_backup(destination: Path) -> None:
    result = backup_sqlite_database(Settings().database_url, destination)
    typer.echo(json.dumps(result.mapping(), ensure_ascii=False))
```

Add `database-status` and `database-restore BACKUP --force`, returning JSON for automation.

- [ ] **Step 4: Document the recovery drill**

Document a safe backup, restore-to-new-file and integrity-check workflow. State that backups may contain operational data and must stay out of public repositories.

- [ ] **Step 5: Run full verification and commit**

Run: `uv run pytest -q && uv run ruff check . && uv lock --check && uv build && git diff --check`

Expected: all checks pass.

```bash
git add guidelineops/cli.py README.md README.zh-CN.md docs/release-readiness.md tests/test_cli_database.py
git commit -m "feat: expose database resilience commands"
```
