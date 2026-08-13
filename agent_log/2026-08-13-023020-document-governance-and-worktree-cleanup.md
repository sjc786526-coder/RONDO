# 文档治理与 worktree 收口

- 基线：`main == origin/main == 10ec08b`；Plan 020 B7 归因报告分歧已全部关闭。
- 将当前状态、下一工作包、跨任务顺序和依赖收敛为 WBS 唯一职责；更新 AGENTS/CLAUDE 与 plan 模板，
  completed plan 只保留历史交接，研究/审计只保留证据、候选与能力边界。
- 重写顶层 WBS 与方向 0/1 子 WBS，新增方向 3 子 WBS；同步方向 2、README、开发环境、数据规范和完成历史。
- B7 统一口径为：v22 机械一致性子门 `sigma=0`、`delta=3` failed，但比较条件不对称，不能形成 RONDO/Codex
  能力或性能归因。
- 独立验证 results 分支使用的 harness `ba16cb2` 与被测对象 `14341a1` / `cb652e1` 均在主线历史，净差异只有
  `eval/results/`；完整合入其 27 个提交。公共账本由 17 条增至 244 条唯一 run，v22 32 条，11 份聚合 JSON
  均可解析；历史“Plan 015”标签未改写，分支已改名 `zz-done/0811-p2-b7-results`。
- 关闭除本轮外的 14 个旧 worktree，释放约 1.6GB 工作树副本与其局部缓存。未合入 results 分支的提交链完整保留；
  已合入但仍使用活动命名的三个分支改为 `zz-done/*`。
- 本批只改文档、公共结果与 Git/worktree 元数据，未运行 Cargo、Docker、真实 API 或本地模型。验收使用
  Markdown 链接、文档职责/过时词扫描、JSON/JSONL 解析与唯一 ID 检查、`git diff --check`、分支 ancestry
  与最终 worktree/Git 状态检查。
