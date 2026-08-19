"""Official NCBI E-utilities adapter for PubMed metadata."""

from __future__ import annotations

import asyncio
from datetime import date
from time import monotonic

import httpx
from lxml import etree
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from guidelineops.config import Settings
from guidelineops.models import SourceRecord
from guidelineops.provenance import write_snapshot

from .base import AdapterConfigurationError, SourceAdapter


class PubMedAdapter(SourceAdapter):
    """Discover and fetch PubMed records through NCBI's documented API."""

    name = "pubmed"
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(
        self,
        settings: Settings,
        *,
        request_interval_seconds: float | None = None,
    ) -> None:
        self.settings = settings
        self.request_interval_seconds = request_interval_seconds
        self._last_request_at: float | None = None

    async def search(
        self, query: str, *, limit: int = 20, since: int | None = None
    ) -> list[str]:
        """Use ESearch to return PubMed identifiers for a query."""

        self._require_email()
        if limit < 1:
            return []
        params: dict[str, str | int] = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": limit,
        }
        if since is not None:
            params.update({"datetype": "pdat", "mindate": since, "maxdate": "3000"})
        response = await self._get("esearch.fcgi", params)
        payload = response.json()
        return [
            str(identifier)
            for identifier in payload.get("esearchresult", {}).get("idlist", [])
        ]

    async def fetch(self, identifiers: list[str]) -> list[SourceRecord]:
        """Use EFetch, snapshot the XML, then normalize its article metadata."""

        self._require_email()
        if not identifiers:
            return []
        params = {"db": "pubmed", "id": ",".join(identifiers), "retmode": "xml"}
        response = await self._get("efetch.fcgi", params)
        request_url = str(response.request.url)
        raw = response.content
        snapshot = write_snapshot(
            self.settings.data_dir,
            self.name,
            "_".join(identifiers),
            raw,
            request_url=request_url,
            adapter_version="0.1.0",
        )
        records = self.normalize(raw, request_url=request_url)
        return [
            record.model_copy(
                update={
                    "raw_path": snapshot.path,
                    "raw_sha256": snapshot.sha256,
                    "retrieved_at": snapshot.retrieved_at,
                }
            )
            for record in records
        ]

    async def search_and_fetch(
        self, query: str, *, limit: int = 20, since: int | None = None
    ) -> list[SourceRecord]:
        """Discover identifiers and fetch their normalized metadata."""

        return await self.fetch(await self.search(query, limit=limit, since=since))

    def normalize(self, raw: bytes, *, request_url: str) -> list[SourceRecord]:
        """Parse a PubMed EFetch XML response into normalized records."""

        root = etree.fromstring(raw)
        records: list[SourceRecord] = []
        for article in root.xpath("./PubmedArticle"):
            pmid = _text(article, "./MedlineCitation/PMID")
            title = _text(article, "./MedlineCitation/Article/ArticleTitle")
            if not pmid or not title:
                continue
            article_date = _publication_date(article)
            publication_types = _texts(
                article, "./MedlineCitation/Article/PublicationTypeList/PublicationType"
            )
            mesh_terms = _texts(
                article, "./MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName"
            )
            doi = _article_id(article, "doi")
            records.append(
                SourceRecord(
                    source=self.name,
                    source_record_id=pmid,
                    title=title,
                    authors=_authors(article),
                    journal=_text(article, "./MedlineCitation/Article/Journal/Title"),
                    publication_year=article_date.year if article_date else None,
                    publication_date=article_date,
                    doi=doi,
                    pmid=pmid,
                    abstract=_abstract(article),
                    source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    language=_text(article, "./MedlineCitation/Article/Language"),
                    metadata={
                        "publication_types": publication_types,
                        "mesh_terms": mesh_terms,
                        "request_url": request_url,
                    },
                )
            )
        return records

    def _require_email(self) -> None:
        if not self.settings.ncbi_email:
            raise AdapterConfigurationError(
                "NCBI_EMAIL must be configured before using the PubMed adapter."
            )

    @property
    def _interval(self) -> float:
        if self.request_interval_seconds is not None:
            return self.request_interval_seconds
        return 0.1 if self.settings.ncbi_api_key else 1 / 3

    async def _throttle(self) -> None:
        if self._last_request_at is not None:
            remaining = self._interval - (monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last_request_at = monotonic()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError,)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _get(self, endpoint: str, params: dict[str, str | int]) -> httpx.Response:
        await self._throttle()
        request_params = {
            **params,
            "tool": self.settings.ncbi_tool,
            "email": self.settings.ncbi_email or "",
        }
        if self.settings.ncbi_api_key:
            request_params["api_key"] = self.settings.ncbi_api_key
        headers = {
            "User-Agent": f"{self.settings.ncbi_tool} ({self.settings.ncbi_email})"
        }
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(
                f"{self.base_url}/{endpoint}", params=request_params
            )
            response.raise_for_status()
            return response


def _text(element: etree._Element, xpath: str) -> str | None:
    nodes = element.xpath(xpath)
    if not nodes:
        return None
    return "".join(nodes[0].itertext()).strip() or None


def _texts(element: etree._Element, xpath: str) -> list[str]:
    return [
        text
        for node in element.xpath(xpath)
        if (text := "".join(node.itertext()).strip())
    ]


def _article_id(article: etree._Element, identifier_type: str) -> str | None:
    identifiers = article.xpath(
        "./PubmedData/ArticleIdList/ArticleId[@IdType=$type]", type=identifier_type
    )
    return "".join(identifiers[0].itertext()).strip() if identifiers else None


def _authors(article: etree._Element) -> list[str]:
    authors: list[str] = []
    for author in article.xpath("./MedlineCitation/Article/AuthorList/Author"):
        parts = [_text(author, "./LastName"), _text(author, "./ForeName")]
        name = " ".join(part for part in parts if part)
        if name:
            authors.append(name)
    return authors


def _abstract(article: etree._Element) -> str | None:
    sections = []
    for node in article.xpath("./MedlineCitation/Article/Abstract/AbstractText"):
        text = "".join(node.itertext()).strip()
        if text:
            label = node.get("Label")
            sections.append(f"{label}: {text}" if label else text)
    return "\n".join(sections) or None


def _publication_date(article: etree._Element) -> date | None:
    year = _text(article, "./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year")
    if year and year.isdigit():
        return date(int(year), 1, 1)
    medline_date = _text(
        article, "./MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate"
    )
    if medline_date:
        digits = medline_date[:4]
        if digits.isdigit():
            return date(int(digits), 1, 1)
    return None
