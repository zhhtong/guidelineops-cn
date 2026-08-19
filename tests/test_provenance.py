import hashlib
from datetime import datetime, timezone
from pathlib import Path

from guidelineops.provenance import Snapshot, write_snapshot


def test_snapshot_writes_hash_and_path(tmp_path: Path) -> None:
    content = b"<xml/>"

    snapshot = write_snapshot(tmp_path, "pubmed", "123", content)

    assert isinstance(snapshot, Snapshot)
    assert snapshot.sha256 == hashlib.sha256(content).hexdigest()
    assert snapshot.path == tmp_path / "raw" / "pubmed" / "123.bin"
    assert snapshot.path.exists()
    assert snapshot.path.read_bytes() == content
    assert snapshot.request_url == ""
    assert snapshot.adapter_version == "0.1.0"
    assert snapshot.retrieved_at.tzinfo is not None
    assert snapshot.retrieved_at.utcoffset() == timezone.utc.utcoffset(
        snapshot.retrieved_at
    )


def test_write_snapshot_encodes_text_before_hashing(tmp_path: Path) -> None:
    content = "指南"

    snapshot = write_snapshot(tmp_path, "crossref", "abc", content)

    expected = content.encode("utf-8")
    assert snapshot.path.read_bytes() == expected
    assert snapshot.sha256 == hashlib.sha256(expected).hexdigest()


def test_write_snapshot_sanitizes_source_and_record_id(tmp_path: Path) -> None:
    snapshot = write_snapshot(
        tmp_path,
        "../CNKI source",
        "../../record id/with?unsafe",
        b"payload",
        request_url="https://example.test/record",
        adapter_version="2.3.4",
    )

    assert snapshot.path.parent == tmp_path / "raw" / "_CNKI_source"
    assert snapshot.path.name == "_record_id_with_unsafe.bin"
    assert snapshot.path.is_file()
    assert snapshot.request_url == "https://example.test/record"
    assert snapshot.adapter_version == "2.3.4"


def test_snapshot_accepts_explicit_retrieval_timestamp() -> None:
    timestamp = datetime(2026, 8, 19, tzinfo=timezone.utc)

    snapshot = Snapshot(
        path=Path("raw/pubmed/123.bin"),
        sha256="a" * 64,
        retrieved_at=timestamp,
        request_url="",
        adapter_version="0.1.0",
    )

    assert snapshot.retrieved_at == timestamp
