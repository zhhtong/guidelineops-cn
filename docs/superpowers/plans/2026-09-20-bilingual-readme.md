# GuidelineOps-CN Bilingual README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clear bilingual landing experience to GuidelineOps-CN while preserving its English technical reference and focused Chinese companion.

**Architecture:** Update only the two README files. Keep English canonical for detailed commands and governance behavior; keep Chinese focused on positioning, capabilities, onboarding, feedback, and safety.

**Tech Stack:** GitHub Markdown, Python 3.11+, uv, pytest, Ruff.

---

### Task 1: Add the bilingual landing content

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] Add `[English](README.md) | [简体中文](README.zh-CN.md)` below both titles.
- [ ] Add a concise Chinese value proposition and scope paragraph near the top of `README.md`.
- [ ] Align the Chinese opening with v0.3.0 capabilities and add a clear link to the English technical reference.
- [ ] Preserve all source-access, copyright, medical-review, and research-only boundaries.
- [ ] Run `git diff --check` and confirm both relative language links target tracked files.
- [ ] Commit with `docs: add bilingual project introduction`.

### Task 2: Verify and publish

**Files:**
- Test: repository test suite

- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run pytest`.
- [ ] Run `uv lock --check`.
- [ ] Review changed filenames for sensitive data or unrelated files.
- [ ] Merge to `main`, rerun verification, and push to `origin/main`.
- [ ] Confirm the remote commit and GitHub Actions result.
