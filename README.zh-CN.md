# GuidelineOps-CN

GuidelineOps-CN 是一个以来源和审计为核心的中文临床指南、专家共识及规范性文件元数据流水线。项目面向研究和教学，不用于诊断、治疗、处方或临床决策支持。

## 当前能力

- PubMed E-utilities：检索、抓取、XML 解析、限速、重试和原始响应快照。
- Crossref REST API：标题检索、DOI 查询以及出版和许可元数据补全。
- CNKI、万方：仅导入用户依法导出的 CSV 元数据，不绕过登录、验证码或付费墙。
- Pydantic 数据契约、SQLite 持久化、保守的 DOI/PMID 去重和仅供人工复核的标题候选。
- UTF-8 CSV/JSONL 导出、PubMed 优先的 `discover` 命令、确定性的质量报告和可审计审核队列。
- 中西医知识单元、原文定位、证据等级、映射关系、撤回记录和 SHA-256 版本冻结。
- 用药安全规则：禁忌证、相互作用、特殊人群、器官功能受损、监测和停药等主题；拒绝剂量及患者个体化处方指令。

## 安装与运行

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync
uv run pytest
uv run guidelineops --help
```

常用命令：

```bash
NCBI_EMAIL=researcher@example.org uv run guidelineops pubmed-search "COPD guideline" --limit 10 --since 2015
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

`discover` 会写入候选 CSV、JSONL 和 SQLite 数据库；原始 API 响应保存到 `data/raw/`，并记录 SHA-256。`quality-report` 只输出元数据质量信号，不做临床判断，也不会自动批准或驳回记录。

## 医学知识治理边界

`knowledge-submit` 会把知识单元置为 `pending`，`review-sync` 随后创建医学审核任务。高风险知识采用双人复核：`medical_reviewer` 初审通过后，由不同的 `medical_lead` 进行终审，只有终审通过才会变为 `approved`。若终审出现分歧，知识单元保持 `pending`，系统创建 `knowledge_escalation` 任务交给 `medical_chair`，并保留驳回原因、审核人和审计事件；这不是把最后一次操作解释成临床真理。

用药安全规则必须引用已有来源知识单元，且同样经过独立初审和终审。终审分歧会创建 `medication_safety_escalation` 任务，规则保持 `pending`。项目不输出剂量、个体化处方、诊断结论或医保报销判断。

审核角色名单可通过 `REVIEWER_REGISTRY_PATH` 指向本地 JSON 白名单（可从 [`reviewers.example.json`](reviewers.example.json) 开始）。角色只是工作流路由，不等同于执业资格、机构认证或身份核验。不要在配置中保存密码、证件号或不必要的个人信息。

## 数据来源和版权

项目保存元数据和链接，不保存 CNKI/万方付费全文；不会绕过认证、验证码或未公开接口。重新分发前请逐一核对来源许可和网站条款。所有输出都是需要人工医学复核的候选数据。

上线前请阅读 [`docs/release-readiness.md`](docs/release-readiness.md)、[`docs/medical-governance-review.md`](docs/medical-governance-review.md) 和 [`docs/ai-readiness-roadmap.md`](docs/ai-readiness-roadmap.md)。本项目是研究/教学工具，不是医疗器械，不得用于真实世界临床决策。

简历项目介绍和面试表达建议见 [`docs/resume-project-profile.md`](docs/resume-project-profile.md)。

## 本地验证

```bash
uv run ruff check .
uv run pytest
uv lock --check
```
