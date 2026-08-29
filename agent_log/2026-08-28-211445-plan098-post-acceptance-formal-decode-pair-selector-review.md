# Plan 098 验收后正式判定与 pair selector 复审

日期：2026-08-28

审查基线：`a8d2abde4190d4b3e446205935ddee8d3fa7b471`

结论：`NARROW_REMEDIATION_REQUIRED / 0_HIGH / 2_MEDIUM`

## 总结

任务规划者提出的两项问题均存在且有必要整改。它们不会推翻五头、非补偿 gate、v9/v10/qualification 数据或已完成的捷径与 reviewer
整改，但会影响工作包三形成候选时采用哪个正式 decoder，以及 validation margin 是否保持 Boundary/invariance 合同。因此暂停 Plan 098
最终接受，工作包三继续锁定。

## Medium 1：正式判定入口不唯一

`rondo-publication-critic-task@v2` 仍把唯一最大 logit 的 argmax 规则定义为逐 head decoder；`successor-output-schema-v1.json` 的
`x-rondo-runtime-decoder` 仍指向 `successor_task.py#decode_structured_output`。同时 `rondo-publication-critic-decision@v1` 与
`decision-config-contract-v1.json` 又把绑定 frozen margin config 的 `qualification.py#decode_with_decision_config` 定义为正式 decoder。
两者对同一组无平局 logits 可以产生不同标签，仓库当前没有让训练候选、validation、资格和未来产品接线只能使用 decision v1 的唯一 formal
入口。

整改应保持旧 helper 作为明确命名的 zero-margin diagnostic / historical reference，并让版本化的正式 output/decision projection、合同和调用方
唯一指向绑定 frozen decision config 的 decision v1 decoder。若保留旧 schema，其身份必须明确为非正式历史投影，不能冒充 qualification
结果。执行者可选择最干净的版本化方式；不得改五头标签、loss、gate 或数据正文。

## Medium 2：margin selector 丢弃 validation pairs

`DevelopmentRelease.select_and_freeze_validation_decision_config()` 调用 `load_validation()` 后以 `candidates, _` 丢弃已经验证的 pairs；
`_select_and_freeze_decision_config()` 只用单 candidate confusion、failure recall 与 gate 统计排序 margins。已有
`evaluate_pair_predictions()` 能逐 pair 报告 Boundary/soft-only 绝对闭合，但 selector 没有调用它。

整改应让 release-bound selector 同时消费实际 validation candidates 与 pairs，以 candidate ID 映射每个候选配置的 predicted labels，逐 pair
报告闭合结果，并把 Boundary 的 Q+ PASS / Q- REWRITE、非目标 head 不变性及 soft-only hard/gate invariance 纳入一个预冻结的轻量准入条件或
确定性排序。既然 pairs 参与选择，最终 config/selection identity 还必须绑定实际 validation pair bytes SHA，不能只绑定 candidate SHA。
具体优先级由执行者决定，但必须固定、可测试且仍是单一 bounded validation grid，不扩成多路线 threshold 搜索。

## 已确认保留

- 五头、单 backbone、一次 forward、逐头 margin、保守 continuity N/A、non-compensating AND 与派生 scalar 正确。
- validation candidate bytes、labels、行序和 batch 的 typed binding 正确；本轮只补 pair binding 与 pair-aware selection。
- v10/qualification 数据、捷径整改、family lineage、盲审、sealed 边界及 v8/v9 历史身份不重做。
- 不读取 v9 test、旧 unseen 或 qualification sealed 正文，不运行真实模型、GPU、Docker、付费 API 或产品动作。

## 代用户决定与后续边界

- 只修正式 decoder projection/call boundary 与 pair-aware selector；可以版本化并重新绑定必要 implementation/release identity，但不改数据正文、
  标签、loss、模块 review 或 qualification 内容。
- pair-aware selector 必须把 validation pairs SHA 纳入 frozen config identity；pair 闭合可作为 hard eligibility 或确定性高优先级，执行者自主选择
  更稳妥的轻量方案并在合同中冻结。
- 此前最终接受作为历史记录保留在日志和 Plan 决策记录，但当前完成态撤回，`doc/WBS-COMPLETED.md` 不继续保留 Plan 098 完成条目。
- 工作包三继续锁定。修复后只需重跑受影响 focused tests、既有 76 项定向回归和一次轻量 release 复现，再申请复验。

当前状态：验收不通过；任务目标失败（剩余两项 Medium 窄整改）。
