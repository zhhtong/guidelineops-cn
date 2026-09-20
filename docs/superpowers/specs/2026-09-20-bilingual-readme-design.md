# GuidelineOps-CN Bilingual README Design

## Goal

Make the repository immediately understandable to both Chinese-speaking clinical-guideline professionals and international metadata, evidence, and healthcare-AI developers without maintaining two fully duplicated long documents.

## Design

- Add a visible `English | 简体中文` navigation line at the top of `README.md` and `README.zh-CN.md`.
- Keep English as the main technical README and Chinese as the focused Chinese-language companion.
- Add a concise Chinese value proposition and scope paragraph to the first screen of the English README.
- Preserve the existing provenance-first positioning, v0.3.0 capability claims, quick start, feedback routes, source/copyright boundary, and research-only disclaimer.
- Improve the Chinese README opening so it mirrors the current English positioning and links back to the English technical reference.
- Avoid paragraph-by-paragraph duplication of the long command and governance reference. The Chinese page will remain a practical overview with links to the canonical technical details.
- Do not invent source access, clinical validation, production readiness, compliance, or AI capability claims.

## Validation

- Confirm both language links resolve to tracked files.
- Run Markdown whitespace checks.
- Run the repository's existing test and lint commands before pushing.
- Confirm the remote CI result after pushing.

## Non-goals

- Translating every command explanation and internal design document.
- Changing metadata collection, knowledge governance, or review behavior.
- Adding claims that the project provides clinical recommendations or bypasses source access controls.
