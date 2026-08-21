# GuidelineOps-CN

项目版本：`0.3.0`

GuidelineOps-CN 是一个面向研究与教育用途的临床指南、专家共识和规范元数据治理工具。它负责来源追踪、结构化导入、质量评估和人工审核队列，不提供临床建议，也不会自动批准或拒绝任何医学记录。

## V0.3 功能

- PubMed 官方 E-utilities（ESearch、EFetch、XML 解析），支持重试、限速和原始响应快照。
- Crossref REST API 搜索与 DOI 补全，用于发现候选文献并补充元数据。
- CNKI/万方仅支持用户导出的 CSV 元数据导入；不绕过验证码、不自动抓取受限内容。
- Pydantic 数据模型、SQLite 持久化，以及 DOI/PMID 去重和人工审核队列。
- UTF-8 CSV/JSONL 导入、PubMed/Crossref 的 `discover` 工作流和质量报告。
- 审核任务、认领、决定和追加式审计事件；审核不会修改原始来源记录。

## 安装与快速开始

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync
uv run pytest
uv run guidelineops --help
```

PubMed/NCBI 要求提供联系邮箱：

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
uv run guidelineops knowledge-validate knowledge.json
uv run guidelineops review-sync
uv run guidelineops review-list --status open
uv run guidelineops review-events 12
uv run guidelineops review-claim 12 --reviewer "张医生" --role data_curator
uv run guidelineops review-reject 12 --reviewer "张医生" --role data_curator --reason "不符合指南范围"
```

`discover` 会生成 `data/guideline_candidates.csv`、`data/guideline_candidates.jsonl` 并写入 SQLite；API 原始响应保存在 `data/raw/`，同时记录 SHA-256 校验值，便于审计和复现。

`quality-report` 从 SQLite 读取数据，生成 `data/quality_report.json` 和 `data/quality_report.md`（可通过 `DATA_DIR` 调整目录），报告元数据完整性、风险信号和重复候选。

`knowledge-validate` 校验来源可追溯的知识单元 JSON（包括原文定位、证据等级、审核状态以及中西医映射字段），不执行临床推理或生成治疗建议。

`review-sync` 会把质量风险和重复候选同步为 SQLite 审核任务。任务会携带风险等级、所需审核角色和是否需要医学审核：缺失年份由 `data_curator` 处理，缺失链接/标识符由 `evidence_curator` 处理，重复候选由 `medical_reviewer` 复核。命令行必须显式声明 `--role`，系统会拒绝与任务所需角色不符的操作，并将角色写入审计事件。该角色声明尚不是执照或机构资质验证。

审核决定保留为追加式审计事件，任务队列不会修改原始来源元数据。`approved` 仅表示完成规定的审核流程，不代表临床有效性或医疗建议。

部署时可设置 `REVIEWER_REGISTRY_PATH` 指向本地 JSON 审核人员白名单（可从 [`reviewers.example.json`](reviewers.example.json) 开始）。配置后，只有白名单中拥有已声明角色的审核人才能执行审核命令。白名单不应保存密码或不必要的个人信息；它仅提供运行层面的授权，并不证明身份、执业资格或专业资质。

## 医学安全与版权边界

本项目仅处理元数据、来源链接和用户提供的结构化信息。CNKI/万方适配器只接受合法导出的文件，不绕过验证码、不抓取未授权内容。使用任何来源前，请先核对许可、版权和网站条款。

所有候选记录和审核任务都必须由具备相应资质的医学人员复核。项目不输出诊断、处方、剂量或治疗建议；不得把审核状态解释为临床结论。详细治理要求见 [`docs/medical-governance-review.md`](docs/medical-governance-review.md)。

## 贡献与安全

- 贡献流程和医学数据边界：[`CONTRIBUTING.md`](CONTRIBUTING.md)
- 漏洞与敏感信息披露：[`SECURITY.md`](SECURITY.md)
- 医学知识治理审查：[`docs/medical-governance-review.md`](docs/medical-governance-review.md)
- 上线前核对清单：[`docs/release-readiness.md`](docs/release-readiness.md)

## 本地验证

```bash
uv run ruff check .
uv run pytest
uv lock --check
```
