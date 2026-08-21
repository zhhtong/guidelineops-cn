"""Command-line interface for GuidelineOps-CN."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import typer
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from .config import Settings
from .database import (
    CanonicalGuidelineRow,
    KnowledgeUnitRow,
    SourceRecordRow,
    create_engine,
    init_database,
    knowledge_unit_from_row,
    submit_knowledge_unit,
    upsert_knowledge_unit,
    upsert_source_record,
)
from .dedup import group_records
from .export import export_records
from .knowledge import KnowledgeUnit
from .models import SourceRecord
from .quality import build_quality_report, render_markdown, report_json
from .review_queue import (
    ReviewQueueError,
    claim_task,
    decide_task,
    event_mapping,
    list_review_events,
    list_review_tasks,
    sync_knowledge_review_tasks,
    sync_review_tasks,
    task_mapping,
)
from .reviewers import ReviewerRegistryError, authorize_reviewer
from .sources.base import AdapterConfigurationError
from .sources.cnki_import import import_cnki_csv
from .sources.crossref import CrossrefAdapter
from .sources.pubmed import PubMedAdapter
from .sources.wanfang_import import import_wanfang_csv

app = typer.Typer(
    name="guidelineops",
    help=(
        "GuidelineOps-CN: research and educational tools for evidence-oriented "
        "guideline operations. Not for clinical decision-making."
    ),
    add_completion=False,
)


@app.callback()
def main() -> None:
    """Use GuidelineOps-CN for research and education only, never clinical decisions."""


@app.command("pubmed-search")
def pubmed_search(
    query: str,
    limit: int = typer.Option(20, min=1, max=1000),
    since: int | None = typer.Option(None, help="Earliest publication year."),
) -> None:
    """Search PubMed and print normalized records as JSON Lines."""

    try:
        records = asyncio.run(
            PubMedAdapter(Settings()).search_and_fetch(query, limit=limit, since=since)
        )
    except AdapterConfigurationError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    for record in records:
        typer.echo(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))


@app.command("crossref-search")
def crossref_search(
    query: str,
    limit: int = typer.Option(20, min=1, max=1000),
) -> None:
    """Search Crossref works by title and print normalized JSON Lines."""

    records = asyncio.run(CrossrefAdapter(Settings()).search(query, limit=limit))
    for record in records:
        typer.echo(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))


@app.command("crossref-enrich")
def crossref_enrich(
    doi: str = typer.Argument(..., help="DOI to resolve through Crossref."),
) -> None:
    """Resolve one DOI and print the enriched Crossref metadata."""

    record = asyncio.run(CrossrefAdapter(Settings()).lookup_doi(doi))
    typer.echo(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))


@app.command("import-file")
def import_file(
    source: str = typer.Option(..., help="Source name: cnki or wanfang."),
    file: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Import a user-exported CNKI or Wanfang CSV without web access."""

    settings = Settings()
    output_dir = Path(settings.data_dir)
    if source == "cnki":
        result = import_cnki_csv(file, output_dir)
    elif source == "wanfang":
        result = import_wanfang_csv(file, output_dir)
    else:
        raise typer.BadParameter(
            "source must be cnki or wanfang", param_hint="--source"
        )

    engine = _database_engine(settings)

    with Session(engine) as session:
        for record in result.records:
            upsert_source_record(session, record)
        session.commit()
    typer.echo(f"Imported records: {result.imported_count}")
    typer.echo(f"Import errors: {result.error_count}")
    typer.echo(f"Database: {settings.database_url}")


@app.command("discover")
def discover(
    disease: str = typer.Option(..., help="Disease or guideline search phrase."),
    since: int | None = typer.Option(None, help="Earliest publication year."),
    limit: int = typer.Option(20, min=1, max=1000),
) -> None:
    """Run the PubMed-first discovery pipeline and export candidate records."""

    settings = Settings()
    engine = _database_engine(settings)
    pubmed_records, crossref_records = asyncio.run(
        _discover_records(settings, disease, limit=limit, since=since)
    )
    init_database(engine)
    with Session(engine) as session:
        for record in [*pubmed_records, *crossref_records]:
            upsert_source_record(session, record)
        session.commit()
        rows = list(session.scalars(select(SourceRecordRow)))
        canonical_count = session.scalar(
            select(func.count()).select_from(CanonicalGuidelineRow)
        )

    all_records = [SourceRecord.model_validate(row.record_data) for row in rows]
    result = group_records([*pubmed_records, *crossref_records])
    csv_path = export_records(all_records, settings.data_dir, "csv")
    jsonl_path = export_records(all_records, settings.data_dir, "jsonl")
    typer.echo("GuidelineOps Discovery")
    typer.echo(f"PubMed records: {len(pubmed_records)}")
    typer.echo(f"Crossref enriched: {len(crossref_records)}")
    typer.echo("Imported records: 0")
    typer.echo(f"Source records: {len(rows)}")
    typer.echo(f"Canonical records: {canonical_count or 0}")
    typer.echo(f"Duplicate groups: {len(result.candidates)}")
    typer.echo(f"CSV: {csv_path}")
    typer.echo(f"JSONL: {jsonl_path}")


@app.command("quality-report")
def quality_report() -> None:
    """Write a deterministic metadata quality report for persisted records."""

    settings = Settings()
    engine = _database_engine(settings)
    with Session(engine) as session:
        rows = list(
            session.scalars(select(SourceRecordRow).order_by(SourceRecordRow.id))
        )
        canonical_count = session.scalar(
            select(func.count()).select_from(CanonicalGuidelineRow)
        )

    records = [SourceRecord.model_validate(row.record_data) for row in rows]
    report = build_quality_report(
        records, canonical_records=canonical_count or 0
    )

    output_dir = Path(settings.data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "quality_report.json"
    markdown_path = output_dir / "quality_report.md"
    _atomic_write_reports(
        json_path,
        report_json(report),
        markdown_path,
        render_markdown(report),
    )

    typer.echo(f"Records: {report.total_records}")
    typer.echo(f"JSON: {json_path}")
    typer.echo(f"Markdown: {markdown_path}")


@app.command("knowledge-validate")
def knowledge_validate(
    file: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Validate source-grounded knowledge-unit JSON without clinical inference."""

    units = _load_knowledge_units(file)
    typer.echo(f"Validated knowledge units: {len(units)}")


@app.command("knowledge-import")
def knowledge_import(
    file: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Validate and idempotently persist knowledge-unit JSON."""

    units = _load_knowledge_units(file)
    settings = Settings()
    engine = _database_engine(settings)
    with Session(engine) as session:
        for unit in units:
            upsert_knowledge_unit(session, unit)
        session.commit()
    typer.echo(f"Imported knowledge units: {len(units)}")


@app.command("knowledge-list")
def knowledge_list() -> None:
    """Print persisted knowledge units as deterministic JSON Lines."""

    settings = Settings()
    engine = _database_engine(settings)
    with Session(engine) as session:
        rows = session.scalars(
            select(KnowledgeUnitRow).order_by(KnowledgeUnitRow.unit_id)
        )
        for row in rows:
            unit = knowledge_unit_from_row(row)
            typer.echo(json.dumps(unit.model_dump(mode="json"), ensure_ascii=False))


@app.command("knowledge-submit")
def knowledge_submit(
    unit_id: str = typer.Argument(..., help="Stable knowledge-unit ID."),
) -> None:
    """Submit one imported knowledge unit for medical review."""

    settings = Settings()
    engine = _database_engine(settings)
    with Session(engine) as session:
        try:
            row = submit_knowledge_unit(session, unit_id)
            unit_payload = knowledge_unit_from_row(row).model_dump(mode="json")
            session.commit()
        except ValueError as error:
            session.rollback()
            typer.echo(str(error), err=True)
            raise typer.Exit(code=2) from error
    typer.echo(
        json.dumps(unit_payload, ensure_ascii=False)
    )


@app.command("review-sync")
def review_sync() -> None:
    """Synchronize metadata risks and duplicate candidates into review tasks."""

    settings = Settings()
    engine = _database_engine(settings)
    with Session(engine) as session:
        records = [
            SourceRecord.model_validate(row.record_data)
            for row in session.scalars(
                select(SourceRecordRow).order_by(SourceRecordRow.id)
            )
        ]
        result = sync_review_tasks(session, records)
        knowledge_result = sync_knowledge_review_tasks(session)
        session.commit()
    typer.echo(f"Created: {result.created + knowledge_result.created}")
    typer.echo(f"Refreshed: {result.refreshed + knowledge_result.refreshed}")
    typer.echo(f"Superseded: {result.superseded + knowledge_result.superseded}")


@app.command("review-list")
def review_list(
    status: str | None = typer.Option(None, help="Optional review-task status."),
) -> None:
    """Print deterministic JSON Lines for current review tasks."""

    settings = Settings()
    engine = _database_engine(settings)
    with Session(engine) as session:
        try:
            tasks = list_review_tasks(session, status=status)
        except ReviewQueueError as error:
            _exit_review_error(session, error)
        for task in tasks:
            typer.echo(json.dumps(task_mapping(task), ensure_ascii=False))


@app.command("review-events")
def review_events(
    task_id: int = typer.Argument(..., help="Review task ID."),
) -> None:
    """Print the append-only audit history for one review task."""

    settings = Settings()
    engine = _database_engine(settings)
    with Session(engine) as session:
        try:
            events = list_review_events(session, task_id)
        except ReviewQueueError as error:
            _exit_review_error(session, error)
        for event in events:
            typer.echo(json.dumps(event_mapping(event), ensure_ascii=False))


@app.command("review-claim")
def review_claim(
    task_id: int = typer.Argument(..., help="Review task ID."),
    reviewer: str = typer.Option(..., help="Named reviewer claiming the task."),
    reviewer_role: str = typer.Option(
        ..., "--role", help="Declared role for this review action."
    ),
) -> None:
    """Claim an open or deferred task for a reviewer."""

    _run_review_mutation(
        lambda session: claim_task(
            session,
            task_id,
            reviewer=reviewer,
            reviewer_role=reviewer_role,
        ),
        reviewer=reviewer,
        reviewer_role=reviewer_role,
    )


@app.command("review-approve")
def review_approve(
    task_id: int = typer.Argument(..., help="Review task ID."),
    reviewer: str = typer.Option(..., help="Named reviewer making the decision."),
    reviewer_role: str = typer.Option(
        ..., "--role", help="Declared role for this review action."
    ),
    note: str | None = typer.Option(None, help="Optional review note."),
) -> None:
    """Approve a task claimed by the named reviewer."""

    _run_review_mutation(
        lambda session: decide_task(
            session,
            task_id,
            reviewer=reviewer,
            reviewer_role=reviewer_role,
            decision="approved",
            reason=note,
        ),
        reviewer=reviewer,
        reviewer_role=reviewer_role,
    )


@app.command("review-reject")
def review_reject(
    task_id: int = typer.Argument(..., help="Review task ID."),
    reviewer: str = typer.Option(..., help="Named reviewer making the decision."),
    reviewer_role: str = typer.Option(
        ..., "--role", help="Declared role for this review action."
    ),
    reason: str = typer.Option(..., help="Required reason for rejection."),
) -> None:
    """Reject a task claimed by the named reviewer."""

    _run_review_mutation(
        lambda session: decide_task(
            session,
            task_id,
            reviewer=reviewer,
            reviewer_role=reviewer_role,
            decision="rejected",
            reason=reason,
        ),
        reviewer=reviewer,
        reviewer_role=reviewer_role,
    )


@app.command("review-defer")
def review_defer(
    task_id: int = typer.Argument(..., help="Review task ID."),
    reviewer: str = typer.Option(..., help="Named reviewer making the decision."),
    reviewer_role: str = typer.Option(
        ..., "--role", help="Declared role for this review action."
    ),
    reason: str = typer.Option(..., help="Required reason for deferral."),
) -> None:
    """Defer a task claimed by the named reviewer."""

    _run_review_mutation(
        lambda session: decide_task(
            session,
            task_id,
            reviewer=reviewer,
            reviewer_role=reviewer_role,
            decision="deferred",
            reason=reason,
        ),
        reviewer=reviewer,
        reviewer_role=reviewer_role,
    )


def _run_review_mutation(operation, *, reviewer: str, reviewer_role: str) -> None:
    """Commit a successful review action or roll back a rejected transition."""

    settings = Settings()
    try:
        authorize_reviewer(
            settings.reviewer_registry_path,
            reviewer=reviewer,
            reviewer_role=reviewer_role,
        )
    except ReviewerRegistryError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    engine = _database_engine(settings)
    with Session(engine) as session:
        try:
            task = operation(session)
            session.commit()
        except ReviewQueueError as error:
            _exit_review_error(session, error)
        typer.echo(json.dumps(task_mapping(task), ensure_ascii=False))


def _load_knowledge_units(file: Path) -> list[KnowledgeUnit]:
    """Load and validate one knowledge-unit object or a JSON array."""

    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        typer.echo(f"Invalid knowledge JSON: {error}", err=True)
        raise typer.Exit(code=2) from error

    if isinstance(payload, dict):
        items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        typer.echo("Knowledge JSON must be an object or an array", err=True)
        raise typer.Exit(code=2)

    units: list[KnowledgeUnit] = []
    for index, item in enumerate(items, start=1):
        try:
            units.append(KnowledgeUnit.model_validate(item))
        except (TypeError, ValidationError) as error:
            typer.echo(f"Invalid knowledge unit {index}: {error}", err=True)
            raise typer.Exit(code=2) from error
    return units


def _exit_review_error(session: Session, error: ReviewQueueError) -> None:
    """Roll back a rejected review transition and exit consistently."""

    session.rollback()
    typer.echo(str(error), err=True)
    raise typer.Exit(code=2) from error


def _write_temp_text(path: Path, content: str, *, prefix: str) -> Path:
    """Write UTF-8 text to a durable same-directory temporary file."""

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=prefix,
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        return temporary_path
    except BaseException:
        if temporary_path is not None:
            _remove_temp_file(temporary_path)
        raise


def _write_temp_bytes(path: Path, content: bytes, *, prefix: str) -> Path:
    """Write bytes to a durable same-directory temporary file."""

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=prefix,
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        return temporary_path
    except BaseException:
        if temporary_path is not None:
            _remove_temp_file(temporary_path)
        raise


def _remove_temp_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _atomic_write_reports(
    json_path: Path,
    json_content: str,
    markdown_path: Path,
    markdown_content: str,
) -> None:
    """Prepare both reports before replacing either final artifact."""

    targets = (
        (json_path, json_content),
        (markdown_path, markdown_content),
    )
    if any(path.is_dir() for path, _ in targets):
        raise IsADirectoryError("quality report output path is a directory")

    temporary_paths: list[Path] = []
    backup_paths: dict[Path, Path] = {}
    replaced_targets: list[Path] = []
    try:
        for path, content in targets:
            temporary_paths.append(
                _write_temp_text(path, content, prefix=f".{path.name}.")
            )
        for path, _ in targets:
            if path.exists():
                backup_paths[path] = _write_temp_bytes(
                    path,
                    path.read_bytes(),
                    prefix=f".{path.name}.backup.",
                )

        for (path, _), temporary_path in zip(targets, temporary_paths):
            replaced_targets.append(path)
            os.replace(temporary_path, path)
    except BaseException:
        for path in reversed(replaced_targets):
            backup_path = backup_paths.get(path)
            if backup_path is None:
                _remove_temp_file(path)
            else:
                try:
                    os.replace(backup_path, path)
                except OSError:
                    pass
        raise
    finally:
        for temporary_path in temporary_paths:
            _remove_temp_file(temporary_path)
        for backup_path in backup_paths.values():
            _remove_temp_file(backup_path)


async def _discover_records(
    settings: Settings, disease: str, *, limit: int, since: int | None
) -> tuple[list[SourceRecord], list[SourceRecord]]:
    pubmed_records = await PubMedAdapter(settings).search_and_fetch(
        disease, limit=limit, since=since
    )
    crossref_adapter = CrossrefAdapter(settings)
    crossref_records = []
    for record in pubmed_records:
        if record.doi:
            crossref_records.append(await crossref_adapter.lookup_doi(record.doi))
    return pubmed_records, crossref_records


def _database_engine(settings: Settings):
    database_url = make_url(settings.database_url)
    if database_url.get_backend_name() == "sqlite":
        database_name = database_url.database
        if database_name and database_name != ":memory:":
            database_path = Path(database_name)
            database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url)
    init_database(engine)
    return engine


if __name__ == "__main__":
    app()
