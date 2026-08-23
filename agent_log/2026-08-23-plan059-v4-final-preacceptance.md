# Plan 059 revision v4 最终干净上下文预审

审查对象：`worktree-059-publication-critic-training-data@fbe00cd6980f1e627554efb116b9d7e5de348a22` 的全部 staged 变更、
tracked `training/publication-critic-v4/`，以及有界只读的主根 Plan 059 `formal-v9` / `formal-v9-final` 正式证据。

## 结论

- **FAIL；revision v4 仍有 2 项 correctness/functionality finding。** 当前不能给出执行者 provisional 数据 GO，更不是计划制定者最终数据 GO；
  M3-B1b 继续锁定。
- 原 6 项 finding 中，默认 consumer 物理 holdout 隔离、Plan 054 固定 rubric/input/tokenizer identity 与 mandatory teacher freeze、
  Scenario/exact-token long 和非机械历史、数据卡 teacher 非人类真值四项已关闭；continuity Q± 标签语义与 scope 跨 split 模板捷径尚未真实关闭。
- 两项均可在 Plan 059 现有数据职责内窄修，不需要 Plan 058、Docker/Cargo/Bazel/Rust、模型/权重/forward、训练、真实 API、CI/PR 或额外平台。

## Remaining findings

### F059-V4-01（P1）：6 个 continuity Q− 已保留足够可接续状态，`REWRITE` 标签不符合产品合同

产品合同 `doc/rondo-multi-publication-critic-product-contract.md:104-120` 的最低条件是：未完成事项让接手者知道“已到哪里、卡点或下一步起点”；
它同时明确“必须有 handoff”不是 hard requirement。v4 generator prompt 却在
`eval/templates/publication-critic/training-data-generator-prompt-v4.md:7` 固定为 Q− 逐字保留完整 Q+ summary、只删除 handoff。

结果是 `training/publication-critic-v4/packets.jsonl:29,31,33,36,38,40` 的 6 个 Q− 都已经直接给出窄而可行动的落点，例如：

- `pc059-b-continuity-02-qminus` 明确问题只在“过滤后无结果的分页分支”，并保留非空分页/下一页起点对照；
- `pc059-b-continuity-03-qminus` 明确孙进程仍存活且 `job object` 继承尚未接入；
- `pc059-b-continuity-04-qminus` 明确失败只在重复索引的清理分支；
- `pc059-b-continuity-05-qminus` 明确只剩空/非空混合批次正式回归，而且同 packet 最新 prior publication 已保留完全相同的行动 handoff；
- `pc059-b-continuity-06-qminus` 明确只缺 `es-ES` 键映射。

这些 packet 没有因为当前 handoff 为 null 就失去“已到哪里/卡点/起点”。但
`supervision.jsonl:29,31,33,36,38,40` 仍把它们全标成只有 `conditional_continuity` 缺陷，6 个 pair 在
`pairs.jsonl:16-18,20-22` 仍声明 `PASS > REWRITE`。formal-v9 reviewer rationale 也把“缺少 actionable handoff 字段”本身当成失败，
没有按冻结产品 rubric 判断完整 packet。

最小复现：直接把上述任一 Q− 对照产品合同 §3.1；无需外部事实即可从 summary（`continuity-05` 还可从已提供 public history）确定继续落点，
因此至少不是当前声明的原子 `PASS > REWRITE` 边界。需要重新撰写真正缺少可接续状态、但仍保留等强有用状态的 Q−，并重新独立判定受影响
candidate/pair；不能继续把 null handoff 当标签条件。

### F059-V4-02（P1）：6 个 scope Q− 仍共享跨三 split 的“桌面/UI 外观操作”标签模板

`training/publication-critic-v4/packets.jsonl:42,44,46,48,51,53` 虽去掉了“记录 1/2”“无关”“最终结论”等字面 marker，
但六条仍采用同一个语义模板：先堆叠多项窗口、配色、截图、缩放、侧栏、字体、图标等桌面/UI 外观操作，再接一小段真正公共状态。
它们覆盖 train / validation / unseen-test，且全部为 `REWRITE`（对应 `supervision.jsonl:42,44,46,48,51,53`）。

最小机械复现：在 72 条 candidate summary 上统计以下简单外观操作词表，命中至少 3 个词的行恰好只有这 6 条，标签为 6/6
`REWRITE`，并覆盖三个 split：

`配色, 颜色, 透明度, 阴影, 图标, 字号, 字体, 缩放, 光标, 行号, 自动换行, 书签, 截图, 窗口, 侧栏, 提示音, 提示符动画, 任务栏, 通知区域, 桌面快捷方式, 鼠标停留, 键盘布局`

现有 char-4-gram 门禁报告 0，是因为同一语义模板换了词，并未消除“出现一串桌面美化动作即可判 REWRITE”的捷径。这会让模型学习噪声题材，
而不是判断过程内容是否压过 local-scope 核心信号。应把 scope negatives 分散为不同的 product-shaped 过程噪声形态（例如相关但冗长的排查过程、
重复状态/命令/日志摘录等），或加入等强反例打破该特征与标签的完美关系；随后重审变更 endpoint/pair 并重跑全量 shortcut/split/freeze。

## 已通过的独立核验

- staged 范围符合 Plan 059；未见 `multidev/`、`mydev/`、Plan 058、Plan 054 identity-bound input 实现或产品行为改动。
- `formal-v9` 的 raw review input hash 全部与 reviewer-run 一致；72/72 candidate、36/36 pair 均为 terminal `accept`，且只有一个统一 reviewer
  identity。该机械终态不能覆盖上述 rubric/捷径 finding。
- tracked v4 与 `formal-v9-final` 恰有同名 12 文件且逐字节一致；manifest content/file/contract hash、Plan 054 v4 input identity 与当前
  staged contract hash 均复算通过。
- packet 与监督物理隔离；72 candidate / 36 scenario / 36 pair 引用闭合。split 为 42/16/14，39 PASS / 33 REWRITE；group component、
  19 条 near edge 和 pair 均无跨 split 泄漏，Plan 054 reference match 为 0。
- token-census 72 行逐行 bucket 对账，总计 49,234，omission 为 0；三 split 各有 2 个 1,000-token 以上 long endpoint，每个 long packet
  有 4 条互不相同且状态推进的 public history，非 long 均不超过 999。现有文本 char-4-gram 和 exact candidate-token threshold 门禁均报告 0。
- 默认 consumer 只保留 42 packet / 42 supervision / 21 pair，显式 evaluation 为 72/72/36；C1/C2/C3 为
  `42 Binary / +18 Boundary / +3 Within-PASS`。train-only bundle 无 holdout，且四个 source hash 均匹配 tracked freeze。
- 数据卡已明确 synthetic teacher reference 不是 human-labelled ground truth，也未把数据冻结表述为训练或模型质量证据。
- focused Python：Publication Critic contract/eval/training-data/identity/v4 共 **58/58 PASS**。本轮没有重新访问 Plan 054 tokenizer snapshot，
  没有重跑 exact tokenization；只对已冻结 census、render hash、manifest 和 formal evidence 做只读复算。

## 边界

本轮未修改实现、数据、WBS、ExecPlan 或既有日志；唯一写入是本报告。未读取 `.env.local`，未触碰 Plan 058，未运行 Rust、Cargo、Bazel、
Docker、完整模型/权重、forward、训练、真实 API、CI 或 PR。ignored 证据只读取了明确授权的 `formal-v9` 与 `formal-v9-final`，没有扫描其他
`eval-data`。本结论不授权 M3-B1b，也不替代修复后的再次独立预审或计划制定者最终验收。
