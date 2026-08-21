# Demo 数据与端到端演示

这些文件只包含虚构的公开元数据和教育性知识陈述，不包含患者信息，也不构成临床建议。

## 快速运行

在仓库根目录执行：

```bash
export DATABASE_URL="sqlite:///demo-run.db"
export DATA_DIR="demo-output"
export REVIEWER_REGISTRY_PATH="reviewers.example.json"

uv run guidelineops import-file --source cnki examples/demo/metadata.csv
uv run guidelineops quality-report
uv run guidelineops knowledge-import examples/demo/knowledge.json
uv run guidelineops knowledge-submit ku-demo-western
uv run guidelineops medication-safety-import examples/demo/medication-safety.json
uv run guidelineops medication-safety-submit med-demo-001
uv run guidelineops review-sync
uv run guidelineops review-list --status open
```

审核任务 ID 由数据库顺序分配。对 `knowledge_medical_review` 和
`medication_safety_review` 任务使用 `medical-reviewer-example` 初审；初审通过后，
对相应的 `*_final_review` 使用 `medical-lead-example` 终审。若用
`review-reject` 制造分歧，系统会创建 `knowledge_escalation` 或
`medication_safety_escalation`，再由 `medical-chair-example` 裁决。

演示结束后可删除 `demo-run.db` 和 `demo-output/`；它们不应提交到 Git。
