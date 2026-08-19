from typer.testing import CliRunner

from guidelineops.cli import app


def test_discover_help_describes_research_pipeline() -> None:
    result = CliRunner().invoke(app, ["discover", "--help"])

    assert result.exit_code == 0
    assert "PubMed" in result.output
