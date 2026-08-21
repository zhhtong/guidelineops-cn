"""Small, explicit schema migration ledger for GuidelineOps SQLite databases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .database import Base

LATEST_SCHEMA_VERSION = 1
_LEDGER_TABLE = "schema_migrations"


class MigrationError(ValueError):
    """Raised when a database cannot safely be migrated by this release."""


@dataclass(frozen=True)
class SchemaStatus:
    """Read-only description of the application's schema migration state."""

    current_version: int
    latest_version: int
    pending_versions: tuple[int, ...]
    baselined_legacy_database: bool = False


def migrate_database(engine: Engine) -> SchemaStatus:
    """Apply known migrations or record a compatible pre-ledger database."""

    _require_sqlite(engine)
    existing_tables = set(inspect(engine).get_table_names())
    has_ledger = _LEDGER_TABLE in existing_tables
    baselined = False

    if not has_ledger and existing_tables:
        _baseline_legacy_database(engine, existing_tables)
        baselined = True
    elif not has_ledger:
        _create_ledger(engine)

    current_version = _current_version(engine)
    if current_version > LATEST_SCHEMA_VERSION:
        raise MigrationError(
            "database schema version is newer than this GuidelineOps release"
        )
    for version in range(current_version + 1, LATEST_SCHEMA_VERSION + 1):
        _apply_migration(engine, version)
    return schema_status(engine, baselined_legacy_database=baselined)


def schema_status(
    engine: Engine, *, baselined_legacy_database: bool = False
) -> SchemaStatus:
    """Return schema-ledger state without creating or changing database tables."""

    _require_sqlite(engine)
    if _LEDGER_TABLE not in inspect(engine).get_table_names():
        return SchemaStatus(
            current_version=0,
            latest_version=LATEST_SCHEMA_VERSION,
            pending_versions=tuple(range(1, LATEST_SCHEMA_VERSION + 1)),
            baselined_legacy_database=baselined_legacy_database,
        )
    current_version = _current_version(engine)
    if current_version > LATEST_SCHEMA_VERSION:
        raise MigrationError(
            "database schema version is newer than this GuidelineOps release"
        )
    return SchemaStatus(
        current_version=current_version,
        latest_version=LATEST_SCHEMA_VERSION,
        pending_versions=tuple(range(current_version + 1, LATEST_SCHEMA_VERSION + 1)),
        baselined_legacy_database=baselined_legacy_database,
    )


def _baseline_legacy_database(engine: Engine, existing_tables: set[str]) -> None:
    """Register a complete pre-ledger database as version 1 without altering it."""

    expected_tables = set(Base.metadata.tables)
    missing_tables = sorted(expected_tables - existing_tables)
    if missing_tables:
        rendered = ", ".join(missing_tables)
        raise MigrationError(
            "cannot baseline a partial or unrelated database; missing tables: "
            f"{rendered}"
        )
    _create_ledger(engine)
    _record_migration(engine, 1, "baseline_existing_schema")


def _apply_migration(engine: Engine, version: int) -> None:
    """Apply one numbered migration and atomically record it in the ledger."""

    if version != 1:
        raise MigrationError(
            f"migration implementation is missing for version {version}"
        )
    Base.metadata.create_all(engine)
    _record_migration(engine, version, "initial_managed_schema")


def _create_ledger(engine: Engine) -> None:
    """Create the migration ledger independently of SQLAlchemy model tables."""

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                "applied_at TEXT NOT NULL)"
            )
        )


def _record_migration(engine: Engine, version: int, name: str) -> None:
    """Append a migration record after its schema mutation has succeeded."""

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO schema_migrations (version, name, applied_at) "
                "VALUES (:version, :name, :applied_at)"
            ),
            {
                "version": version,
                "name": name,
                "applied_at": datetime.now(timezone.utc).isoformat(),
            },
        )


def _current_version(engine: Engine) -> int:
    """Read the most recent migration version from an existing ledger."""

    with engine.connect() as connection:
        value = connection.execute(
            text("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
        ).scalar_one()
    return int(value)


def _require_sqlite(engine: Engine) -> None:
    """Keep the initial migration contract narrow and explicit."""

    if engine.dialect.name != "sqlite":
        raise MigrationError("schema migrations currently support SQLite only")
