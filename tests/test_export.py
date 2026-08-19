import json
from pathlib import Path

from guidelineops.export import export_records
from guidelineops.models import SourceRecord


def test_export_csv_and_jsonl_preserve_chinese_title(tmp_path: Path) -> None:
    records = [
        SourceRecord(
            source="manual",
            source_record_id="1",
            title="中西医结合指南",
            metadata={"quality": "verified"},
        )
    ]

    csv_path = export_records(records, tmp_path, "csv")
    jsonl_path = export_records(records, tmp_path, "jsonl")

    assert "中西医结合指南" in csv_path.read_text(encoding="utf-8")
    assert json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])[
        "title"
    ] == ("中西医结合指南")
