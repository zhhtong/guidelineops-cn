# GuidelineOps-CN

**一个面向中国临床指南、专家共识及相关规范性文献的“来源优先”元数据与知识治理管道。**

> [!IMPORTANT]
> 本项目仅用于研究与教育，不提供诊断、治疗、处方或针对患者个体的临床决策支持。

GuidelineOps-CN v0.3.0 让证据发现和审核过程可重复、可追溯：保存来源快照，规范元数据记录，保守识别重复候选，生成质量信号，并通过人工审核任务、不可变审计事件和受控知识生命周期管理后续处置。

## v0.3.0 当前能力

- PubMed E-utilities 和 Crossref 元数据检索，包含限速、重试和原始响应快照。
- CNKI、万方：仅导入用户依法导出的 CSV 元数据，不绕过登录、验证码或付费墙。
- Pydantic 校验、SQLite 持久化、保守的 DOI/PMID 去重和仅供人工复核的标题候选。
- 确定性的质量报告和按照角色分配、全程可审计的人工审核任务。
- 带有来源依据的知识单元、高风险内容双阶段审核、撤回影响分析和 SHA-256 保护的冻结快照。

## 快速开始

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync
uv run pytest
uv run guidelineops --help
```

## 征集专业反馈

欢迎医学信息学、循证医学、指南制定、信息科学和医疗 AI 领域的专业人士重点评审：

1. 当前遗漏了哪些元数据质量风险或溯源字段？
2. 审核角色、分歧升级路径和知识生命周期是否符合实际工作？
3. 下一步应支持哪些依法可访问的元数据来源或合成示例？

开放性意见请提交至 [GitHub Discussions](https://github.com/zhhtong/guidelineops-cn/discussions)，可复现的软件问题或边界清晰的建议请使用 [Issues](https://github.com/zhhtong/guidelineops-cn/issues/new/choose)。请勿提交付费全文、患者数据、账号凭证或机构保密材料。

**相关项目：** [AmendBench](https://github.com/zhhtong/AmendBench) 探索临床试验方案修订的可追溯、人工负责型影响评估。两个项目方向互补，目前尚未完成系统集成。

## 检索与工作流命令

常用命令：

```bash
NCBI_EMAIL=researcher@example.org uv run guidelineops pubmed-search "COPD guideline" --limit 10 --since 2015
uv run guidelineops crossref-search "COPD guideline" --limit 10
uv run guidelineops crossref-enrich 10.1000/example
uv run guidelineops import-file --source cnki exports/cnki.csv
uv run guidelineops import-file --source wanfang exports/wanfang.csv
uv run guidelineops discover --disease "COPD guideline" --since 2015 --limit 20
uv run guidelineops quality-report
uv run guidelineops database-status
uv run guidelineops database-backup backups/
DATABASE_URL="sqlite:///./data/recovery-copy.db" uv run guidelineops database-restore backups/guidelineops-backup-YYYYMMDDTHHMMSSZ.db
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

`database-status` 显示当前 SQLite schema 版本。`database-backup` 使用 SQLite 在线备份 API 创建数据库副本，并生成含 SHA-256、文件大小和 schema 版本的 JSON 清单。恢复时建议先写入新的 `DATABASE_URL`；若要替换已有数据库，必须显式使用 `database-restore --force`。备份文件可能含有操作元数据和审核记录，应放在仓库外并在实际依赖前完成恢复演练，不能提交到公开 Git 仓库。

## 医学知识治理边界

`knowledge-submit` 会把知识单元置为 `pending`，`review-sync` 随后创建医学审核任务。高风险知识采用双人复核：`medical_reviewer` 初审通过后，由不同的 `medical_lead` 进行终审，只有终审通过才会变为 `approved`。若终审出现分歧，知识单元保持 `pending`，系统创建 `knowledge_escalation` 任务交给 `medical_chair`，并保留驳回原因、审核人和审计事件；这不是把最后一次操作解释成临床真理。

用药安全规则必须引用已有来源知识单元，且同样经过独立初审和终审。终审分歧会创建 `medication_safety_escalation` 任务，规则保持 `pending`。项目不输出剂量、个体化处方、诊断结论或医保报销判断。

审核角色名单可通过 `REVIEWER_REGISTRY_PATH` 指向本地 JSON 白名单（可从 [`reviewers.example.json`](reviewers.example.json) 开始）。角色只是工作流路由，不等同于执业资格、机构认证或身份核验。不要在配置中保存密码、证件号或不必要的个人信息。

## 数据来源和版权

项目保存元数据和链接，不保存 CNKI/万方付费全文；不会绕过认证、验证码或未公开接口。重新分发前请逐一核对来源许可和网站条款。所有输出都是需要人工医学复核的候选数据。

上线前请阅读 [`docs/release-readiness.md`](docs/release-readiness.md)、[`docs/medical-governance-review.md`](docs/medical-governance-review.md) 和 [`docs/ai-readiness-roadmap.md`](docs/ai-readiness-roadmap.md)。本项目是研究/教学工具，不是医疗器械，不得用于真实世界临床决策。

简历项目介绍和面试表达建议见 [`docs/resume-project-profile.md`](docs/resume-project-profile.md)。
使用虚构数据跑通导入、质量报告和审核闭环的步骤见 [`examples/demo/README.md`](examples/demo/README.md)。

## 本地验证

```bash
uv run ruff check .
uv run pytest
uv lock --check
```
