# Quality Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic `quality-report` command that turns persisted guideline metadata into human- and machine-readable quality evidence.

**Architecture:** A new pure `guidelineops.quality` module will construct a typed report from validated `SourceRecord` values and a persisted canonical-group count. The CLI will be the only database-facing layer: it queries rows, validates stored JSON into records, calls the report module, and atomically writes JSON and Markdown into `DATA_DIR`.

**Tech Stack:** Python 3.11, Pydantic v2 records, SQLAlchemy 2, Typer, pytest, Ruff.

---

### Task 1: Build the pure quality-report domain model

**Files:**

- Create: `guidelineops/quality.py`
- Test: `tests/test_quality.py`

- [ ] **Step 1: Write the failing zero-record and mixed-record tests**

```python
from guidelineops.models import ReviewStatus, SourceRecord
from guidelineops.quality import build_quality_report


def test_build_quality_report_returns_zero_safe_empty_report() -> None:
    report = build_quality_report([], canonical_records=0)

    assert report.total_records == 0
    assert report.canonical_records == 0
    assert report.source_counts == {}
    assert report.field_completeness["doi"].rate == 0.0
    assert report.risk_items == []
    assert report.duplicate_candidates == []


def test_build_quality_report_counts_fields_statuses_and_risks() -> None:
    records = [
        SourceRecord(
            source="pubmed", source_record_id="1", title="COPD guideline",
            doi="10.1000/example", pmid="1", publication_year=2024,
            source_url="https://pubmed.ncbi.nlm.nih.gov/1/", authors=["Li"],
            review_status=ReviewStatus.verified,
        ),
        SourceRecord(
            source="cnki", source_record_id="2", title="COPD guideline",
            review_status=ReviewStatus.needs_review,
        ),
    ]

    report = build_quality_report(records, canonical_records=2)

    assert report.source_counts == {"cnki": 1, "pubmed": 1}
    assert report.review_status_counts == {"needs_review": 1, "verified": 1}
    assert report.field_completeness["doi"].present == 1
    assert report.field_completeness["doi"].missing == 1
    assert {item.reason for item in report.risk_items} == {
        "missing_publication_year", "missing_source_url", "missing_identifiers",
    }
    assert report.duplicate_candidates[0].kind == "exact_title"
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `uv run pytest tests/test_quality.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'guidelineops.quality'`.

- [ ] **Step 3: Implement the minimal pure report API**

```python
@dataclass(frozen=True)
class Completeness:
    present: int
    missing: int
    rate: float


@dataclass(frozen=True)
class RiskItem:
    source: str
    source_record_id: str
    title: str
    reason: str


@dataclass(frozen=True)
class QualityReport:
    generated_at: datetime
    total_records: int
    canonical_records: int
    source_counts: dict[str, int]
    review_status_counts: dict[str, int]
    field_completeness: dict[str, Completeness]
    risk_items: list[RiskItem]
    duplicate_candidates: list[DuplicateCandidate]


def build_quality_report(
    records: list[SourceRecord], *, canonical_records: int
) -> QualityReport:
    """Calculate deterministic data-quality signals without modifying records."""
```

Count sources and review statuses in sorted-key order. For the five required
completeness fields, calculate `(present, missing, present / total)` and return
`0.0` when `total` is zero. Add each applicable risk reason in the order
`missing_publication_year`, `missing_source_url`, `missing_identifiers`.
Use `group_records(records).candidates` unchanged for duplicate suggestions.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `uv run pytest tests/test_quality.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the domain layer**

```bash
git add guidelineops/quality.py tests/test_quality.py
git commit -m "feat: add quality report domain model"
```

### Task 2: Add UTF-8 JSON and Markdown renderers

**Files:**

- Modify: `guidelineops/quality.py`
- Modify: `tests/test_quality.py`

- [ ] **Step 1: Write failing serialization tests**

```python
import json

from guidelineops.quality import build_quality_report, render_markdown, report_json


def test_quality_report_json_is_machine_readable_and_markdown_explains_empty_sections() -> None:
    report = build_quality_report([], canonical_records=0)

    payload = json.loads(report_json(report))
    markdown = render_markdown(report)

    assert payload["total_records"] == 0
    assert payload["field_completeness"]["doi"]["rate"] == 0.0
    assert "No risk items found." in markdown
    assert "No duplicate candidates found." in markdown
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `uv run pytest tests/test_quality.py::test_quality_report_json_is_machine_readable_and_markdown_explains_empty_sections -q`

Expected: FAIL because `render_markdown` and `report_json` do not exist.

- [ ] **Step 3: Implement deterministic renderers**

```python
def report_json(report: QualityReport) -> str:
    return json.dumps(_report_mapping(report), ensure_ascii=False, indent=2) + "\n"


def render_markdown(report: QualityReport) -> str:
    """Render counts, tables, and explicit empty review sections in Markdown."""
```

Serialize dataclasses into the contract specified in
`docs/superpowers/specs/2026-08-20-quality-report-design.md`. Use ISO-8601 UTC
for `generated_at`, a header plus source/status/completeness tables, and
numbered risk and duplicate lists. Include the literal empty-section text used
by the test.

- [ ] **Step 4: Run all quality tests to verify they pass**

Run: `uv run pytest tests/test_quality.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the renderers**

```bash
git add guidelineops/quality.py tests/test_quality.py
git commit -m "feat: render quality report artifacts"
```

### Task 3: Wire report generation into the CLI

**Files:**

- Modify: `guidelineops/cli.py`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Create: `tests/test_cli_quality.py`

- [ ] **Step 1: Write the failing CLI integration test**

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from guidelineops.cli import app


def test_quality_report_writes_json_and_markdown_from_sqlite(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'quality.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "reports"))

    result = CliRunner().invoke(app, ["quality-report"])

    assert result.exit_code == 0
    assert "Records: 0" in result.output
    payload = json.loads((tmp_path / "reports" / "quality_report.json").read_text())
    assert payload["canonical_records"] == 0
    assert (tmp_path / "reports" / "quality_report.md").exists()
```

- [ ] **Step 2: Run the focused CLI test to verify it fails**

Run: `uv run pytest tests/test_cli_quality.py -q`

Expected: FAIL because `quality-report` is not registered.

- [ ] **Step 3: Implement the command and file writing**

```python
@app.command("quality-report")
def quality_report() -> None:
    """Export a provenance-preserving metadata quality report."""
    settings = Settings()
    engine = _database_engine(settings)
    with Session(engine) as session:
        rows = list(session.scalars(select(SourceRecordRow)))
        canonical_count = session.scalar(
            select(func.count()).select_from(CanonicalGuidelineRow)
        ) or 0
    records = [SourceRecord.model_validate(row.record_data) for row in rows]
    report = build_quality_report(records, canonical_records=canonical_count)
    output_dir = Path(settings.data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "quality_report.json"
    markdown_path = output_dir / "quality_report.md"
    json_path.write_text(report_json(report), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    typer.echo(f"Records: {report.total_records}")
    typer.echo(f"JSON: {json_path}")
    typer.echo(f"Markdown: {markdown_path}")
```

Ignore `data/quality_report.json` and `data/quality_report.md`. Add the command
to both README command lists and state that it is metadata quality assurance,
not a clinical recommendation or an automated approval workflow.

- [ ] **Step 4: Run the focused CLI test to verify it passes**

Run: `uv run pytest tests/test_cli_quality.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the CLI and documentation**

```bash
git add guidelineops/cli.py .gitignore README.md README.zh-CN.md tests/test_cli_quality.py
git commit -m "feat: add quality report command"
```

### Task 4: Run complete verification and synchronize X2

**Files:**

- Verify only: repository files changed in Tasks 1-3

- [ ] **Step 1: Run the complete local verification suite**

Run:

```bash
uv lock --check
uv run ruff check .
uv run pytest -q
uv run guidelineops quality-report --help
git diff --check
```

Expected: all commands exit with status 0.

- [ ] **Step 2: Create a Git bundle and synchronize it to X2**

Run:

```bash
git bundle create work/guidelineops-cn-latest.bundle --all
scp work/guidelineops-cn-latest.bundle sxy-x2:/data/y012/projects/
ssh sxy-x2 "cd /data/y012/projects/guidelineops-cn && git stash push --include-untracked -m pre-sync-quality-report >/dev/null || true && git fetch /data/y012/projects/guidelineops-cn-latest.bundle feature/v0.1-foundation && git switch feature/v0.1-foundation && git reset --hard FETCH_HEAD"
```

- [ ] **Step 3: Run X2 static checks and inspect status**

Run:

```bash
ssh sxy-x2 "cd /data/y012/projects/guidelineops-cn && python3 -m compileall -q guidelineops tests && git status --short --branch && git log -1 --oneline"
```

Expected: compilation succeeds and X2 HEAD equals the final local commit. Full
pytest is not expected on X2 until a Python 3.11 project environment is made
available.
