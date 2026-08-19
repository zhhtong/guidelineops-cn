from typer.testing import CliRunner

from guidelineops.cli import app


def test_cli_help_identifies_guidelineops_cn() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "GuidelineOps-CN" in result.stdout
