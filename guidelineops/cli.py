"""Command-line interface for GuidelineOps-CN."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .database import (
    CanonicalGuidelineRow,
    SourceRecordRow,
    create_engine,
    init_database,
    upsert_source_record,
)
from .dedup import group_records
from .export import export_records
from .models import SourceRecord
from .quality import build_quality_report, render_markdown, report_json
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
        rows = list(session.scalars(select(SourceRecordRow)))
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
    json_path.write_text(report_json(report), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")

    typer.echo(f"Records: {report.total_records}")
    typer.echo(f"JSON: {json_path}")
    typer.echo(f"Markdown: {markdown_path}")


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
    database_path = Path(settings.database_url.removeprefix("sqlite:///"))
    if database_path.name != ":memory:":
        database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url)
    init_database(engine)
    return engine


if __name__ == "__main__":
    app()
