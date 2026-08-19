from typer.testing import CliRunner

from guidelineops.cli import app


def test_pubmed_search_reports_missing_email_without_network(monkeypatch) -> None:
    monkeypatch.delenv("NCBI_EMAIL", raising=False)
    result = CliRunner().invoke(
        app, ["pubmed-search", "COPD guideline", "--limit", "1"]
    )

    assert result.exit_code == 2
    assert "NCBI_EMAIL" in result.output
