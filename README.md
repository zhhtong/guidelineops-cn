# GuidelineOps-CN

[![CI](actions/workflows/ci.yml/badge.svg)](actions/workflows/ci.yml)

GuidelineOps-CN v0.3.0 is a reproducible, provenance-first metadata pipeline for
discovering Chinese clinical guidelines, expert consensuses, and related
normative documents. It is designed for research and education, not for
diagnosis, treatment, prescribing, or clinical decision support.

## What works in v0.3

- PubMed E-utilities: ESearch, EFetch, XML parsing, rate limiting, retries, and raw snapshots.
- Crossref REST API: title search, DOI lookup, publication/license metadata.
- CNKI and Wanfang: offline import of user-exported CSV metadata only.
- Pydantic records, SQLite persistence, conservative DOI/PMID deduplication, and review-only title candidates.
- UTF-8 CSV/JSONL exports and a PubMed-first `discover` command.
- Deterministic metadata quality reports plus an auditable human review queue.

```mermaid
flowchart LR
  A["PubMed / Crossref APIs"] --> B["Raw snapshots"]
  C["CNKI / Wanfang CSV"] --> D["SourceRecord"]
  B --> D
  D --> E["SQLite + provenance"]
  E --> F["Canonical groups / duplicate candidates"]
  F --> G["Quality report"]
  G --> H["Review tasks + audit events"]
```

## Install

Python 3.11+ and [uv](https://docs.astral.sh/uv/) are required:

```bash
uv sync
uv run pytest
uv run guidelineops --help
```

For PubMed, configure a contact email as required by NCBI:

```bash
NCBI_EMAIL=researcher@example.org uv run guidelineops pubmed-search "COPD guideline" --limit 10 --since 2015
```

Other commands:

```bash
uv run guidelineops crossref-search "COPD guideline" --limit 10
uv run guidelineops crossref-enrich 10.1000/example
uv run guidelineops import-file --source cnki exports/cnki.csv
uv run guidelineops import-file --source wanfang exports/wanfang.csv
uv run guidelineops discover --disease "COPD guideline" --since 2015 --limit 20
uv run guidelineops quality-report
uv run guidelineops knowledge-validate knowledge.json
uv run guidelineops knowledge-import knowledge.json
uv run guidelineops knowledge-list
uv run guidelineops knowledge-submit ku-copd-001
uv run guidelineops knowledge-impact ku-copd-001
uv run guidelineops knowledge-retract ku-copd-001 --reviewer "Dr Wang" --role medical_lead --reason "Source withdrawn"
uv run guidelineops knowledge-freeze ku-copd-001 --reviewer "Dr Wang" --role medical_lead
uv run guidelineops medication-safety-import medication-safety.json
uv run guidelineops medication-safety-submit med-safety-001
uv run guidelineops medication-safety-list
uv run guidelineops review-sync
uv run guidelineops review-list --status open
uv run guidelineops review-events 12
uv run guidelineops review-claim 12 --reviewer "Dr Li" --role data_curator
uv run guidelineops review-reject 12 --reviewer "Dr Li" --role data_curator --reason "Not a formal guideline"
```

`discover` writes `data/guideline_candidates.csv`,
`data/guideline_candidates.jsonl`, and a SQLite database. Raw API responses are
stored under `data/raw/` with SHA-256 provenance and are ignored by Git.

`quality-report` reads the configured SQLite database and writes metadata quality
signals to `data/quality_report.json` and `data/quality_report.md` (or the
configured `DATA_DIR`). The report is for research and education only: it does
not provide clinical recommendations and never automatically approves or
rejects records.

`knowledge-validate` validates a JSON object or array of source-grounded knowledge
units, including source location, evidence grade, review status, and TCM/Western
mapping fields. It performs no clinical inference or recommendation.

`knowledge-import` validates and idempotently stores those units in SQLite;
`knowledge-list` prints the persisted units as JSON Lines for review or export;
`knowledge-submit` moves one unit to `pending`, and `review-sync` creates its
medical-review task. High-risk knowledge uses two named reviewers: a
`medical_reviewer` completes primary review, then an independent `medical_lead`
must complete final review before the unit becomes `approved`. A rejection is
reflected on the unit immediately.

`knowledge-impact` finds mapping-dependent units before a safety action.
`knowledge-retract` requires a named `medical_lead`, records an immutable reason,
marks the unit `retracted`, and reports the dependent units needing review.
`knowledge-freeze` requires the same role and creates an immutable, SHA-256
protected snapshot only after the unit has completed final approval.

Medication safety statements are stored separately from general knowledge units.
They must cite an existing source unit and are limited to contraindications,
interactions, special populations, organ impairment, monitoring, or withdrawal.
The project rejects dosage and patient-specific prescribing instructions; submitted
rules follow independent `medical_reviewer` and `medical_lead` review.

`review-sync` turns quality risks and non-destructive duplicate candidates into
idempotent SQLite tasks. Review actions are append-only audit events; they never
alter source metadata, automatically merge records, or make clinical decisions.
Tasks carry a deterministic risk level, required reviewer role, and medical-review
flag. CLI actions must declare `--role`; the queue rejects a role that does not
match the task and records the declared role in the audit trail. A declared role
is workflow routing, not credential or licensure verification.

Deployments can set `REVIEWER_REGISTRY_PATH` to a local JSON allow-list (start
from [`reviewers.example.json`](reviewers.example.json)). When configured, the
CLI permits review actions only when the declared reviewer ID has the declared
role. Keep the registry free of passwords and unnecessary personal information;
it is operational authorization, not identity or professional credential proof.

## Source and copyright boundary

The project stores metadata and links, not paywalled CNKI/Wanfang full text.
It never bypasses authentication or CAPTCHA and never invents undocumented API
endpoints. Check the license and terms of every source before redistribution.
All outputs are candidate records requiring human medical review.

See the [release-readiness checklist](docs/release-readiness.md) before sharing
the system with other users or describing it as production-ready.
The [AI-readiness roadmap](docs/ai-readiness-roadmap.md) explains which
knowledge-governance capabilities are implemented and which model/CDSS claims
are intentionally out of scope.

## Development

```bash
uv run ruff check .
uv run pytest
```

The repository is for research and educational use only. It is not a medical
device and must not be used to make or support real-world clinical decisions.
