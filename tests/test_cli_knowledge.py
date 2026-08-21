import json
from pathlib import Path

from typer.testing import CliRunner

from guidelineops.cli import app


def _unit_payload() -> dict[str, object]:
    return {
        "unit_id": "ku-1",
        "source_record_id": "pubmed:1",
        "domain": "western_medicine",
        "statement": "Use a documented source statement.",
        "source_locator": {"section": "Recommendations"},
        "version": "2024-1",
    }


def test_knowledge_validate_accepts_json_array(tmp_path: Path) -> None:
    source = tmp_path / "knowledge.json"
    source.write_text(json.dumps([_unit_payload()]), encoding="utf-8")

    result = CliRunner().invoke(app, ["knowledge-validate", str(source)])

    assert result.exit_code == 0, result.output
    assert "Validated knowledge units: 1" in result.output


def test_knowledge_validate_reports_invalid_unit(tmp_path: Path) -> None:
    source = tmp_path / "knowledge.json"
    payload = _unit_payload()
    payload["source_locator"] = {}
    source.write_text(json.dumps(payload), encoding="utf-8")

    result = CliRunner().invoke(app, ["knowledge-validate", str(source)])

    assert result.exit_code == 2
    assert "source_locator" in result.output
