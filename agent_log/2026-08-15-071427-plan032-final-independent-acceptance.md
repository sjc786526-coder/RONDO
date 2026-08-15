# Plan 032 最终独立验收

日期：2026-08-15

审查对象：`4a95b8da288c86e396f1934a4904b01d964d2a15`

前次报告：`agent_log/2026-08-15-070024-plan032-independent-acceptance-review.md`

## 结论

- **验收：通过。** 前次唯一 blocker 已按 production archive 合同窄修，回归有效，未发现新的功能性或正确性
  blocker。
- **任务目标：完成。** 当前 47 条真实证据已有稳定语义身份、互斥 seed/holdout、语义去重和 40 条冻结 Sol
  教师标签；标签批次保持严格可导入且不冒充人工 ground truth、L3/L4 或 shadow 结果。
- 本分支可以进入用户决定的合并交付步骤；本轮仍未合并、未推送。

## 前次 blocker 复验

`teacher_labels._read_meta()` 现在从已安全读取并解析为对象的 production meta 取得非空 `review_id`，再复用现有
production validator 校验完整字段，不再把 `guardian-evidence/0001` 等四位归档槽位当作 review identity。

新增回归直接覆盖路径槽位 `0001` 与 `meta.review_id=review-1` 不同的形状；恢复旧实现会使测试失败，因此该回归
有效命中前次问题。整改只修改 review id 来源和对应测试，没有改变 prompt、schema、canonical payload、语义
身份、分区、标签或结果账本。

## 独立验证

- focused `eval.tests.test_teacher_labels`：**13/13** 通过。
- 使用内存替换私有写入函数运行完整 `prepare_batch`，真实读取当前 47 条 production archive，得到
  **47 / 45 / 2 / 42 / 40**；三个拟写文件均为预期 0600，且重建的 manifest、outbound、prepare receipt
  与冻结批次逐字节相同。该复验没有创建第二个私有批次。
- 现有私有批次 `verify` 通过：40 条、`ready_for_l3=true`；labels SHA-256 仍为
  `7eaafa25aa99de804559ee77f034f4e69f8ff4227f5cf5d8d70c66f0a7b82a40`。
- `summarize` 重跑完整 verify 后与 tracked lock 字节相同；summary SHA-256 仍为
  `237a57b4378c6c0cc4ee5ce919246dca150ea7c8646b946f17e41acc6593a57e`。
- `git diff --check ca1fde0..4a95b8d` 通过。主工作区保持
  `main == origin/main == ca1fde0dd725fed81138df3306b53cee663a567a` 且 clean。

本轮没有重新生成标签或启动第二批 Sol，没有运行 L3/L4、Local-static、本地模型、Docker、Cargo、API、训练、
CI 或全量测试，没有读取 `.env.local`，也没有修改 Guardian bridge、产品代码或 `eval/results/runs.jsonl`。

## 审查者代用户作出的决定

1. **接受 `4a95b8d` 的窄修并关闭前次 blocker。** 不要求进一步重构 `_read_meta()`，也不新增 schema registry、
   签名、provenance、审计或可信设施。
2. **继续保留现有 40 条标签，不重新生成。** 当前完整 prepare 重算与冻结批次逐字节一致，第二批 Sol 或额外重试
   没有正确性收益，反而会破坏一次完整批次的冻结边界。
3. **Plan 032 到此冻结。** L3/L4 仍按 WBS 作为下一独立工作包推进；本轮不提前实现 importer 以外的下游评分、
   结果发布、训练或 16k 路线。

执行者没有留下需要用户选择的 Plan 032 未决项；除是否合并/推送外，无需用户继续决策。
