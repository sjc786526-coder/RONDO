# Plan 044 / Multi M-5 门 1 证据绑定复验（阶段 A 收口）

日期：2026-08-18 ｜ 审查对象：`worktree-044-multi-m5-real-workflow-and-nondegradation` @ `1aaecb7`
｜ 前两轮报告：`...-210000-plan044-m5-phase-a-independent-acceptance.md`、
`...-233000-plan044-m5-phase-a-remediation-rereview.md` ｜ 审查者：独立审查会话（未参与本轮修复）

## 结论

**复验通过，阶段 A 收口。** 门 1 判据这条线上的三处缺陷全部关闭，每处都有反例回归钉住，
并且**正向通路首次用冻结二进制实测确认**（此前两轮都只验了反面）。无全局回归。

阶段 A 的含义仍然只是「M-5 已具备真实运行条件」。**不是** M-5 通过、门 1 通过或未见退化 ——
两道门的 runner 都还没实现，真实 API、付费与 Docker 仍未授权。

## 本轮实测（关键证据）

### 正向通路：冻结二进制 + 本地 stub，端到端跑通（此前无人验过）

用冻结 Multi 二进制配 stub 让模型真的依次调用 `team_publish` 与 `team_inspect(action=dump)`，
把捕获到的 3 个 Responses 请求体喂给采集器：

```
请求数=3 rc=0
采集到 dump 行数=6  log行=0  wait信号=0  unattributed=[]
  {"entry":"participant","label":"/root","role":"root"}
  {"entry":"event","event_id":"evt-1-d1c061a9…"}
  {"entry":"version","version_id":"ver-1.1-d1c061a9…","author":"/root","root_state":"tracking","fact_ref_count":0}
  {"entry":"visibility",…} {"entry":"activity",…} {"entry":"publication",…}
```

这一次证明了四件此前只是推断的事：真实 `team_inspect` 调用确实执行；CLI 写回的
`function_call_output` 正文就是真实 dump 负载；采集器把它正确归属（`unattributed` 为空）；
真实行的 `entry` 标签、`role`、`root_state`、文档顺序与判据假设逐项吻合（Root 自建 Version 落在
`tracking` 也符合设计合同第 9 条）。**绑定工具名没有把门焊死**，执行者先查后修的判断成立。

### 反面：两个反例都被拒

- 上一轮的 Root 独角戏反例：`passed=False`，四项谓词失败。
- 本轮的伪造反例（`exec_command` 回显整套伪造 dump + 回显 TeamActivity 原文）：
  `passed=False`，**六项谓词全失败** —— 伪造负载被整体丢弃，修前是 `passed=True`。

### 回归与一致性

- 完整离线 `just eval-test`：**854 项**，仅剩既有的 2 项 Local 模块加载失败
  （干净 `main` 同样复现，与本任务无关）。相对上轮 851 项新增 3 项，无新增失败。
- `just eval-multi-m5-loopback`：通过。
- `instruction_sha256` 重算值与锁**逐字符相符**（`b11136af…1b322`）。
- 未跑 Rust（`multidev/` 本轮零改动）、未跑 Docker、未调真实 API、未产生任何费用。

## 信任边界的最终核查（本轮重点）

修复后再从头推一遍"模型能否自造一次门 1 通过"：

- **传输**：`function_call_output` 只能由 CLI 写入，模型无法自行发出该类型的 item；采集器只取
  `_CALL_TYPES` / `_OUTPUT_TYPES`，assistant message 不进入。
- **归属**：工具名决定由哪个 handler 执行，模型改不了；不带 `namespace` 的 `team_inspect` 会得到
  `unsupported call`，不是 JSON 负载，`_absorb_inspect` 直接丢弃。
- **内容**：dump 内容全部由 canonical 团队状态派生 —— 参与者由 `team_participant_identity`
  从权威 session 身份注册，`author` 是 `label_of(ThreadId)`，都不是模型自报。M-1 第 22 条
  "取不到权威身份即 fail-closed" 在此仍然兜底。
- **越权**：`team_inspect` 是 Root-only（`require_root`），成员调用拿不到 dump。

结论：三条路径（伪造传输、冒名归属、注入内容）都关闭了。

## 并发 / 生命周期

本轮改动是纯解析层，没有新增并发面。上一轮确认的关键保证仍然成立且未被触碰：
dump 续页校验 `instance` / `revision` / `availability_epoch` / `observe_generation` 四项，
跨快照拼页在 Rust 侧就被 `DumpCursorStale` / `InstanceReset` 拒绝，采集器
"带 cursor 才拼接、否则替换"的规则与之一致（`collect.py:136-148` 未改）。
最坏情况是续页报错、证据截断，属 fail-closed。

## 遗留与观察（均不阻塞阶段 A 收口）

- `ignored_evidence` 故意不进 `reasons`：同意这个取舍（无关工具偶然输出 `action=dump` 不该把合法通过
  翻成失败）。但它必须出现在阶段 B 的 run 记录里，否则门 1 失败时无法区分"模型伪造"与"wire 形状变了"。
- 阶段 B 的请求捕获必须保留**完整**请求体。实测表明最后一个 body 已携带完整历史（call 与 output 同在），
  所以全量或只留最后一个都能归属；但一旦捕获被截断，证据会静默丢失成假阴性。
- `non_code_mode_only=false` 与产品默认（true）不同，门 1/门 2 因此验证的是团队工具在 code-mode
  嵌套面下的形态。执行者已实测两种取值下证据都可归属，选择不动冻结值，判断合理；
  但 M-5 最终结论应写明"协作闭环在该工具面下验证"，不要泛化成全部工具面。
- 预期内未完成：门 1 runner、门 2 交错执行面、预算记账接线、归档落盘 —— 都是阶段 B 前置工作。
- 既有无关缺陷未变：`just eval-test` 仍加载不了两个 Local 测试模块，仍建议单开窄修。

## 替用户做出的决策

| # | 事项 | 决策 | 理由 |
|---|---|---|---|
| F1 | 阶段 A 是否收口 | **收口，复验通过**。可表述为"M-5 已具备真实运行条件"，不得表述为 M-5/门 1 通过 | 三处缺陷全关、正反两面都有实测证据、无回归 |
| F2 | 真实付费 | **仍然锁定**。未经用户明确授权，不碰真实 API、付费调用与 Docker 拉取/运行；阶段 B 只做离线前置准备 | 用户本轮明确要求；也符合 WBS §6 授权门 |
| F3 | 付费前的最后一道关 | 门 1 runner 与门 2 交错执行面**实现后需再过一次独立审查**，通过后再申请付费授权 | 那是真正花钱并产出结论的部件，判据已连栽三轮，不宜直接上真金白银 |
| F4 | `ignored_evidence` | 必须写进阶段 B 的门 1 run 记录 | 门 1 失败时要能区分伪造与 wire 漂移 |
| F5 | 请求体捕获 | 阶段 B runner 必须保留完整请求体，不得截断 | 截断会把证据静默丢成假阴性，白烧付费尝试 |
| F6 | 工具面口径 | M-5 结论写明协作闭环是在 `non_code_mode_only=false` 的工具面下验证的 | 诚实标注验证边界，不泛化 |
| F7 | 文档同步 | **由本审查者直接完成**：`doc/WBS.md`（5 处状态行）与 `doc/WBS/multi-agent-trusted-evidence.md`（2 处）已从"独立验收不通过、待复验"改为"复验通过、已具备真实运行条件；阶段 B 未开始" | 权威规划文档不能与刚做出的验收结论相矛盾；改动纯机械，不涉及设计 |
| F8 | 先前已批冻结值 | 维持不变（provider、双侧模型、超时、轮次、运行上限、$120 硬上限、十个镜像、外发边界、只提交不合并） | 本轮未改动这些值 |

## 验收判定

- **做得对不对**：**通过**。修复精准、范围最小，先查 wire 形状再动手的顺序正确，
  没有为了堵洞把门焊死；三项新增回归覆盖真实 wire 形状、伪造拒绝与唤醒来源，非同义反复。
- **是否实现预期**：**阶段 A 目标达成** —— M-5 已具备真实运行条件。
  Plan 044 的总目标（M-5 两道门）**仍未完成**，属预期内：阶段 B 未开始，且按 F2 保持付费锁定。
