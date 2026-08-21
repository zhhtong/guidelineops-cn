# Database Resilience Design

## Goal

Give GuidelineOps-CN a small, testable database-evolution and backup/recovery
layer suitable for its SQLite-based research workflow. This is an operational
control, not a clinical validation feature.

## Scope

The feature adds a version ledger for schema migrations, a command to inspect
database schema state, a verified SQLite backup command, and a guarded restore
command. It deliberately does not add multi-user database support, cloud
storage, automatic scheduling, encryption key management, or patient data.

## Architecture

`guidelineops/migrations.py` will own a numbered migration registry. Version 1
records the current SQLAlchemy model set as the initial managed schema. On a
new database, it creates all current tables and records the migration. On a
database created by a prior release without the ledger, it records an explicit
baseline only after all expected current tables exist. This preserves existing
research databases while making future schema changes explicit.

`guidelineops/backups.py` will own SQLite-specific backups and restores. Backup
uses SQLite's online backup API and writes a JSON manifest containing the
artifact name, UTC timestamp, byte count, SHA-256 and schema version. Restore
checks the manifest hash and SQLite integrity, then refuses to replace a target
database unless the caller explicitly supplies `--force`.

The CLI will expose `database-status`, `database-backup` and
`database-restore`. Database URLs remain configured through `DATABASE_URL`; a
backup directory defaults to a caller-provided argument rather than silently
choosing a location. All commands reject non-file SQLite URLs and non-SQLite
engines with clear errors.

## Data Flow

```text
DATABASE_URL -> migrate_database -> schema_migrations ledger
DATABASE_URL -> SQLite backup API -> .db artifact -> SHA-256 manifest
manifest + artifact -> integrity/hash verification -> guarded atomic restore
```

## Error Handling

- A database whose migration ledger is ahead of the application's latest
  version fails fast rather than being opened or restored as if compatible.
- A legacy database lacking the ledger is only baselined when all expected
  tables are present; partial or unrelated databases fail with guidance.
- Backup verifies that the source is a persistent SQLite file and that the
  resulting artifact passes `PRAGMA integrity_check`.
- Restore rejects missing files, invalid JSON, hash mismatch, failed integrity
  checks and existing targets without `--force`. It writes a temporary target
  in the target directory before replacing the target.

## Test Strategy

Use temporary SQLite files, not mocks. Tests cover initial migration,
legacy-baseline migration, status reporting, manifest hash generation, backup
round-trip restoration, corrupt artifact rejection and overwrite protection.
CLI tests verify the commands use settings, print usable paths and require
`--force` for replacement.

## Acceptance Criteria

1. Every project database initialized by the application has a versioned
   migration ledger.
2. A user can create a manifest-verified backup and restore it into a new file.
3. A corrupt or modified backup cannot be restored.
4. A restore cannot overwrite an existing database without an explicit flag.
5. Existing database, CLI and full test behavior remains green.
