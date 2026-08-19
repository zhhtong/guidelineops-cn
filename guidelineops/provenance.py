"""Immutable-on-disk raw snapshots and their cryptographic evidence."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class Snapshot(BaseModel):
    """Description of one raw source response persisted on disk."""

    model_config = ConfigDict(frozen=True)

    path: Path
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_url: str = ""
    adapter_version: str = "0.1.0"


_UNSAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_identifier(value: str) -> str:
    """Convert an external identifier into one path component."""

    safe = _UNSAFE_IDENTIFIER.sub("_", str(value)).strip()
    return safe or "_"


def write_snapshot(
    data_dir: str | Path,
    source: str,
    source_record_id: str,
    content: bytes | str,
    *,
    request_url: str = "",
    adapter_version: str = "0.1.0",
    retrieved_at: datetime | None = None,
) -> Snapshot:
    """Write original response bytes under ``raw/<safe source>``.

    Text responses are encoded as UTF-8 before hashing and writing. Source and
    record identifiers are reduced to safe single path components so neither
    can escape the configured data directory.
    """

    raw_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    source_component = _safe_identifier(source)
    record_component = _safe_identifier(source_record_id)
    path = Path(data_dir) / "raw" / source_component / f"{record_component}.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw_bytes)

    return Snapshot(
        path=path,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
        request_url=request_url,
        adapter_version=adapter_version,
    )
