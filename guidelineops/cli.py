"""Command-line interface for GuidelineOps-CN."""

import typer

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


if __name__ == "__main__":
    app()
