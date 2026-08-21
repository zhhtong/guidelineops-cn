from pathlib import Path

from sqlalchemy import text

from guidelineops.database import Base, create_engine
from guidelineops.migrations import LATEST_SCHEMA_VERSION, migrate_database


def test_migrate_database_records_initial_schema(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'managed.db'}")

    status = migrate_database(engine)

    assert status.current_version == LATEST_SCHEMA_VERSION
    assert status.pending_versions == ()
    with engine.connect() as connection:
        versions = connection.execute(
            text("SELECT version FROM schema_migrations ORDER BY version")
        ).scalars().all()
    assert versions == [1]


def test_migrate_database_baselines_legacy_current_schema(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)

    status = migrate_database(engine)

    assert status.current_version == LATEST_SCHEMA_VERSION
    assert status.baselined_legacy_database is True
