"""Portable UTF-8 exports for candidate guideline records."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .models import SourceRecord

EXPORT_FIELDS = tuple(SourceRecord.model_fields)


def export_records(
    records: Iterable[SourceRecord], output_dir: str | Path, format: str
) -> Path:
    """Write records as UTF-8 CSV or JSON Lines and return the output path."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if format not in {"csv", "jsonl"}:
        raise ValueError("format must be csv or jsonl")
    path = output_dir / f"guideline_candidates.{format}"
    serialized = [record.model_dump(mode="json") for record in records]
    if format == "jsonl":
        path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in serialized),
            encoding="utf-8",
        )
        return path

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        for item in serialized:
            row = {field: _csv_value(item.get(field)) for field in EXPORT_FIELDS}
            writer.writerow(row)
    return path


def _csv_value(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value
