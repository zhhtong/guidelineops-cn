"""Crossref REST API adapter for bibliographic metadata."""

from __future__ import annotations

import asyncio
from datetime import date
from time import monotonic
from urllib.parse import quote

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from guidelineops.config import Settings
from guidelineops.models import SourceRecord
from guidelineops.provenance import write_snapshot

from .base import SourceAdapter


class CrossrefAdapter(SourceAdapter):
    """Search and resolve works through Crossref's public REST API."""

    name = "crossref"
    base_url = "https://api.crossref.org"

    def __init__(
        self,
        settings: Settings,
        *,
        request_interval_seconds: float = 0.05,
    ) -> None:
        self.settings = settings
        self.request_interval_seconds = request_interval_seconds
        self._last_request_at: float | None = None

    async def search(
        self, query: str, *, limit: int = 20, since: int | None = None
    ) -> list[SourceRecord]:
        """Search Crossref works by title and normalize returned items."""

        params: dict[str, str | int] = {"query.title": query, "rows": max(1, limit)}
        if since is not None:
            params["filter"] = f"from-pub-date:{since}-01-01"
        response = await self._get("/works", params)
        payload = response.json()
        raw = response.content
        request_url = str(response.request.url)
        items = payload.get("message", {}).get("items", [])
        records = self._normalize_items(items, request_url=request_url)
        if records:
            snapshot = write_snapshot(
                self.settings.data_dir,
                self.name,
                "search",
                raw,
                request_url=request_url,
                adapter_version="0.1.0",
            )
            records = [
                record.model_copy(
                    update={
                        "raw_path": snapshot.path,
                        "raw_sha256": snapshot.sha256,
                        "retrieved_at": snapshot.retrieved_at,
                    }
                )
                for record in records
            ]
        return records

    async def fetch(self, identifiers: list[str]) -> list[SourceRecord]:
        """Resolve a list of DOI identifiers one at a time."""

        records: list[SourceRecord] = []
        for identifier in identifiers:
            records.append(await self.lookup_doi(identifier))
        return records

    async def lookup_doi(self, doi: str) -> SourceRecord:
        """Resolve one DOI and return its Crossref metadata."""

        normalized_doi = doi.strip().lower()
        endpoint = f"/works/{quote(normalized_doi, safe='')}"
        response = await self._get(endpoint, {})
        payload = response.json()
        item = payload.get("message", {})
        request_url = str(response.request.url)
        record = self._normalize_item(item, request_url=request_url)
        snapshot = write_snapshot(
            self.settings.data_dir,
            self.name,
            normalized_doi,
            response.content,
            request_url=request_url,
            adapter_version="0.1.0",
        )
        return record.model_copy(
            update={
                "raw_path": snapshot.path,
                "raw_sha256": snapshot.sha256,
                "retrieved_at": snapshot.retrieved_at,
            }
        )

    def normalize(self, raw: bytes, *, request_url: str) -> list[SourceRecord]:
        """Normalize a saved Crossref response containing works or one message."""

        payload = httpx.Response(200, content=raw).json()
        message = payload.get("message", {})
        items = message.get("items") if isinstance(message, dict) else None
        return self._normalize_items(items or [message], request_url=request_url)

    def _normalize_items(
        self, items: list[dict[str, object]], *, request_url: str
    ) -> list[SourceRecord]:
        return [
            self._normalize_item(item, request_url=request_url)
            for item in items
            if item.get("DOI") or item.get("title")
        ]

    def _normalize_item(
        self, item: dict[str, object], *, request_url: str
    ) -> SourceRecord:
        doi = _string(item.get("DOI"))
        title_values = item.get("title") or []
        title = _string(
            title_values[0]
            if isinstance(title_values, list) and title_values
            else title_values
        )
        if not title:
            title = doi or "Untitled Crossref work"
        authors = []
        for author in item.get("author") or []:
            if isinstance(author, dict):
                name = " ".join(
                    part
                    for part in (
                        _string(author.get("family")),
                        _string(author.get("given")),
                    )
                    if part
                )
                if name:
                    authors.append(name)
        journal_values = item.get("container-title") or []
        journal = _string(
            journal_values[0] if isinstance(journal_values, list) else journal_values
        )
        publication_date = _date_from_parts(item.get("published") or item.get("issued"))
        issn = [str(value) for value in item.get("ISSN", []) or []]
        licenses = [
            str(entry.get("URL"))
            for entry in item.get("license", []) or []
            if isinstance(entry, dict) and entry.get("URL")
        ]
        normalized_doi = doi.lower() if doi else None
        return SourceRecord(
            source=self.name,
            source_record_id=normalized_doi or title,
            title=title,
            authors=authors,
            organization=_string(item.get("publisher")),
            journal=journal,
            publication_year=publication_date.year if publication_date else None,
            publication_date=publication_date,
            doi=normalized_doi,
            source_url=_string(item.get("URL")),
            metadata={
                "issn": issn,
                "license_urls": licenses,
                "type": _string(item.get("type")),
                "request_url": request_url,
            },
        )

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _get(self, endpoint: str, params: dict[str, str | int]) -> httpx.Response:
        if self._last_request_at is not None:
            remaining = self.request_interval_seconds - (
                monotonic() - self._last_request_at
            )
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last_request_at = monotonic()
        headers = {"User-Agent": "GuidelineOps-CN/0.1"}
        if self.settings.crossref_mailto:
            headers["User-Agent"] += f" (mailto:{self.settings.crossref_mailto})"
            params = {**params, "mailto": self.settings.crossref_mailto}
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(f"{self.base_url}{endpoint}", params=params)
            response.raise_for_status()
            return response


def _string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _date_from_parts(value: object) -> date | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
        return None
    numbers = parts[0]
    if not numbers or not isinstance(numbers[0], int):
        return None
    month = numbers[1] if len(numbers) > 1 and isinstance(numbers[1], int) else 1
    day = numbers[2] if len(numbers) > 2 and isinstance(numbers[2], int) else 1
    try:
        return date(numbers[0], month, day)
    except ValueError:
        return None
