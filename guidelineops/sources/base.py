"""Shared contracts and errors for metadata-source adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from guidelineops.models import SourceRecord


class AdapterConfigurationError(RuntimeError):
    """Raised when an adapter lacks a required runtime configuration value."""


class SourceAdapter(ABC):
    """Contract for source-specific discovery, fetch, and normalization."""

    name: str

    @abstractmethod
    async def search(
        self, query: str, *, limit: int = 20, since: int | None = None
    ) -> list[str]:
        """Return source-specific identifiers for a discovery query."""

    @abstractmethod
    async def fetch(self, identifiers: list[str]) -> list[SourceRecord]:
        """Fetch and normalize records for source-specific identifiers."""

    @abstractmethod
    def normalize(self, raw: bytes, *, request_url: str) -> list[SourceRecord]:
        """Normalize one raw response into source records."""

    def provenance(self, raw: bytes) -> dict[str, Any]:
        """Return lightweight source-specific provenance details."""

        return {"source": self.name, "raw_bytes": len(raw)}
