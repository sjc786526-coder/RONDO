# Plan 059 独立验收审查

## 结论

- **验收不通过；任务目标尚未完成。** revision v3 的基础架构、Binary/Pair 数量、group split、manifest、token census 与
  train-only bundle 大体成立，但仍有 6 项 correctness/functionality finding。当前不能给出 M3-B1b 数据 GO，M3-B1b 继续锁定。
- finding 都可在 Plan 059 现有职责内窄修；不需要 Docker、Rust/Bazel、模型 forward、真实 API、训练、额外数据平台、教师委员会或复杂审计体系。
- 本轮未修改实现或冻结数据，只新增本审查报告。

## Findings

### F059-AR-01（P1）：默认 consumer 仍直接暴露 validation / unseen-test

`DatasetConsumer.from_rows()` 把全量 `packets`、`supervision`、`pairs` 存入公开属性
（`eval/rondo_eval/publication_critic/training_data/consumer.py:76-110`）。只有 `evaluation_split()` 检查
`allow_evaluation`（同文件 `:168-173`），因此方法调用虽被拒绝，调用者仍可直接从属性枚举和读取 holdout。

对正式 v3 的最小复现结果为：`evaluation_split("unseen_test")` 拒绝，但 `consumer.supervision` 与
`consumer.packets` 各直接暴露 14 个 unseen-test candidate。这个行为与数据卡的“default consumer denies”声明不符，也不满足
ExecPlan `:195-197`、`:210-212` 的默认训练入口不可触达 holdout 合同。

建议窄修：构造时可以先验证全量冻结集合，但默认 consumer 实例只保留 train 可消费视图；只有显式 evaluation mode 才保留/公开 holdout
视图。补回归覆盖公开入口，而不建设权限系统。

### F059-AR-02（P1）：正式输入身份是可选声明，consumer 还能生成错误 rubric 输入

- `DatasetConsumer.model_inputs(name, rubric)` 接受任意自由文本（`consumer.py:158-166`）。现场调用
  `model_inputs("C1", "WRONG RUBRIC")` 成功把错误 rubric 放入 user message；现有测试未调用该方法。
- `from_frozen_directory(... expected_input_identity=None)` 与 `verify_freeze_manifest(... expected_input_identity=None)` 默认不把 manifest
  identity 与 Plan 054 v4 预期身份比较（`consumer.py:123-132`、`freeze.py:59-79`）。
- formal finalizer 只用 snapshot 目录 basename 判断 tokenizer revision（`finalize_publication_critic_training_data.py:482-486`），没有复用
  `eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json` 中 7 个 tokenizer/template/special-token 文件 hash。
- formal 的 `--teacher-freeze` 可省略；即使提供，也只检查文件位于仓库内，没有验证 freeze schema、dataset/input identity、generator/reviewer
  identity 与实际 prompt hashes（finalizer `:696-716`）。

当前 v3 并未被证明使用了错误身份：本轮复算 tracked contract/Plan 054 manifest 及本地 7 个 tokenizer 文件 hash 均与冻结值匹配。finding 是
正式路径没有兑现 ExecPlan `:172-175`、`:181-183`、`:201-203` 的 fail-closed 合同。

建议窄修：consumer 自行加载 Plan 054 fixed rubric，不接收自由 rubric；默认从现有 Plan 054 v4 freeze/design lock 派生并验证 input identity；
finalizer 复用 tracked model lock，只 hash tokenizer 所需的 7 个小文件，不读取 3.3GB 权重；formal 强制并解析校验 teacher freeze。无需通用身份
平台或签名体系。

### F059-AR-03（P1）：6 个 Conditional-continuity Boundary pair 不是单一 hard-dimension 差异

`pairs.jsonl:16-18,20-22` 声明只改变 `conditional_continuity`，但所有 Q− 在删除 actionable handoff 的同时，也删除或弱化了 summary 中的
具体公共状态，因而同时损害 `useful_state_transfer`。例如：

- `packets.jsonl:30-31` 从“空页后重复前一游标”退化为“空页分支处置没写”；
- `packets.jsonl:39-40` 从“西班牙语回退英文、键映射未补齐”退化为“没有交代做到哪一步”。

其余 01/03/04/05 有同类双重变化。这与 ExecPlan `:43-45`、`:184-187` 的 Q± 原子性要求冲突，不能由 reviewer 的
`atomicity_confirmed=true` 替代实际语义。

建议保留 Q+ 中足够且等价的当前状态，只让 Q− 缺少或提供不可执行的 handoff；对变更的 Q− 与对应 pair 重新独立复核。未变化 review 可以在逐行
相等门禁下保留，不要求浪费性重审全部 72/36。

### F059-AR-04（P1）：Scope Q− 存在明显跨 split 标签/模板捷径

6 个 `scope_and_signal` Q−（`packets.jsonl:42,44,46,48,51,53`）都采用“过程/记录 1、2 + 重复操作 + 最终结论”的固定结构，且
模型可见词“无关”只出现在这 6 个 REWRITE 中，覆盖 train、validation、unseen-test。现有 char-4-gram 检查因该强标记较短而报告 0，
但这仍是人工即可识别的标签模板，也违背 generator prompt 对固定 process diary 的禁止。

建议自然化这 6 个 Q−：保留真实的 process-dump/scope 缺陷，但去掉主动自报“无关”和统一 1/2 模板，分散过程噪声的表达结构；随后重跑已有
文本/长度 shortcut 门禁并重新复核受影响 endpoint/pair。无需新增 embedding 或语义审计设施。

### F059-AR-05（P1）：长输入覆盖的 metadata 与实际内容不可信

- 5 个 supervision candidate 标为 `long`，对应 Scenario 全是 `medium`；`contract.py:368-378` 的 Scenario 投影校验遗漏
  `length_bucket`。这 5 项是 `b-honest-04` 两端、`b-scope-01-qminus`、`b-consistency-06` 两端。
- unseen-test 唯一被计为 `long` 的 `pc059-b-scope-01-qminus` 只有 627 total tokens，其同 pair 的 620-token Q+ 却标为 `medium`，说明
  `long_input_candidates_per_split` 门禁靠不一致人工标签通过；unseen-test 实际范围仅 558–681 tokens。
- train/validation 的两个真正较长 Scenario 约 2,744–2,753 tokens，但各自 4 条 prior publication 把同一句“公开检查点……”各重复 7 次，
  共 28 次，属于机械长度填充而非可信 product-shaped continuity。

应先明确 `length_bucket` 是 Scenario 还是 Candidate 职责并使 schema/validator/coverage 一致；每个 split 的 long 覆盖应由实际较长且有意义的
公共 context 支撑。把重复填充改为少量互不重复、前后状态有真实推进的 prior publication 即可，不要求逼近 16k，也不要求扩大数据总量。

### F059-AR-06（P2）：最终数据卡遗漏 teacher reference 不是人类真值

ExecPlan `:189-191` 明确要求最终数据卡保留该限制，但 `training/publication-critic-v3/DATA_CARD.md:29-31` 只说明未训练、不证明模型质量、
不解锁 B1b。生成缺口位于 finalizer `_data_card()` 的 Limits 文案（`:390-392`）。

建议补明 Binary labels、pair directions 与 reviewer accepts 是 synthetic teacher reference，不是人类标注真值；可顺带简洁披露 34 个合成
Scenario 与 2 个 Plan 050 公共锚点。加一条聚焦回归即可。

## 已通过的聚焦核验

- 规划基线 `086f5d39...` 至实现 `f72ea0c...` 的变更未修改 Plan 054 v4 identity-bound packet/render/tokenizer/runner，未修改
  `multidev/`，未发现 Plan 058 内容或产品行为变更。
- tracked `training/publication-critic-v3/` 与 ignored `formal-v8-final` 的 12 个文件逐字节一致；manifest 文件 hash/大小与
  `content_sha256=992e193c...0582` 可复算。
- 72 个 candidate 均有 Binary，36 个 pair 引用闭合；36 个 group component 无跨 split 泄漏；C1/C2/C3 为
  `42 Binary / +18 Boundary / +3 Within-PASS`；smoke bundle 只含 train。
- 72/72 token-census 行与 53,294 总 token 对账，当前记录的 candidate truncation 和 continuity omission 都为 0；本轮未重跑全量 exact tokenizer。
- formal-v8 ignored review 记录为 72/72 candidate、36/36 pair accept，ID 与 reviewer identity 唯一闭合；这些 accept 不能覆盖上述实际语义
  finding，受影响行需返修后再审。
- 轻量门禁复跑：
  `TOKENIZERS_PARALLELISM=false .../publication-critic-plan054/bin/python -m unittest -v eval.tests.test_publication_critic_contract eval.tests.test_publication_critic_eval eval.tests.test_publication_critic_training_data`
  为 **44/44 PASS**。
- 未运行 Rust、Bazel、Docker、模型权重/forward、GPU、真实 API、训练、CI 或 PR；未读取 `.env.local`，未触碰 Plan 058。

## 修复与重新冻结边界

- 数据语义将发生变化，不能只改 manifest。按 ExecPlan 应升级 dataset revision（建议 v4 或等强的新 revision），对正式全集重新执行
  generation/finalization、group/split、dedup/shortcut、exact-token census、manifest、consumer 与双物化一致性门禁。
- 只需重审改变的 candidate/pair，以及因公共 context 变化受影响的同 Scenario endpoint；未变化的 review 可在严格逐行相等确认后复用。
  最终仍需一次干净状态的全量机械 finalization 和本审查者复验，不要求重新生成所有已验证样本。
- consumer/identity/data-card 修复应补聚焦回归；formal tokenizer identity 验证只读取小型 tokenizer 文件，不读取模型权重。
- 修复后 WBS/ExecPlan/agent log 应准确指向新 revision，v3 不得继续冒充最终数据 GO；M3-B1b 在最终验收和获批主线整合前继续锁定。

## 代用户作出的决策

- **ignored 资产暂不清理。** 总量仅约 4.3 MiB，当前清理收益为零；在修复、最终验收、获批主线整合及首次 B1b 消费验证前全部保留。
  后续如需清理，只处理 Plan 059 自有 superseded 目录，并保留当时最终 rehearsal/raw/final 四类恢复资产；绝不触碰 Plan 058。
- 本轮不要求执行者重做全部 teacher 合成或全量 teacher 语义复核。采用“受影响行返修/复核 + 未变化行逐字节确认 + 全量干净机械冻结”最符合
  用户关于保留已验证进度、避免整版浪费的要求。
