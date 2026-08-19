from pathlib import Path

from guidelineops.sources.cnki_import import import_cnki_csv
from guidelineops.sources.wanfang_import import import_wanfang_csv

FIXTURES = Path(__file__).parent / "fixtures"


def test_cnki_import_keeps_good_rows_and_reports_invalid_rows(tmp_path: Path) -> None:
    result = import_cnki_csv(FIXTURES / "cnki_sample.csv", tmp_path)

    assert result.imported_count == 2
    assert result.error_count == 1
    assert result.records[0].source == "cnki"
    assert result.records[0].doi == "10.1000/cnki1"
    assert (tmp_path / "import_errors.csv").exists()


def test_wanfang_import_accepts_english_export_headers(tmp_path: Path) -> None:
    result = import_wanfang_csv(FIXTURES / "wanfang_sample.csv", tmp_path)

    assert result.imported_count == 1
    assert result.error_count == 0
    assert result.records[0].source == "wanfang"
