"""Offline importer for user-exported Wanfang metadata CSV files."""

from pathlib import Path

from ._csv_import import ImportResult, import_csv


def import_wanfang_csv(csv_path: str | Path, output_dir: str | Path) -> ImportResult:
    return import_csv("wanfang", csv_path, output_dir)
