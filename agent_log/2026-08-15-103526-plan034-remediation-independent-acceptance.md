# Plan 034 整改独立复验

日期：2026-08-15 ｜ 审查对象：`034-l5b-synthetic-training-dataset@b5b9e7f`

## 结论

**验收通过；任务目标完成。**

首轮验收的唯一 blocker 已按要求窄修。当前 `synthetic_training.py` 不再固化或扫描私有教师批次 marker；
600 条最终数据、split、prompt/schema、manifest 和三个发布哈希均未改变。删除逐字 marker 分支没有削弱本任务的
核心合同：static-v3/decision-v1 严格校验、synthetic workspace 限定、精确去重、组安全划分和 holdout 内存近重复
排除仍由原有实现与 focused tests 覆盖。没有必要引入通用 DLP 或额外审计设施。

## 整改审查

- `b5b9e7f` 的功能代码变更仅删除 `_SOURCE_MARKERS` 常量及 `source_reference_copied` 逐字扫描，共 10 行；
  其余改动只更新 execplan 当前状态和新增整改日志。
- 相对首轮审查提交，`training/`、prompt/schema 和测试文件均无差异；没有重生成候选或更改数据合同。
- 从旧 validator 提取五个 marker 做 body-free 聚合检查：当前非日志/计划 tracked tree 只命中基线原本已有的两个
  通用片段，Plan 034 新引入的三个私有片段命中为 0。报告不复述具体值。

## 独立验证

- `test_contracts_and_evidence`、`test_teacher_labels`、`test_shadow_replay`、`test_synthetic_training`：
  **90/90 通过**。
- 正式 release verify 从私有候选和冻结教师批次复算为 `ready_for_l6`：600 条，train 470 / validation 130，
  allow 240 / deny 360，六类分布 180 / 100 / 120 / 70 / 65 / 65，holdout 排除 0。
- train / validation / manifest SHA-256 精确保持为
  `1e66c06e9357a3b6e14aedd193c5405ad2c18924e57da6a3a209f079b80c110a`、
  `cbab8084bfb78bc40f96ce9dfdb564f6fabea1d73c6d48f04ffee2c95aba8dd2`、
  `dbf5fffe1f26d7746acf43fdcd092ff3e9cd64ea1f40046cd3b7219a15107190`。
- 私有批次目录仍为 0700，六个普通文件均为 0600；tracked/private 任务树未见符号链接，`git diff --check` 通过。
- 未调用 Sol、HF/Hub、API、本地模型、训练、Docker、Cargo、CI 或 PR；主工作区和其他 worktree 未修改。

## 代用户作出的决定

1. **接受删除 marker 扫描的轻量整改。** 不增加运行时私有数据 DLP、通用敏感扫描或可信体系；现有冻结批次已由
   release verify 和近重复排除证明可复算。
2. **保留并接受现有 600 条 v1 数据。** 不重生成、不修改 prompt/schema/split，也不因模板化和短上下文这一已披露
   限制回开 L5b；训练收益交由独立 L6 验证。
3. **后续获批交付时采用 squash 或等价的干净单提交集成。** `9b8990a` 仍是当前本地工作树分支的祖先，普通 merge/
   fast-forward 会把已经删除的私有字面量历史带入 `main`。因此不得原样推送该工作树分支；应从最终干净 tree 生成
   新的 `main` 提交，并在推送前确认 `9b8990a` 不是 `main` 的祖先。该交付处理不要求再次修改数据或代码。
4. **L5b 可以收口，下一工作包仍为 L6。** L6 涉及的数据外发、云 GPU、训练、Hub 状态和费用继续使用独立授权门；
   本次复验不提前执行这些动作。

## 当前状态

- 验收状态：**通过**。
- 任务目标：**完成**，冻结数据可直接供 L6 消费。
- 交付状态：工作树分支尚未合并或推送；等待用户批准后按上述干净集成方式交付。
