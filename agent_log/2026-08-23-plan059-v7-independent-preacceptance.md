# Plan 059 revision v7 独立功能预验收

## 结论

- **PASS。** 对 `62982ee..6b66e3d`、tracked `training/publication-critic-v7/` 及指定 Plan 059 ignored 终态证据的独立复验未发现剩余 correctness/functionality finding；`remaining findings = 0`。
- revision v6 的两个阻断均已实质关闭：公开 `DatasetConsumer(...)` 直接构造不再能注入 holdout rows 或任意 rubric；六组 Scope Q+/Q- 已形成自然 candidate-token 长度交错，未再出现可稳定代替 `scope_and_signal` 判断的长度信号。
- 执行者的 provisional 数据 **GO 合理**。本结论只表示 v7 数据具备进入 M3-B1b 训练资格 smoke 的条件；计划制定者最终数据 GO、用户批准合入 main、M3-B1b 解锁、训练与模型质量仍是后续独立决定。

## 关键复验

### Consumer 与 Plan 054 输入隔离

- `DatasetConsumer` 使用 `dataclass(init=False)` 和显式拒绝的 `__init__`；公开创建路径为 `from_rows()` / `from_frozen_directory()`，两者都先从 Plan 054 v4 冻结身份自行加载固定 rubric/input identity。直接传入全量映射、`WRONG RUBRIC` 与 `allow_evaluation=False` 抛出 `TypeError`，定向回归通过。
- tracked v7 实测默认 consumer 物理只持有 `42 packet / 42 supervision / 21 pair`，且 `evaluation_split()` 被拒绝；显式 `allow_evaluation=True` 才持有 `72/72/36`，validation/unseen-test 为 `16/14`。C1/C2/C3 为 `42 Binary + 0/18/21 pair`，模型消息角色和固定 rubric 路径保持 Plan 054 合同。
- train-only bundle 为 `6 packet / 6 supervision / 2 pair`，成员全部来自 train，未包含任何 validation/unseen-test candidate ID；source hashes 与正式冻结输入一致。

### Scope 语义、原子性与捷径

- 六组 Scope Q+/Q- exact candidate tokens 分别为 `150/138`、`179/175`、`182/204`、`144/124`、`176/166`、`186/196`：4 组 Q- 更短、2 组更长，两个方向均有交错。全量正式数据的双向 threshold shortcut 独立复算为 0；Scope 子集也不存在支持数达到 5 的单标签阈值。
- 逐组阅读确认 Q- 分别使用比较器/数组交换、inode 环遍历、轮换时间线、术语会议、配置逐段替换、扫描批次指标六类不同的 product-shaped process dump；每条仍保留可依赖的核心结果、诚实完成度/不确定性和适用 handoff，只失败 `scope_and_signal`。未见新的固定前缀、统一结论、desktop/UI 主题或跨场景标签模板。
- 六个 Boundary 的非 candidate model-visible context 与最终 omission 全部相等，方向均为 `PASS > REWRITE`；独立 reviewer 对 12 个 Q+/Q- endpoint 只在 Q- 标出 `scope_and_signal`，并确认 6/6 Boundary 原子性。
- 受影响的 `pair-b-scope-04-within-pass` 已重新复核：两端均为 PASS、核心完成状态/上下文/omission 相同；扩写后的 Q+ 增加非重复的转换矩阵状态，`pass-soft` 仍主要重复同一组合，`directness_and_lower_repetition` 软方向可信。

### Review 复用边界

- 对 v6/v7 tracked rows 独立比较：只有 6 个 Scope Q+ packet 和对应 6 个 Scenario blueprint 改变；pair rows 为 0 处变化，移除 generator/reviewer identity 后 supervision 语义为 0 处变化。
- `rehearsal-v23` 的 fresh 集合恰为 12 个 Scope Q+/Q- candidate review、6 个 Scope Boundary review 和 1 个受影响 Within-PASS review；这些终态与 `formal-v12` 对应记录一致。
- `formal-v12` 复用的 60 个 candidate packet 全部与 v6 模型可见 packet 相等；复用的 29 个 pair row 及其 53 个 endpoint packet 也全部相等。没有把变化行混入 review 复用。

### 正式冻结与数据合同

- 完整终态校验通过：36 scenario group、72 candidate（39 PASS / 33 REWRITE）、30 Boundary、6 Within-PASS；split 为 train/validation/unseen-test=`42/16/14`，三个 split 均有两类标签。
- 从 tracked rows 重建 group closure 并重跑确定性 grouped stratified split，结果与冻结 assignments 完全一致；12 条 near-duplicate edge 与报告一致且全部受同 split component 约束。exact packet digest 为 72 个唯一值，Plan 054 reference match 为 0，coverage failure 为 0，model-visible char-4 shortcut 为 0。
- manifest 校验、所有 contract/file hash 和 teacher/raw input hash 均闭合；manifest content SHA-256 为 `07666936706786c456e83a7130c211013ff95cfb3e494154e62fca1e3bc528eb`。tracked v7 与 `formal-v12-final` 的 12/12 文件逐字节一致。
- 未重跑 exact tokenizer。只读取并对账已冻结 census：72 行、总计 50,073 tokens、单条 553–1,367、continuity omission 总数 0；该 census 由 manifest/hash、formal final 双物化一致性及 raw/freeze identity 闭合支撑。
- 数据卡、WBS 与 ExecPlan 正确保留 synthetic teacher reference 非人类真值、未训练/未证明模型质量、待独立验收/用户批准整合、M3-B1b 未解锁的交付边界；未夸大为训练或产品资格证据。

## 已运行项

- `python3 -m unittest -v eval.tests.test_publication_critic_contract eval.tests.test_publication_critic_eval eval.tests.test_publication_critic_training_data eval.tests.test_publication_critic_training_data_identity eval.tests.test_publication_critic_training_data_v7`：**62/62 PASS**。
- 纯逻辑独立复算：完整 `validate_dataset`、exact/near dedup、Plan 054 reference match、group closure、确定性 split、coverage、文本/长度 shortcut、manifest/hash、consumer、C1/C2/C3、bundle 隔离、v6/v7 模型可见相等性和 tracked/formal-final 字节一致性，全部通过。
- `git diff --check 62982ee..6b66e3d`：通过；审查前目标 worktree clean，提交父子关系为 `62982ee -> 6b66e3d`，tracked v7 正式目录为 12 个文件。

## 未运行与边界

- 未运行 exact tokenizer 重算、Docker、Cargo、Bazel、完整模型/权重、model forward、训练、真实 API、CI 或 PR。
- 只读查看了允许的 `rehearsal-v23{,-final}` 与 `formal-v12{,-final}`；未查看或触碰 Plan 058、`.env.local`、`mydev/`、`multidev/` 产品源码，也未修改实现、合并或推送。本报告是本轮唯一写入，未提交。
