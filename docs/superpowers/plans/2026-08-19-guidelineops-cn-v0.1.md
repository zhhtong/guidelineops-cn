# GuidelineOps-CN V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested, reproducible CLI that discovers and governs traceable metadata for Chinese clinical guidelines and expert consensuses without accessing protected full text.

**Architecture:** Source-specific adapters write immutable raw snapshots before parsing them into `SourceRecord` objects. Records are persisted in SQLite, grouped into canonical works using conservative deduplication, and exported for human medical review. PubMed and Crossref use documented public APIs; CNKI/Wanfang are offline CSV import only.

**Tech Stack:** Python 3.11+, uv, httpx, Pydantic v2, pydantic-settings, SQLAlchemy 2, SQLite, Typer, tenacity, lxml, BeautifulSoup4, rapidfuzz, pytest, pytest-asyncio, respx, ruff, mypy.

---

## File Structure

- `pyproject.toml` — package metadata, dependencies, tool configuration, CLI entry point.
- `guidelineops/config.py` — validated environment settings and configured paths.
- `guidelineops/models.py` — Pydantic enums and normalized record models.
- `guidelineops/provenance.py` — safe raw snapshot filenames, bytes persistence, SHA-256 evidence.
- `guidelineops/database.py` — SQLAlchemy tables, session factory, idempotent persistence.
- `guidelineops/normalization.py` — DOI and title normalization.
- `guidelineops/dedup.py` — exact match merges and reviewable fuzzy candidates.
- `guidelineops/export.py` — UTF-8 CSV/JSONL exports.
- `guidelineops/sources/base.py` — adapter protocol and observable adapter errors.
- `guidelineops/sources/pubmed.py` — ESearch/EFetch client and XML parser.
- `guidelineops/sources/crossref.py` — Crossref search/DOI lookup JSON parser.
- `guidelineops/sources/cnki_import.py`, `wanfang_import.py` — explicit CSV column mappings and row errors.
- `guidelineops/cli.py` — Typer commands and discovery orchestration.
- `tests/` — offline fixtures and unit tests; integration tests opt in with marker.

### Task 1: Create a minimal installable package and CLI

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`, `README.zh-CN.md`
- Create: `guidelineops/__init__.py`, `guidelineops/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI test**

```python
from typer.testing import CliRunner
from guidelineops.cli import app

def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "GuidelineOps-CN" in result.stdout
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`

Expected: collection fails because package files do not yet exist.

- [ ] **Step 3: Add project configuration and minimal CLI**

```toml
[project]
name = "guidelineops-cn"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["typer>=0.12"]

[project.scripts]
guidelineops = "guidelineops.cli:app"
```

```python
import typer

app = typer.Typer(help="GuidelineOps-CN: traceable guideline metadata governance.")

@app.callback()
def main() -> None:
    """Research and education use only; not for clinical decision making."""
```

- [ ] **Step 4: Run installation, lint, and the test**

Run: `uv sync; uv run ruff check .; uv run pytest tests/test_cli.py -v; uv run guidelineops --help`

Expected: all commands exit 0 and help displays the research-use statement.

- [ ] **Step 5: Commit the scaffold**

Run: `git add pyproject.toml .gitignore .env.example README.md README.zh-CN.md guidelineops tests/test_cli.py && git commit -m "feat: scaffold guidelineops cli"`

### Task 2: Add normalized data models and provenance snapshots

**Files:**
- Create: `guidelineops/config.py`, `guidelineops/models.py`, `guidelineops/normalization.py`, `guidelineops/provenance.py`
- Create: `tests/test_models.py`, `tests/test_normalization.py`, `tests/test_provenance.py`

- [ ] **Step 1: Write failing model, normalization, and snapshot tests**

```python
def test_normalize_doi_removes_url_and_lowercases() -> None:
    assert normalize_doi("https://doi.org/10.1000/ABC.1 ") == "10.1000/abc.1"
def test_snapshot_writes_hash_and_path(tmp_path: Path) -> None:
    snapshot = write_snapshot(tmp_path, "pubmed", "123", b"<xml/>")
    assert snapshot.sha256 == hashlib.sha256(b"<xml/>").hexdigest()
    assert snapshot.path.exists()
```

- [ ] **Step 2: Verify those tests fail**

Run: `uv run pytest tests/test_models.py tests/test_normalization.py tests/test_provenance.py -v`

Expected: import errors for the new modules.

- [ ] **Step 3: Implement the data contract**

Implement `DocumentType`, `AccessStatus`, and `ReviewStatus` string enums; a
`SourceRecord` Pydantic model with all fields named in the approved design; and
`Snapshot` with `path`, `sha256`, `retrieved_at`, and `request_url`. Implement
Unicode NFKC title normalization, whitespace collapse, ASCII casefolding, and
canonical DOI extraction. `write_snapshot` must use only safe identifier
characters in filenames and compute SHA-256 from original bytes.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_models.py tests/test_normalization.py tests/test_provenance.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run: `git add guidelineops tests && git commit -m "feat: add normalized records and provenance"`

### Task 3: Add SQLite persistence and conservative deduplication

**Files:**
- Create: `guidelineops/database.py`, `guidelineops/dedup.py`
- Create: `tests/test_database.py`, `tests/test_dedup.py`

- [ ] **Step 1: Write failing persistence and deduplication tests**

```python
def test_upsert_is_idempotent(session: Session, record: SourceRecord) -> None:
    upsert_source_record(session, record)
    upsert_source_record(session, record)
    assert session.scalar(select(func.count()).select_from(SourceRecordRow)) == 1
def test_four_sources_with_one_doi_form_one_canonical_group() -> None:
    result = group_records(make_same_doi_records(4))
    assert len(result.canonical_groups) == 1
    assert len(result.canonical_groups[0].source_record_ids) == 4
```

- [ ] **Step 2: Verify the tests fail**

Run: `uv run pytest tests/test_database.py tests/test_dedup.py -v`

Expected: import errors.

- [ ] **Step 3: Implement storage and grouping**

Create SQLAlchemy tables `source_records`, `canonical_guidelines`,
`guideline_source_links`, and `ingestion_runs`. Use a uniqueness constraint on
`(source, source_record_id)` and update matching rows rather than appending.
Group exact DOI, PMID, and source identity matches automatically. Emit exact
normalized-title and >=95 RapidFuzz/year-within-one matches as `DuplicateCandidate`
objects only; do not delete them.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_database.py tests/test_dedup.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run: `git add guidelineops tests && git commit -m "feat: persist and deduplicate guideline records"`

### Task 4: Implement the PubMed adapter with mocked HTTP tests

**Files:**
- Create: `guidelineops/sources/__init__.py`, `guidelineops/sources/base.py`, `guidelineops/sources/pubmed.py`
- Create: `tests/fixtures/pubmed_search.json`, `tests/fixtures/pubmed_fetch.xml`, `tests/test_pubmed.py`

- [ ] **Step 1: Write failing adapter tests using respx**

```python
@respx.mock
async def test_pubmed_search_fetch_and_parse(settings: Settings) -> None:
    respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["1"]}})
    )
    respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi").mock(
        return_value=httpx.Response(200, text=fixture_xml)
    )
    records = await PubMedAdapter(settings).search_and_fetch("COPD guideline", 10)
    assert records[0].pmid == "1"
    assert records[0].doi == "10.1000/example"
```

- [ ] **Step 2: Verify the test fails**

Run: `uv run pytest tests/test_pubmed.py -v`

Expected: import errors.

- [ ] **Step 3: Implement the adapter**

Require `NCBI_EMAIL` in `Settings` before issuing calls. Send `tool`, `email`,
and optional `api_key`; enforce 3 requests/second without a key and 10 with one.
Use `httpx.AsyncClient`, a 30-second timeout, tenacity retries for transport and
5xx errors, and persist each EFetch XML snapshot before parsing. Extract PMID,
title, abstract, authors, journal, date/year, publication types, DOI, and the
PubMed URL.

- [ ] **Step 4: Run offline tests and a configured real command**

Run: `uv run pytest tests/test_pubmed.py -v`

Run when `NCBI_EMAIL` is configured: `uv run guidelineops pubmed-search "COPD guideline" --limit 10 --since 2015`

Expected: offline tests pass; the real command either persists records or exits
with the explicit missing-email/network error.

- [ ] **Step 5: Commit**

Run: `git add guidelineops tests && git commit -m "feat: add pubmed source adapter"`

### Task 5: Implement Crossref search and enrichment

**Files:**
- Create: `guidelineops/sources/crossref.py`, `tests/fixtures/crossref_works.json`, `tests/test_crossref.py`
- Modify: `guidelineops/cli.py`

- [ ] **Step 1: Write failing mocked Crossref tests**

```python
@respx.mock
async def test_crossref_parses_work() -> None:
    respx.get("https://api.crossref.org/works").mock(
        return_value=httpx.Response(200, json=fixture_json)
    )
    records = await CrossrefAdapter(settings).search("COPD guideline", 1)
    assert records[0].doi == "10.1000/example"
    assert records[0].journal == "Example Journal"
```

- [ ] **Step 2: Verify the test fails**

Run: `uv run pytest tests/test_crossref.py -v`

Expected: import errors.

- [ ] **Step 3: Implement Crossref adapter and enrich command**

Use `https://api.crossref.org/works` only, including configured `mailto` in the
User-Agent/parameters. Snapshot returned JSON before normalization. The enrich
path must fill absent DOI, publisher, ISSN, journal, publication date, URL, and
license metadata, without replacing non-empty PubMed values.

- [ ] **Step 4: Run focused tests and CLI help**

Run: `uv run pytest tests/test_crossref.py -v; uv run guidelineops crossref-search --help; uv run guidelineops crossref-enrich --help`

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

Run: `git add guidelineops tests && git commit -m "feat: add crossref search and enrichment"`

### Task 6: Import CNKI and Wanfang CSV exports safely

**Files:**
- Create: `guidelineops/sources/cnki_import.py`, `guidelineops/sources/wanfang_import.py`, `guidelineops/sources/wanfang.py`
- Create: `tests/fixtures/cnki_sample.csv`, `tests/fixtures/wanfang_sample.csv`, `tests/test_import.py`
- Modify: `guidelineops/cli.py`

- [ ] **Step 1: Write failing import tests**

```python
def test_cnki_import_keeps_good_rows_and_reports_bad_rows(tmp_path: Path) -> None:
    result = import_cnki_csv(fixture_path, tmp_path)
    assert result.imported_count == 2
    assert result.error_count == 1
    assert (tmp_path / "import_errors.csv").exists()
```

- [ ] **Step 2: Verify the test fails**

Run: `uv run pytest tests/test_import.py -v`

Expected: import errors.

- [ ] **Step 3: Implement explicit mappings and optional Wanfang shell**

Accept documented alternate column labels for title, authors, journal, year,
DOI, abstract, and record URL. Preserve invalid rows with a specific reason in
`data/import_errors.csv`; do not abort the entire import. The Wanfang API class
must only raise a clear “credentials/API documentation not configured” warning;
it must not define an endpoint or authentication scheme.

- [ ] **Step 4: Run focused tests and an import command**

Run: `uv run pytest tests/test_import.py -v; uv run guidelineops import-file --source cnki --file tests/fixtures/cnki_sample.csv`

Expected: tests pass and command reports exact imported/error counts.

- [ ] **Step 5: Commit**

Run: `git add guidelineops tests && git commit -m "feat: import cnki and wanfang csv metadata"`

### Task 7: Add exports, unified discovery, documentation, and final verification

**Files:**
- Create: `guidelineops/export.py`, `tests/test_export.py`, `tests/test_discover.py`
- Modify: `guidelineops/cli.py`, `README.md`, `README.zh-CN.md`, `.env.example`, `.gitignore`, `pyproject.toml`

- [ ] **Step 1: Write failing export/discovery tests**

```python
def test_export_jsonl_is_utf8_and_contains_record(tmp_path: Path) -> None:
    path = export_records(records_with_chinese_title(), tmp_path, "jsonl")
    assert "指南" in path.read_text(encoding="utf-8")


def test_discover_reports_actual_counts(mocked_services: None) -> None:
    result = CliRunner().invoke(app, ["discover", "--disease", "COPD", "--limit", "2"])
    assert result.exit_code == 0
    assert "PubMed records: 2" in result.stdout
```

- [ ] **Step 2: Verify the tests fail**

Run: `uv run pytest tests/test_export.py tests/test_discover.py -v`

Expected: import or assertion failures.

- [ ] **Step 3: Implement export and discovery orchestration**

Export candidates to `data/guideline_candidates.csv` and `.jsonl` with UTF-8
encoding. `discover` queries PubMed, persists records/snapshots, enriches
eligible records with Crossref, performs grouping, exports files, and reports
calculated—not hard-coded—counts for PubMed, enrichment, imports, source
records, canonical records, duplicate groups, and output paths.

- [ ] **Step 4: Add final documentation and safety controls**

Document installation, required NCBI configuration, exact commands, source and
copyright boundaries, CSV import, output schema, a Mermaid architecture figure,
and roadmap. Include `.env`, `.private/`, `data/fulltext/`, `*.caj`, and
`licensed_content/` in `.gitignore`. Include no credentials in fixtures or docs.

- [ ] **Step 5: Run release verification and inspect outputs**

Run: `uv sync; uv run ruff check .; uv run mypy guidelineops; uv run pytest; uv run guidelineops --help`

Run when the network and NCBI email are available: `uv run guidelineops discover --disease "chronic obstructive pulmonary disease" --since 2015 --limit 20`

Expected: all offline checks exit 0. Inspect `data/guidelineops.db`,
`data/guideline_candidates.csv`, and `data/guideline_candidates.jsonl`; report
whether the live run succeeded or failed due to network/configuration.

- [ ] **Step 6: Commit**

Run: `git add . && git commit -m "feat: complete guideline discovery v0.1"`

## Plan Self-Review

- Spec coverage: all V0.1 sources, provenance, normalized model, SQLite,
  deduplication, exports, commands, offline tests, safety restrictions, docs,
  and verification are assigned in Tasks 1–7.
- Scope: no task introduces browser automation, full-text processing, CNKI/Wanfang
  API guessing, LLMs, RAG, a vector database, frontend, or CDSS.
- Interface consistency: all adapters normalize into `SourceRecord`; all data is
  snapshot before parsing; exact merges and review-only fuzzy candidates use the
  same policy in storage and discovery.
