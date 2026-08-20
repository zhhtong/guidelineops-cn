# GuidelineOps-CN

项目版本：`0.3.0`。

GuidelineOps-CN 是一个以来源追溯为核心的临床指南、专家共识和规范性文献
元数据发现与治理工具，面向研究和教育用途。它不是医疗器械，不提供诊断、
治疗或处方建议，不得用于真实临床决策。

## V0.3 已实现

- PubMed 官方 E-utilities：ESearch、EFetch、XML 解析、限流、重试和原始快照；
- Crossref REST API：题名检索、DOI 查询、出版与许可元数据补全；
- CNKI/万方：只导入用户自行导出的 CSV 元数据，不自动登录、不绕过验证码、不下载付费全文；
- Pydantic 数据模型、SQLite 持久化、DOI/PMID 保守去重和人工复核候选；
- UTF-8 CSV/JSONL 导出及 PubMed 优先的 `discover` 管线。
- 可复现的元数据质量报告，以及带审计记录的人工审核队列。

## 安装与运行

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync
uv run pytest
uv run guidelineops --help
```

PubMed 按 NCBI 要求配置联系邮箱：

```bash
NCBI_EMAIL=researcher@example.org uv run guidelineops pubmed-search "COPD guideline" --limit 10 --since 2015
```

常用命令：

```bash
uv run guidelineops crossref-search "COPD guideline" --limit 10
uv run guidelineops crossref-enrich 10.1000/example
uv run guidelineops import-file --source cnki exports/cnki.csv
uv run guidelineops import-file --source wanfang exports/wanfang.csv
uv run guidelineops discover --disease "COPD guideline" --since 2015 --limit 20
uv run guidelineops quality-report
uv run guidelineops review-sync
uv run guidelineops review-list --status open
uv run guidelineops review-claim 12 --reviewer "李医生"
uv run guidelineops review-reject 12 --reviewer "李医生" --reason "非正式指南"
```

`discover` 会生成 `data/guideline_candidates.csv`、
`data/guideline_candidates.jsonl` 和 SQLite 数据库；API 原始响应保存在
`data/raw/`，带有 SHA-256 证据链并被 Git 忽略。

`quality-report` 会读取配置的 SQLite 数据库，并在 `data/quality_report.json`
和 `data/quality_report.md`（或配置的 `DATA_DIR`）中生成元数据质量信号。该
报告仅用于研究和教育，不提供临床推荐，也不会自动审批或拒绝任何记录。

`review-sync` 会将质量风险和不自动合并的重复候选同步为 SQLite 审核任务；每次
领取或作出结论都会保留不可覆盖的审计事件。审核队列不会修改原始来源元数据、
自动合并记录或产生临床决策。

## 数据与版权边界

项目只保存元数据、来源链接和治理信息，不保存 CNKI/万方付费全文；不会绕过
登录或验证码，也不会臆造未公开的 API。发布或再利用任何来源前必须核对其
许可和网站条款。所有候选记录都需要医学人员复核。

## 开发检查

```bash
uv run ruff check .
uv run pytest
```
