# Medical Review Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable, deterministic CLI review queue for metadata risks and duplicate candidates.

**Architecture:** SQLAlchemy rows retain current task state and append-only events. `review_queue.py` turns validated source records into stable signals and owns state-transition rules; `cli.py` only opens sessions, calls services, commits, and prints JSON Lines.

**Tech Stack:** Python 3.11, SQLAlchemy 2, Pydantic v2, Typer, pytest, Ruff.

---

### Task 1: Persist review tasks and append-only events

**Files:**

- Modify: `guidelineops/database.py`
- Modify: `tests/test_database.py`

- [ ] **Step 1: Write failing persistence tests**

```python
from sqlalchemy import select

from guidelineops.database import ReviewEventRow, ReviewTaskRow


def test_review_task_fingerprint_is_unique(session: Session) -> None:
    session.add_all(
        [
            ReviewTaskRow(
                fingerprint="risk:pubmed:1:missing_source_url",
                task_type="metadata_risk", status="open", payload={},
            ),
            ReviewTaskRow(
                fingerprint="risk:pubmed:1:missing_source_url",
                task_type="metadata_risk", status="open", payload={},
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_review_event_links_to_task(session: Session) -> None:
    task = ReviewTaskRow(
        fingerprint="risk:pubmed:1:missing_source_url",
        task_type="metadata_risk", status="open", payload={},
    )
    session.add(task)
    session.flush()
    session.add(ReviewEventRow(task=task, event_type="synced", actor="system"))
    session.commit()

    assert session.scalar(select(ReviewEventRow)).task_id == task.id
```

- [ ] **Step 2: Verify the test fails**

Run: `uv run pytest tests/test_database.py -q`

Expected: FAIL because `ReviewTaskRow` and `ReviewEventRow` do not exist.

- [ ] **Step 3: Add minimal SQLAlchemy mappings**

Add these models below `IngestionRunRow`:

```python
class ReviewTaskRow(Base):
    __tablename__ = "review_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(255))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    events: Mapped[list[ReviewEventRow]] = relationship(back_populates="task")


class ReviewEventRow(Base):
    __tablename__ = "review_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    task: Mapped[ReviewTaskRow] = relationship(back_populates="events")
```

Use a forward reference exactly as existing source/link mappings do. Do not add
database migration tooling; `Base.metadata.create_all` is the current project
initialization contract.

- [ ] **Step 4: Verify persistence tests pass**

Run: `uv run pytest tests/test_database.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add guidelineops/database.py tests/test_database.py
git commit -m "feat: persist review tasks and audit events"
```

### Task 2: Build deterministic synchronization and transition services

**Files:**

- Create: `guidelineops/review_queue.py`
- Create: `tests/test_review_queue.py`

- [ ] **Step 1: Write failing service tests**

```python
def test_sync_creates_one_task_per_risk_and_duplicate(session: Session) -> None:
    records = [
        SourceRecord(source="pubmed", source_record_id="1", title="COPD guideline"),
        SourceRecord(source="cnki", source_record_id="2", title="COPD guideline"),
    ]

    result = sync_review_tasks(session, records)
    session.commit()

    assert result.created == 7
    assert session.scalar(select(func.count()).select_from(ReviewTaskRow)) == 7
    assert session.scalar(select(func.count()).select_from(ReviewEventRow)) == 7


def test_sync_is_idempotent_and_supersedes_disappeared_active_signal(session: Session) -> None:
    record = SourceRecord(source="pubmed", source_record_id="1", title="COPD")
    sync_review_tasks(session, [record])
    session.commit()
    assert sync_review_tasks(session, [record]).created == 0
    assert sync_review_tasks(session, []).superseded == 3


def test_claim_and_reject_require_owner_and_reason(session: Session) -> None:
    task = create_open_task(session)
    claim_task(session, task.id, reviewer="李医生")
    with pytest.raises(ReviewQueueError):
        decide_task(session, task.id, reviewer="王医生", decision="rejected", reason="不适用")
    with pytest.raises(ReviewQueueError):
        decide_task(session, task.id, reviewer="李医生", decision="rejected", reason=" ")
    decide_task(session, task.id, reviewer="李医生", decision="rejected", reason="非正式指南")
    assert task.status == "rejected"
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/test_review_queue.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'guidelineops.review_queue'`.

- [ ] **Step 3: Implement signals, sync, and transitions**

Define the public API:

```python
class ReviewQueueError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewSignal:
    fingerprint: str
    task_type: str
    payload: dict[str, object]


@dataclass(frozen=True)
class SyncResult:
    created: int
    refreshed: int
    superseded: int


def review_signals(records: list[SourceRecord]) -> list[ReviewSignal]: ...
def sync_review_tasks(session: Session, records: list[SourceRecord]) -> SyncResult: ...
def list_review_tasks(session: Session, *, status: str | None = None) -> list[ReviewTaskRow]: ...
def claim_task(session: Session, task_id: int, *, reviewer: str) -> ReviewTaskRow: ...
def decide_task(session: Session, task_id: int, *, reviewer: str, decision: str, reason: str | None = None) -> ReviewTaskRow: ...
def task_mapping(task: ReviewTaskRow) -> dict[str, object]: ...
```

Build risks from `build_quality_report(records, canonical_records=0).risk_items`.
Risk payload keys are `source`, `source_record_id`, `title`, and `reason`.
For duplicate candidates sort its two source identities, then include
`left_source_record_id`, `right_source_record_id`, `kind`, `confidence`, and
`score` in the payload.

`sync_review_tasks` reads existing tasks by fingerprint, creates a `synced`
event only for a newly created row, and updates `payload`, `updated_at`, and
`last_seen_at` on existing rows. For missing signals, transition only `open`,
`claimed`, and `deferred` rows to `superseded` and append exactly one
`superseded` event by actor `system`.

Require nonblank reviewer strings. Claim only `open`/`deferred`; clear any
previous resolution timestamp and append `claimed`. Decision only accepts a
claimed task owned by the supplied reviewer. Valid decisions are `approved`,
`rejected`, and `deferred`; reject/defer require nonblank reason. Set
`resolved_at` only for approved/rejected and append an event of the decision
name. All event payloads may be `{}`.

- [ ] **Step 4: Verify service tests pass**

Run: `uv run pytest tests/test_review_queue.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add guidelineops/review_queue.py tests/test_review_queue.py
git commit -m "feat: add review queue workflow services"
```

### Task 3: Expose the queue through CLI commands

**Files:**

- Modify: `guidelineops/cli.py`
- Create: `tests/test_cli_review.py`

- [ ] **Step 1: Write failing CLI flow test**

```python
def test_review_cli_sync_claim_and_reject(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'review.db'}")
    seed_source_record(tmp_path)

    assert CliRunner().invoke(app, ["review-sync"]).exit_code == 0
    listed = CliRunner().invoke(app, ["review-list", "--status", "open"])
    task_id = json.loads(listed.output.splitlines()[0])["id"]
    assert CliRunner().invoke(app, ["review-claim", str(task_id), "--reviewer", "李医生"]).exit_code == 0
    result = CliRunner().invoke(app, ["review-reject", str(task_id), "--reviewer", "李医生", "--reason", "非正式指南"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/test_cli_review.py -q`

Expected: FAIL because `review-sync` is not registered.

- [ ] **Step 3: Register five commands**

Add imports for `ReviewQueueError`, `claim_task`, `decide_task`,
`list_review_tasks`, `sync_review_tasks`, and `task_mapping`. Implement:

```python
@app.command("review-sync")
def review_sync() -> None: ...

@app.command("review-list")
def review_list(status: str | None = typer.Option(None)) -> None: ...

@app.command("review-claim")
def review_claim(task_id: int, reviewer: str = typer.Option(...)) -> None: ...

@app.command("review-approve")
def review_approve(task_id: int, reviewer: str = typer.Option(...), note: str | None = typer.Option(None)) -> None: ...

@app.command("review-reject")
def review_reject(task_id: int, reviewer: str = typer.Option(...), reason: str = typer.Option(...)) -> None: ...

@app.command("review-defer")
def review_defer(task_id: int, reviewer: str = typer.Option(...), reason: str = typer.Option(...)) -> None: ...
```

All commands call `_database_engine(Settings())`. `review-sync` validates
`SourceRecordRow.record_data` in `id` order, commits, then prints
`Created:`, `Refreshed:`, and `Superseded:`. `review-list` emits one
`json.dumps(task_mapping(task), ensure_ascii=False)` line per task in ID order.
Mutation commands roll back on `ReviewQueueError`, echo its message to stderr,
and exit code 2; otherwise commit and print one JSON task mapping.

- [ ] **Step 4: Verify CLI tests pass**

Run: `uv run pytest tests/test_cli_review.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add guidelineops/cli.py tests/test_cli_review.py
git commit -m "feat: add review queue CLI commands"
```

### Task 4: Correct presentation defects and verify release

**Files:**

- Modify: `guidelineops/quality.py`
- Modify: `tests/test_quality.py`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 1: Write failing regression tests for Markdown Unicode**

```python
def test_render_markdown_uses_readable_unicode_separators() -> None:
    report = build_quality_report(
        [SourceRecord(source="cnki", source_record_id="1", title="中文指南")],
        canonical_records=1,
    )
    markdown = render_markdown(report)
    assert "鈥" not in markdown
    assert "中文指南" in markdown
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/test_quality.py::test_render_markdown_uses_readable_unicode_separators -q`

Expected: FAIL because the existing renderer contains mojibake.

- [ ] **Step 3: Fix presentation and documentation**

Replace mojibake separators in `render_markdown` with ASCII ` - ` and ` -> `
so output is portable. Add `work/` to `.gitignore`. Update both README files to
call the project v0.2, document the six review commands, and state that the
queue records human governance decisions without automatically approving,
rejecting, merging, or clinically validating source records.

- [ ] **Step 4: Run complete verification**

Run:

```bash
uv lock --check
uv run ruff check .
uv run pytest -q
uv run guidelineops review-sync --help
uv run guidelineops review-list --help
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit and synchronize X2**

```bash
git add guidelineops/quality.py tests/test_quality.py .gitignore README.md README.zh-CN.md
git commit -m "chore: polish review queue documentation"
git bundle create work/guidelineops-cn-latest.bundle --all
scp work/guidelineops-cn-latest.bundle sxy-x2:/data/y012/projects/
ssh sxy-x2 "cd /data/y012/projects/guidelineops-cn && git stash push --include-untracked -m pre-sync-review-queue >/dev/null || true && git fetch /data/y012/projects/guidelineops-cn-latest.bundle feature/v0.1-foundation && git switch feature/v0.1-foundation && git reset --hard FETCH_HEAD && python3 -m compileall -q guidelineops tests"
```

Expected: local checks pass; X2 source code compiles and points to the latest
commit. Do not run the full suite on X2 until a Python 3.11 environment exists.
