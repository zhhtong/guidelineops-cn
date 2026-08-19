"""Shared, offline CSV import logic for licensed user exports."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from guidelineops.models import SourceRecord


@dataclass(frozen=True)
class ImportResult:
    """Imported records and row-level errors from one CSV file."""

    records: list[SourceRecord]
    errors: list[dict[str, object]]
    error_path: Path

    @property
    def imported_count(self) -> int:
        return len(self.records)

    @property
    def error_count(self) -> int:
        return len(self.errors)


ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("题名", "标题", "篇名", "title", "name"),
    "authors": ("作者", "authors", "author"),
    "journal": ("来源", "期刊", "journal", "source"),
    "year": ("发表年度", "发表年份", "年份", "年", "year", "publication_year"),
    "doi": ("doi", "数字对象唯一标识符"),
    "abstract": ("摘要", "abstract"),
    "url": ("链接", "来源链接", "url", "source_url"),
    "source_record_id": ("文献id", "文献编号", "记录id", "id", "record_id"),
}


def import_csv(
    source: str, csv_path: str | Path, output_dir: str | Path
) -> ImportResult:
    """Import a CNKI/Wanfang-style export without network access."""

    csv_path = Path(csv_path)
    output_dir = Path(output_dir)
    records: list[SourceRecord] = []
    errors: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = {normalize_header(name): name for name in reader.fieldnames or []}
        mapping = {
            field: headers[normalize_header(alias)]
            for field, aliases in ALIASES.items()
            for alias in aliases
            if normalize_header(alias) in headers
        }
        for row_number, row in enumerate(reader, start=2):
            title = _value(row, mapping.get("title"))
            if not title:
                errors.append(
                    {"row_number": row_number, "error": "missing title", **row}
                )
                continue
            source_record_id = _value(row, mapping.get("source_record_id"))
            doi = _value(row, mapping.get("doi"))
            source_record_id = source_record_id or doi or f"row-{row_number}"
            try:
                records.append(
                    SourceRecord(
                        source=source,
                        source_record_id=source_record_id,
                        title=title,
                        authors=_authors(_value(row, mapping.get("authors"))),
                        journal=_value(row, mapping.get("journal")),
                        publication_year=_year(_value(row, mapping.get("year"))),
                        doi=doi,
                        abstract=_value(row, mapping.get("abstract")),
                        source_url=_value(row, mapping.get("url")),
                        metadata={
                            "import_file": str(csv_path),
                            "import_row": row_number,
                        },
                    )
                )
            except (TypeError, ValueError) as error:
                errors.append({"row_number": row_number, "error": str(error), **row})

    output_dir.mkdir(parents=True, exist_ok=True)
    error_path = output_dir / "import_errors.csv"
    if errors:
        fields = sorted({key for error in errors for key in error})
        with error_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(errors)
    elif error_path.exists():
        error_path.unlink()
    return ImportResult(records, errors, error_path)


def normalize_header(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value.strip().casefold())


def _value(row: dict[str, str | None], key: str | None) -> str | None:
    if key is None:
        return None
    value = row.get(key)
    return value.strip() if value and value.strip() else None


def _authors(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[;；]", value) if item.strip()]


def _year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d{4}", value)
    if not match:
        raise ValueError(f"invalid publication year: {value}")
    return int(match.group())
