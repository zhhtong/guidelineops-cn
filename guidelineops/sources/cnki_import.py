"""Offline importer for user-exported CNKI metadata CSV files."""

from pathlib import Path

from ._csv_import import ImportResult, import_csv


def import_cnki_csv(csv_path: str | Path, output_dir: str | Path) -> ImportResult:
    return import_csv("cnki", csv_path, output_dir)
