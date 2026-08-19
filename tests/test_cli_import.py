from pathlib import Path

from typer.testing import CliRunner

from guidelineops.cli import app


def test_import_file_reports_counts_and_writes_database(
    monkeypatch, tmp_path: Path
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "wanfang_sample.csv"
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'db.sqlite'}")

    result = CliRunner().invoke(
        app, ["import-file", "--source", "wanfang", str(fixture)]
    )

    assert result.exit_code == 0, result.output
    assert "Imported records: 1" in result.output
    assert (tmp_path / "db.sqlite").exists()
