# Plan 059 Publication Critic 训练数据实现

## 实质修改

- 新增 Plan 059 版本化 Scenario/Candidate/Binary/Boundary/Within-PASS/review 合同，以及分组切分、exact/near-duplicate、shortcut、exact-tokenizer census、freeze/manifest 和轻量 consumer；PublicationPacket、render 与 tokenizer 继续直接复用 Plan 054 v4 seam。
- 合成前冻结 72 candidate、30 Boundary、6 Within-PASS 的 coverage/stop lock。rehearsal-v1/v2 的 continuity metadata、length bucket、pair mechanism 和 mixed `hard_focus` finding 均在扩量前关闭；rehearsal-v3 全链路通过。
- 正式数据按六个小批独立复核。formal-v1/v2 暴露一个 uncertainty mechanism 粒度问题和三个 incomplete consistency pair 夹带 continuity defect；只重生成受影响 endpoint，并以逐行 Scenario/packet/supervision/pair 相等门禁复用未变化 review。formal-v3 终态为 72/72 candidate 与 36/36 pair accept。
- 首次正式冻结虽通过结构、review、token 和 consumer 门禁，但干净上下文审查发现跨 split 固定 Q-/Within-PASS marker 可完美预测标签，故 v1 判定数据 NO-GO，未提交其 tracked release；失败证据保留在主物理根 ignored Plan 059 namespace。
- revision v2 把 30 个 Q- 和 6 个 Within-PASS endpoint 改为逐场景显式文本，增加跨 split、支持数至少 4 的 label-exclusive char-4-gram 门禁；v2 rehearsal 已完成 12/12 candidate、6/6 pair accept 和全链路 finalization，正式生成待执行。

## 验收结果

- 数据：42 train / 16 validation / 14 unseen-test；39 PASS / 33 REWRITE；30 Boundary / 6 Within-PASS。稀疏覆盖、group closure、25 条 near-duplicate edge 闭包、shortcut 检查均通过，Plan 054 reference match 为 0。
- exact tokenizer：72/72 完整 census，53,199 tokens，单条 556–2,753，continuity omission 为 0；未加载模型、权重或执行 forward。
- consumer：C1/C2/C3 累计为 42 Binary / 18 train Boundary / 3 train Within-PASS；默认拒绝 validation/unseen-test，显式 evaluation mode 可读，train-only bundle 物理排除 holdout，两条 model message 顺序为 user/assistant。
- 测试：Publication Critic contract/eval/training-data focused Python tests 42 项通过；Rust、Bazel、Docker、模型推理、训练、真实 API、CI/PR 均未运行。
- 第一次干净上下文聚焦审查为 FAIL（1 个真实 shortcut finding）；当前执行者建议数据 NO-GO。revision v2 正式冻结及复审待完成，M3-B1b 未解锁。
