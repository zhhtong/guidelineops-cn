from guidelineops.normalization import normalize_doi, normalize_title


def test_normalize_title_collapses_unicode_whitespace_and_casefolds_ascii() -> None:
    assert normalize_title("  ＡＢC\t  指南　的  TEST  ") == "abc 指南 的 test"


def test_normalize_title_preserves_chinese_text() -> None:
    assert normalize_title("  高血压指南  ") == "高血压指南"


def test_normalize_doi_removes_supported_prefixes_and_trailing_punctuation() -> None:
    assert normalize_doi("https://doi.org/10.1000/ABC.1 ") == "10.1000/abc.1"
    assert normalize_doi("DOI: 10.1000/ABC.2。") == "10.1000/abc.2"
    assert normalize_doi("http://dx.doi.org/10.1000/ABC.3)") == "10.1000/abc.3"
    assert normalize_doi(" doi.org/10.1000/ABC.4, ") == "10.1000/abc.4"


def test_normalize_doi_returns_none_for_empty_values() -> None:
    assert normalize_doi(None) is None
    assert normalize_doi("") is None
    assert normalize_doi(" \t\n ") is None


def test_normalize_title_returns_none_for_none() -> None:
    assert normalize_title(None) is None
