# Plan 059 修复后独立验收复验

## 结论

- **验收不通过；任务目标本轮仍未完成。** revision v6 已实质关闭上一轮大部分问题，冻结、身份、factory 消费、long 输入与数据卡均明显收敛；但仍有 2 项 correctness/functionality finding，当前不能给出 M3-B1b 数据 GO，M3-B1b 继续锁定。
- 两项问题都可在 Plan 059 内窄修，不需要扩大数据规模、重做全部 teacher 合成/复核，也不需要 Docker、Cargo/Bazel、模型 forward、真实 API、训练、CI、审计平台或可信体系。
- 本轮未修改实现或冻结数据，只新增本审查报告。

## Findings

### F059-RR-01（P1）：公开 `DatasetConsumer(...)` 构造器可绕过 holdout 与固定 rubric 合同

两个正式 factory 已正确验证 Plan 054 identity，并让默认 consumer 物理只保留 train；但 `DatasetConsumer` 仍是带自动公开 `__init__` 的
dataclass（`eval/rondo_eval/publication_critic/training_data/consumer.py:77-84`），同时作为包级公共 API 导出
（`eval/rondo_eval/publication_critic/training_data/__init__.py:3-8,46-48`）。调用者可直接传入全量 registry、任意
`_fixed_rubric` 和默认的 `allow_evaluation=False`，完全绕开 `from_rows()` / `from_frozen_directory()` 的验证与裁剪。

对 tracked v6 的最小复现结果为：直接构造后 `allow_evaluation=False`，但实例仍持有 `72 packet / 72 supervision / 36 pair`、其中
14 个 unseen-test candidate；`model_inputs("C1")` 还会把传入的 `WRONG RUBRIC` 放进模型输入。现有回归只覆盖 factory
（`eval/tests/test_publication_critic_training_data_identity.py:77-127`），因此 60/60 通过没有覆盖这个公开入口。

这仍违反 ExecPlan `:181-183` 与 `:210-212` 的固定输入和默认训练入口不可触达 holdout 合同。建议仅封闭自动公开构造路径，让实例只能由受控
factory 创建，并补一项直接构造被拒绝的回归；具体实现可由执行者选择，不需要权限系统。若顺手把内部映射转为只读视图成本很低可以做，但不是本次
验收的新增硬要求。

### F059-RR-02（P1）：Scope Q− 形成新的明显跨 split candidate-token 长度捷径

原 v3 finding 中的“无关”、统一 `记录 1/2` 和共同 desktop/UI 主题已经消除；六个 Scope Q− 现在是不同、与产品场景相关的过程噪声。
但六组 Q+/Q− 的 exact candidate-token 分布几乎完全分离（`training/publication-critic-v6/token-census.jsonl:41-53`）：

- Q+：`88, 108, 105, 85, 93, 99`
- Q−：`138, 175, 204, 124, 166, 196`

全数据中 `candidate tokens >= 134` 的 5 个样本全部是 Scope REWRITE，横跨 train、validation、unseen-test；`>= 110` 则为
`6 REWRITE / 1 PASS`，唯一 PASS 是 133-token 的 Within-PASS endpoint。也就是说，最长的五个 candidate 可以不理解
`scope_and_signal` 就稳定猜出 REWRITE，而六个 Scope Q− 也可以基本按长度识别。

`reports.json:171` 的空 finding 在当前设计锁下是机械上正确的：门禁只拒绝“至少 6 个样本且 100% 同标签”的完美阈值
（`eval/templates/publication-critic/training-data-design-lock-v6.json:27-35`），因此刚好漏过 5/5 与 6:1。ExecPlan `:204-206` 还要求人工发现的
明显长度外观不能稳定替代 qualification；该宏观要求不能由窄门禁的 `[]` 覆盖。

建议直接调整这六组 Scope candidate 的自然长度分布，使 PASS/REWRITE 有可信交错；可以缩短过程噪声、充实有意义的 PASS 公共状态或采用更优组合，
但不能用机械 filler。无需建设新的通用统计/审计设施，也不要求扩大 72 个 candidate 的规模。变更的 endpoint 与 pair 需要独立复核，未变化行仍可
在逐字节相等后复用既有 review。

## 上一轮 finding 关闭情况

- **F059-AR-01 / 02 部分实现路径已关闭：** factory 实测默认 `42/42/21`、显式 evaluation `72/72/36`，validation/unseen-test 为
  `16/14`；`model_inputs()` 不再接收自由 rubric，manifest expected identity 已必填，Plan 054 v4 identity、7 个 tokenizer-only 文件和 formal
  teacher freeze 均 fail closed。剩余的是 F059-RR-01 的公开构造旁路。
- **F059-AR-03 已关闭：** 六个 continuity Q− 均保留可依赖的具体已验证进展，只不公开当前 blocker/接续起点；非 candidate context 与
  omission 保持相同，独立 reviewer 也只判定 `conditional_continuity` 失败。这里的原子性按“仅一个 hard qualification 从通过变为失败”理解，
  不要求 candidate 文本逐字相同。
- **F059-AR-04 的固定模板已关闭，但出现 F059-RR-02 的长度捷径。**
- **F059-AR-05 已关闭：** `length_bucket` 为 Scenario 级合同；train/validation/unseen-test 各有一个真实 long Scenario 的 PASS/REWRITE 双端，
  exact totals 分别约 `1354/1363`、`1367/1367`、`1322/1338`；每个 context 有 4 条互不重复且状态推进的公共历史，未见机械填充。
- **F059-AR-06 已关闭：** v6 数据卡明确 synthetic teacher reference 不是 human-labelled ground truth，并披露 34 synthetic / 2 public anchor。

## 已通过的聚焦复验

- tracked `training/publication-critic-v6/` 与 ignored `formal-v11-final` 的 12 个文件逐字节一致；manifest content SHA 为
  `9c44fa1239e2190254ef983fb825a4bff6bbf20b8a18be7aaaf7b3fc848a6900`。
- 72 candidate（39 PASS / 33 REWRITE）、36 pair（30 Boundary / 6 Within-PASS）、42/16/14 split、C1/C2/C3
  `42 Binary / +18 Boundary / +3 Within-PASS` 与 train-only smoke bundle 对账成立；group closure、reference match、已有 dedup/shortcut 报告和
  stored exact-token census 身份闭合。
- 正常 factory consumer smoke 为默认 `42/42/21`、evaluation `72/72/36`，C1/C2/C3 pair 为 `0/18/21`，模型消息角色严格为
  `user, assistant`。
- 复跑 5 个相关 `unittest` 模块为 **60/60 PASS**。本轮没有重复执行完整 tokenizer census；正式 `formal-v11-final` 与 tracked 逐字节相等，
  stored census 已足够用于本次长度复算。
- v6 对 v19/formal-v10 的唯一“没有收口”→“还有空白”表面替换不改变该 candidate 的 Binary/defect/pair 语义；接受复用已有独立语义决定与
  执行者机械复验，不要求为这一处再单独消耗 teacher。此次接受不覆盖 F059-RR-02 后续对 Scope 文本的语义修改。
- worktree 与主工作区均 clean；main 与 origin/main 仍为 `2ac4e850...`。未 merge、push、rebase；未触碰 Plan 058、`.env.local`、产品行为、
  Docker、Cargo/Bazel、模型权重/forward、GPU、真实 API、训练、CI 或 PR。

## 修复与重新冻结边界

- Scope candidate 文本将发生语义变化，按 ExecPlan 应升级 dataset revision（建议 v7 或等强新 revision），对正式全集重新运行 group/split、
  dedup/shortcut、exact-token census、manifest、consumer、bundle 与双物化一致性；不能只修 manifest。无需增加 candidate 数量，也不要求重新切
  split，除非现有 grouped split 因实际变更不能继续满足门禁。
- 只需独立复核发生变化的 Scope endpoint/pair；其余 review 可在逐字节相等门禁下复用。最终仍需一次干净状态的全量机械 finalization。
- consumer 构造旁路应做窄代码修复与回归，并进入新 revision 的 contract hash；不要求引入鉴权、签名或不可绕过的 Python 安全沙箱。
- M3-B1b 保持锁定，直到新 revision 无剩余 finding、独立验收通过并经用户批准合入 main。

## 代用户作出的决策

- **接受 v6 单句表面修复复用 v19/formal-v10 独立语义结论。** 执行记录对此已透明披露，不要求补做一轮没有信息增益的 v6 全量 teacher 终审。
- **不扩大 shortcut 基础设施。** 本轮直接修正已知 Scope 长度分布即可；是否增加一条窄回归由执行者自主决定，不要求近完美统计平台、embedding、
  语义审计或因果证明。
- **继续保留 Plan 059 ignored 资产。** 当前约 7.8 MiB，清理收益很小；至少保留到后续修复、最终验收与获批主线整合。只可在最终验收后清理
  Plan 059 自有 superseded 批次，绝不触碰 Plan 058。
- **不批准合并、推送或解锁 M3-B1b。** 本轮仍只允许执行者在 059 worktree 内修复并提交。
