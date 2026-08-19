from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from guidelineops.config import Settings
from guidelineops.sources.base import AdapterConfigurationError
from guidelineops.sources.pubmed import PubMedAdapter

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(ncbi_email="researcher@example.org", data_dir=tmp_path / "data")


@pytest.mark.asyncio
@respx.mock
async def test_pubmed_search_fetch_and_parse(settings: Settings) -> None:
    search_route = respx.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"count": "1", "idlist": ["12345678"]}},
        )
    )
    fetch_route = respx.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    ).mock(
        return_value=httpx.Response(
            200, content=(FIXTURES / "pubmed_fetch.xml").read_bytes()
        )
    )

    records = await PubMedAdapter(
        settings, request_interval_seconds=0
    ).search_and_fetch("COPD guideline", limit=10, since=2015)

    assert search_route.called
    assert fetch_route.called
    assert records[0].pmid == "12345678"
    assert records[0].doi == "10.1000/example"
    assert records[0].title == "Clinical Practice Guideline for COPD"
    assert records[0].authors == ["Wang Li"]
    assert records[0].journal == "Example Medical Journal"
    assert records[0].publication_year == 2024
    assert records[0].metadata["publication_types"] == ["Practice Guideline"]
    assert records[0].metadata["mesh_terms"] == ["COPD"]
    assert records[0].raw_path is not None
    assert (
        Path(records[0].raw_path).read_bytes()
        == (FIXTURES / "pubmed_fetch.xml").read_bytes()
    )


@pytest.mark.asyncio
async def test_pubmed_requires_email_only_when_used(tmp_path: Path) -> None:
    adapter = PubMedAdapter(
        Settings(data_dir=tmp_path / "data"), request_interval_seconds=0
    )

    with pytest.raises(AdapterConfigurationError, match="NCBI_EMAIL"):
        await adapter.search("COPD guideline")
