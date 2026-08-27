# Plan 087 验收后原因研究与 WBS 收口

- Plan 087 最终仓库整改复验通过；最终结论为 `PROMISING_CANDIDATE_RETAINED / FINAL_REVIEW_ACCEPTED / ZERO_POD`，无遗留
  High/Medium correctness/functionality finding。
- 因 Route O 尚未经过干净正式复现、15 条路线共用 validation 且信号很小，按用户要求完成跨历史路线原因研究：区分 Plan 060 技术资格、
  Plan 066 全参数质量塌缩、Plan 079 4B base NO-GO、Plan 082 公共 logit 下移，以及 Plan 087 A–O 的 scope/objective/数值形态。
  报告为 `doc/research/2026-08-26-publication-critic-training-route-outcome-analysis.md`。
- 研究确认不存在单一已证实深层根因；最可信组合是基础表示任务对齐不足、小型同质数据覆盖、calibration/pair 梯度关系、更新强度与
  module-specific response 共同造成狭窄不稳定的有效区间，数值精度限制仍待对照。Route O 是值得预冻结复现的线索，不是可靠效果或产品候选。
- 已在 Plan 087 worktree 内窄同步 `doc/WBS.md`、三期子 WBS、WBS-COMPLETED 与 ExecPlan 终态，并保留并行进入 `main` 的 Plan 086/088
  当前事实。下一 Publication Critic 工作包只登记为另行规划、授权的 Route O 干净正式复现；Plan 087 剩余预算和外部动作授权不转移。
- 本批次只做文档、结果与既有小型 evidence 的只读分析；未访问 live 云/HF、未运行模型、训练、Cargo、Docker、unseen 或外部写操作。
