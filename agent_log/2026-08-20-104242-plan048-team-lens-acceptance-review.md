# Plan 048：Team Lens 验收审查

## 审查对象与结论

- 审查对象：`worktree-048-team-lens@84d201ed6c1434c08716db26326deda8e255be1d`。
- 范围：按 ExecPlan 检查原生 bundle 兼容、共有/Team 归约、四态降级、确定性、CLI 与单文件 HTML；不扩大到
  Rust、Docker、API、模型、完整数据集或 workspace 全量测试。
- **验收结论：不通过。** 实现主体和零 hook 方向正确，但仍有 4 个可复现的功能/正确性缺口，其中前两个直接错误处理
  合法原生生命周期，当前不能作为完成状态进入 A/B 最终整合。
- **任务目标结论：未完成。** 两阶段代码已经形成，但“读取合法原生 trace 并一致解释 Agent/Event/Version/时间顺序”
  尚未在这些原生合法场景下成立。

## 阻断问题

### 1. 合法结构化 SessionSource 被误拒绝

- `eval/rondo_eval/team_lens/reducer.py:1568-1578` 把所有对象形态 `session_source` 都当作
  `subagent.thread_spawn`，没有 parent 就抛错。
- 原生 `SessionSource` 还允许 `Custom`、`Internal`、`SubAgent::Review/Compact/...` 等合法对象形态；原生
  rollout reducer 只有在确实存在 `subagent.thread_spawn` 时才提取 parent，其他形态不伪造 parent、也不因此拒绝。
- 临时合成复现把 root metadata 从字符串 `cli` 改为合法 `{"custom":"app-server"}`，当前消费者错误返回
  `BundleError: spawned thread metadata has no parent identity`。
- 应窄修为：只在存在结构正确且 parent 非空的 `subagent.thread_spawn` 时返回 parent；其他合法 source 形态返回
  `None`，后续沿用已有 root/缺 parent 降级语义。不要新增通用 SessionSource 审计器。

### 2. turn 结束时没有按原生 reducer 语义关闭仍运行的 inference

- `eval/rondo_eval/team_lens/reducer.py:487-492` 结束 turn 时只关闭 turn；
  `eval/rondo_eval/team_lens/reducer.py:593-613` 只接受单独 inference terminal event。
- 原生 reducer 明确在 turn 结束时关闭仍为 running 的 inference：completed/cancelled turn 对应 cancelled inference，
  failed/aborted 分别对应 failed/aborted；之后到达的 late partial/cancel event 可以补 usage/response metadata，但不能覆盖
  turn-end 已确定的 terminal 状态和时间。
- 临时合成复现移除单独 `inference_completed` 后，当前输出为 `turn=completed`，但 inference 仍是
  `running` 且 `ended_seq=null`，会让 timeline 永久显示错误的活动状态；合法 late terminal 顺序还会被当前重复终止检查拒绝。
- 应完整对齐上述原生收口语义，并补“无单独 terminal”及“turn-end 后 late terminal”两个窄回归。

### 3. invocation payload 合法缺失时丢掉 ToolCallKind 已携带的机械身份

- `eval/rondo_eval/team_lens/reducer.py:623-631` 在可选 `invocation_payload` 缺失时只保留 kind tag，例如把
  `{"type":"other","name":"team_publish"}` 归约成 name=`other`。
- 原生 `ToolCallKind::Other{name}` 和 `Mcp{server,tool}` 已携带 body-free、typed 身份。当前行为不仅无谓降低普通工具名，
  还会让 `reducer.py:817-825` 跳过本来可解析的 Team result。
- 临时合成复现移除 `team_publish` 的可选 invocation ref 后，归约器没有记录 revision 1，并把工具名写成 `other`；这不是
  “字段确实不可用”，而是遗漏了同一原生事件内已有的机械事实。
- 应优先使用 invocation 的精确名称；缺失时从 `Other.name` 或 `Mcp.server/tool` 回退。只有确实无法恢复的展示字段才降级，
  不需要 hook 或解析正文。

### 4. Event/Version 关系链按 ID 词典序而非原生时序排序

- `eval/rondo_eval/team_lens/reducer.py:1391-1397,1469-1479` 将 Team rows 和关系 ID 纯字符串排序，
  `eval/rondo_eval/team_lens/report.py:83` 再直接把 `event.version_ids` 当作可视链顺序。
- RONDO ID 含十进制 ordinal；词典序会把 `ver-1.10-*` 放在 `ver-1.2-*` 前。当前 24 个样本的 11 个多版本 Event
  尚未超过触发该问题的 ordinal，因此现场复验没有暴露，但合法后续 trace 会让报告与 `first_seq`/原生登记顺序不一致。
- 应使用 `(first_seq, stable_id)` 之类的机械顺序统一 Team rows 和关系链；不要通过正文或 ID 外观猜时序。同一 observation
  内无法再细分时可用 stable ID 作确定性 tie-break。

## 非阻断观察

- capability 总矩阵能显示四态，但 Attention 有数据时、Event/Version 视图中没有就地重复显示 partial/reason。
  Fact 视图已有就地标记。当前总矩阵已满足基本可见性，本轮不把重复 badge 当作单独阻断，也不要求为此建立额外设施；
  执行者若修改相邻 report 代码，可顺手采用同一小 helper 改善。

## 已通过的部分与实际验证

- `PYTHONPATH=eval python3 -m unittest -v eval/tests/test_team_lens.py`：20/20 通过，约 0.1 秒。
- 指定 ignored 现场 24/24 个 RONDO M-5 bundle 归约成功；每个 bundle 重复 JSON 与 HTML 均字节一致。最终矩阵与执行者
  声明一致：1 个 bundle 五类 Team capability 全 available，其余诚实出现 partial。
- 合成 CLI `reduce` 两次、`report` 两次均返回 0，JSON/HTML 各自字节一致；内嵌 JavaScript 通过 `node --check`。
- body-free 白名单、Codex `team=null + not_applicable`、projection 只读 canonical 外壳、HTML 转义/自包含、renderer 不读 raw
  trace、wait 不伪造成 interaction、Fact observation/omission 降级等既有定向回归通过。
- 零 hook 决策仍成立：上述 4 项都能仅靠现有 typed 原生字段和 Python consumer 修复，不需要修改 Rust、Team State、
  trace writer 或冻结 Codex。
- 未运行 M-5 共用测试、Cargo、Docker、API、模型、完整数据集或全量测试；实现没有修改共用 M-5 reader，故不为本次
  审查扩大这些门禁。

## 代用户作出的决策

1. **不接受 `84d201e` 为任务 B 完成提交，也不进入 A/B 最终整合、合并或推送。** 先由 048 执行者完成上述窄修。
2. **保持零 hook。** 这些问题都不是 trace 字段缺口，不授权或建议修改 runtime/Rust 来规避 consumer 问题。
3. **修复路线保持自主但语义冻结：** SessionSource 与 inference closure 对齐冻结原生 reducer；工具名优先 typed kind fallback；
   Team 关系按原生 sequence/`first_seq` 排序。内部 helper、测试组织和具体代码结构由执行者自行选择。
4. **验证仍保持轻量：** 增加对应合成回归，复跑 Team Lens 定向测试、24 bundle 确定性与 CLI smoke 即可；不要求 Cargo、
   Docker、真实 Codex/API/模型、全量 eval 或新审计设施。
5. **Codex 侧继续接受结构忠实的合成原生 fixture。** 本轮没有现成真实 Codex bundle，且原授权禁止 API/模型；无需为了
   “真实”标签扩大授权。合成证据仍须如实标记。
6. capability 局部 badge 改善不是重新验收的独立门；只要总矩阵和相关空/降级状态保持清楚，不要求额外可视化框架。

## 重新验收条件

- 上述 4 个问题各有先失败后通过的窄回归，且原有 20 项功能测试继续通过。
- 24 个指定 RONDO bundle 仍全部归约成功并保持 JSON/HTML 字节确定性；CLI smoke 继续通过。
- diff 中没有 raw trace、正文、生成的 JSON/HTML、依赖或任务 A/共享 WBS 改动。
- 执行者只提交 048 本地分支，不合并、不推送，然后交回审查。
