from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from guidelineops.config import Settings
from guidelineops.sources.crossref import CrossrefAdapter

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        crossref_mailto="researcher@example.org", data_dir=tmp_path / "data"
    )


@pytest.mark.asyncio
@respx.mock
async def test_crossref_search_normalizes_work_and_provenance(
    settings: Settings,
) -> None:
    payload = json.loads((FIXTURES / "crossref_works.json").read_text())
    route = respx.get("https://api.crossref.org/works").mock(
        return_value=httpx.Response(200, json=payload)
    )

    records = await CrossrefAdapter(settings, request_interval_seconds=0).search(
        "COPD guideline", limit=1
    )

    assert route.called
    assert records[0].source_record_id == "10.1000/example"
    assert records[0].doi == "10.1000/example"
    assert records[0].authors == ["Wang Li"]
    assert records[0].journal == "Example Medical Journal"
    assert records[0].publication_year == 2024
    assert records[0].organization == "Example Publisher"
    assert records[0].metadata["issn"] == ["1234-5678"]
    assert records[0].metadata["license_urls"] == [
        "https://creativecommons.org/licenses/by/4.0/"
    ]
    assert json.loads(Path(records[0].raw_path).read_text()) == payload


@pytest.mark.asyncio
@respx.mock
async def test_crossref_doi_lookup_fills_metadata_without_overwriting_record(
    settings: Settings,
) -> None:
    payload = json.loads((FIXTURES / "crossref_works.json").read_text())
    lookup_payload = {"message": payload["message"]["items"][0]}
    respx.get("https://api.crossref.org/works/10.1000%2Fexample").mock(
        return_value=httpx.Response(200, json=lookup_payload)
    )
    record = await CrossrefAdapter(settings, request_interval_seconds=0).lookup_doi(
        "10.1000/example"
    )

    assert record.doi == "10.1000/example"
    assert record.organization == "Example Publisher"
