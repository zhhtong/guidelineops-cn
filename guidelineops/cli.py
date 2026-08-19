"""Command-line interface for GuidelineOps-CN."""

from __future__ import annotations

import asyncio
import json

import typer

from .config import Settings
from .sources.base import AdapterConfigurationError
from .sources.pubmed import PubMedAdapter

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


if __name__ == "__main__":
    app()
