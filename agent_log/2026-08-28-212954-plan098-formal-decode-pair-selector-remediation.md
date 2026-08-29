# Plan 098 正式判定与 pair selector 窄整改

日期：2026-08-28

状态：`IMPLEMENTED / FINAL_REVIEW_PENDING`

## 整改结论

复审所列两项 Medium 均存在，已在不重开五头、标签、loss、gate、数据正文或既有 review 的边界内闭合。

1. 保留 `successor-output-schema-v1.json` 和旧 raw helper 的历史字节，新增
   `formal-decision-projection-v1.json`：该投影绑定旧 schema 精确 SHA，并明确旧 raw argmax 只作
   zero-margin diagnostic/historical reference、不得承担正式判定。训练候选、validation、资格和未来产品正式 projection/call path
   唯一指向 `qualification.py#decode_with_decision_config`，且必须绑定 frozen decision config。该版本化方式避免破坏已接受 v9
   semantic identity，同时消除当前正式入口歧义。
2. `DevelopmentRelease` selector 现同时消费真实 validation candidates 与 pairs，以 candidate ID 映射 predictions；实际 pairs SHA、行数和完整
   逐 pair 结果进入 frozen config。全部 12 个 Boundary/soft-only pairs 必须满足 Q+ PASS、Q- REWRITE、非目标 head 不变性以及
   hard/applicability/gate invariance，才可进入原单一 bounded margin grid 的确定性 candidate-level 排序；没有 pair-closed 配置时 fail-closed。

## 身份与生成工件

- decision implementation commit：`29eb4a75b5d8abcd7e404747c93012efa6da9e34`；bundle：
  `f86894faabedfa3f8a9d95ba26d2c9d8297e373503c975d332c7c08b631eeacc`。
- directional runtime commit：`0ebab613193580c1e8296442fa023dc4ca01e6c8`；bundle：
  `b56d12aa8811642eb7cc9c5c4efea794e457c6828873995be2431308bb75f955`。
- directional design SHA-256：`22c0eda6b38a396a52fd8802b8bb5fdfc2c94442792cf7647b15abe4c59557c5`；config SHA-256：
  `263800e449ec4b2747126e7645e517c008024c814da60142a2c27a0191d5167f`。
- `publication-critic-v10` manifest SHA-256：`1d0d1deaae16e59c16614a40f995a0aad71347f52c3f4eb22372cc49081150a5`；
  qualification manifest SHA-256：`6ed925253f556824d9f2fd7472be89f3b3650442b5ba9e9379921d2c769bb969`。
- 两个 release 从空目录由正式 finalizer 重建；与旧 release 相比只改变 design lock、generation config、manifest 和 release identity，
  candidates、pairs、review 与 coverage 字节未变。随后在独立临时目录再次生成，两个完整目录逐字节一致。
- 首次 finalizer 调用异常地以零退出且无输出目录；未把该次计作通过，确认无残留 transaction 后用同一正式入口重跑成功，再完成独立复现。

## 验证与保护边界

- focused：qualification、directional data、successor contract，`28/28` 通过。
- 既有定向回归：successor 相关 `33/33`，旧 contract/training-data/identity/v7 `43/43`，合计 `76/76` 通过。
- 未读取或改写 v9 test、旧 unseen 或 qualification sealed 正文；v8/v9 历史路径保持不变。没有运行真实模型、GPU、Docker、付费 API、
  产品启用、合并或推送。

## ignored 暂存

本轮没有新增 ignored namespace。继续保留物理仓库根
`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098/`，总计约 `1.8M`：`commissioning/` 约 `1.2M`、
`directional-remediation/` 约 `120K`、`modules/` 约 `216K`、`qualification-set/` 约 `248K`、`reviews/` 约 `16K`。
它们是 Plan 098 commissioning、方向性整改、模块交接与封存资格生成的可复现输入，最终验收前应保留；验收通过后可由用户按需清理。

工作包三继续锁定；本轮仅申请 Plan 098 最终窄整改复验。
