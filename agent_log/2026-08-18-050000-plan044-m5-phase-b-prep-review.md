# Plan 044 / Multi M-5 阶段 B 离线前置准备 独立验收

日期：2026-08-18 ｜ 审查对象：`worktree-044-multi-m5-real-workflow-and-nondegradation` @ `5bde52d`
｜ 基线：`7957997` ｜ 审查者：独立审查会话（未参与实现）｜ 本轮无费用、无 Docker、无真实 API

## 结论

**验收不通过，需一轮窄整改。** 五项交付物工程质量高、边界守得住、彩排是真的（我独立复跑过）。
但有一处会**直接把第一次付费尝试烧掉**的缺陷：

> **冻结的指令模板按字面执行，必然过不了门 1 的 `two_authors` 谓词。**
> 彩排之所以全绿，是因为 stub 额外做了一次模板从未要求的 Root 发布。

这正是用户"停在付费门前、一切就绪"的目标里最不能带过去的一类问题：彩排验的协议
与付费运行将被要求执行的协议，在决定谓词的那一维上不一致。整改是纯离线的，很窄。

## 主要发现

### P1 门 1 指令模板与判据不自洽，合规的付费运行必然失败（必须先修）

模板（`eval/templates/multi-m5/collab-workflow-instruction-v1.md`）的协议是：

1. 成员读 NOTES 并发布 → Event 由**成员**创建（作者 = 成员）
5. **成员**在同一 Event 追加第二个 Version → 作者仍是成员
6. Root 用 `team_update` 把成员的 Version 置 `root_state=resolved`

模板从头到尾**没有任何一步要求 Root 在该 Event 上发布自己的 Version**。而
`team_update` 只改生命周期、不产生 Version —— 已核对 `core/src/tools/handlers/team_tools/update.rs`：
它只构造 `LifecycleTarget` 并调 `update_lifecycle`，没有任何 Version 创建路径。

判据 `predicates._event_flags` 要求 `len(authors) >= 2 and bool(member_versions)`。
两个 Version 都是成员写的 → `authors` 只有一个 → **`two_authors` 恒为假**。

模板第 5 步的括号"（two authors on that Event, at least two Versions）"写的是**期望结果**，
但它描述的**动作**产生不出这个结果。

**实测证据**（本轮在冻结二进制上真跑，只跳过 stub 那次 Root 发布，其余协议完全一致）：

```
passed = False
predicates = {spawn_member:T, event_with_two_versions:T, two_authors:F,
              team_route:T, team_evidence:T, root_resolved:T, root_woken:T}
reasons = ('predicate:two_authors',)   requests=15   stub_errors=[]   TEAM_REPORT 已写出
```

即：协议全程走完、报告写出、其余六项谓词全真，**只因为没人告诉 Root 也发一版而判失败**。

执行者其实已经察觉到这一点 —— `rehearsal.py` 的 docstring 明写
"Root's extra publish is required by the frozen two_authors predicate" —— 但只把这次补发放进了 stub 脚本，
没有回写进冻结模板。于是彩排绿的是"stub 版协议"，付费跑的是"模板版协议"，两者恰好差这一步。

后果：付费门 1 最多三次尝试会连续失败（按执行者自己 $8/次的估算约 $24），
产出一个看起来像产品缺陷、实际是合同不自洽的"门 1 未通过"。

修法（窄）：模板补一步明确要求 Root 在同一 Event 上发布自己的 Version，重算 `instruction_sha256`
（硬约束允许改模板，只要重算 sha 并说明理由）；同时让彩排 stub 的步骤序列与模板一致，
否则彩排就不再是付费运行的证据。

### P2 付费执行器落地时必须一并解决（记录在案，纳入 F3 复审清单）

1. **`gate2._record_for` 把 `evidence_kind` 硬编码成 `"fake"`**（`gate2.py:265`）。真实 Docker/付费运行
   若复用这条路径，会把真实证据写成 `fake`，证据分区就此失真。必须由执行器决定该字段。
2. **`capture._forward` 的 `HTTPConnection(timeout=30)`**：真实模型一轮经常超过 30 秒，付费路径直接照搬会
   把正常慢响应变成 infra 失败。同时该实现把整个 SSE 响应缓冲完再返回，流式语义丢失。
3. **转发只带 Authorization / Content-Type / Content-Length**，其余请求头被丢弃。接预算代理或真实上游前
   必须核对头部保真。
4. **门 1 彩排不把 `subprocess.TimeoutExpired` 转成 infra 记录**，超时会抛栈而不是留下归档行。
   付费入口必须把超时归档成 infra，否则一次超时既花了钱又没有可核对记录。

### P3 观察（不阻塞）

- `budget.RUN_CAP_USD = $40` 相对预期单次运行（TB 约 $0.45–$1.35、门 1 约 $8）过于宽松，
  单次跑飞要烧掉三分之一预算才触发。总额 $120 是硬拦的，所以有界；建议 F3 时按实测 token 收紧。
- 预算记账目前是**组件级**成立：`open_phase_b_ledger` 会校验上限/批次/槽位数，也有三条路径的测试，
  但还没有任何真实请求路径穿过它（付费入口未实现）。"$120 在代码里"这句话对账本成立，
  对端到端付费链路要等 F3 复审时才算数。
- `gate2-fake` 归档写在 `eval-data/tmp/multi-m5-gate2-fake-records.jsonl` 而非主账本 —— 这是对的
  （fake 不该污染主账本）。执行者日志里的"20 条归档"指的就是它，我复核过：20 行、codex/rondo-multi 各 10、
  必需字段齐全、双方二进制哈希均非空。
- 既有无关缺陷未变：`just eval-test` 仍加载不了两个 Local 测试模块（干净 `main` 同样复现）。

## 已独立复核通过的部分

- **彩排是真的，不是自说自话**：stub 只发 `function_call`，所有工具输出都由 CLI 产生；
  stub 追踪的 event/version/fact id 全部从真实 CLI 输出里解析；判决时调用方 dump 传的是 `{}`，
  JSONL 才是权威。我独立复跑 `just eval-multi-m5-rehearsal`：七项谓词全真、`passed=true`、
  16 个请求、`stub_errors=[]`、`ignored_evidence=[]`，与执行者所述一致。
- **就绪自检**：`ready=true`、`missing=[]`；两侧 bundle 哈希与锁相符。`.env.local` 探针只返回布尔值，
  文件内容留在函数局部、从不外传或落盘 —— 与 CLAUDE.md「可检查所需变量存在且非空」的口径一致。
- **capture 的离线边界**：只绑 127.0.0.1，forward 上游也被限制为 127.0.0.1，
  该模块本轮**没有能力**直连付费端点；请求体在处理**之前**就整体落盘（F5），capture 路径做了符号链接防护。
- **归档落盘**：`O_APPEND|O_NOFOLLOW` + `fsync` + 0600 + 路径收敛；F4（门 1 必带 `ignored_evidence`）
  与门 2 必带 `task_id`/`round_index`/`counts_as_effective` 都在写入与读取两侧强制。
- **执行者自报的三处修复确实存在**：每次尝试都归档（不再只留最后一条）、`Gate2Error` 计入 infra 并按
  `max_slot_attempts` 重试与总上限 12 收口、缺失二进制哈希 fail-closed 不再回填占位。
- **并发/生命周期**：capture 锁与 stub 锁不嵌套，无死锁面；账本 `max_runs = 60+12 = 72` 恰好等于
  最大尝试数（每次尝试非有效即 infra），不会出现"槽位耗尽早于 infra 上限"的隐性截断；
  成员请求穿插不影响 dump 分页拼接（dump 只来自 Root 的连续 `team_inspect`）。
- **无回归**：完整离线 `just eval-test` **865 项**，仅剩既有 2 项 Local 加载失败。
  `gate2-fake` 20 槽位、0 条件复跑、0 infra，十题裁决均为 `no_stable_one_way_degradation`（fake 数据）。

## 替用户做出的决策

| # | 事项 | 决策 | 理由 |
|---|---|---|---|
| G1 | 是否现在给付费授权 | **不给**。先修 P1 并复验：改模板、重算 sha，然后以**模板一致**的步骤序列重跑彩排并全绿 | 不修就是拿钱去撞一个已知必败的合同缺陷 |
| G2 | 彩排与模板的关系 | 立为常规：**stub 的步骤序列必须与冻结模板一致**；两者分叉时彩排不作为付费运行的证据 | 本轮的教训正是分叉处恰好决定谓词 |
| G3 | 本批其余交付物 | **照单认可**，不返工：设计、边界、预算组件、归档、就绪自检、门 2 交错骨架均达标 | 已逐项复核，质量高于要求 |
| G4 | P2 四项 | 不在本轮修，**并入 F3 付费前复审清单**，与付费执行器一起交付和审查 | 它们属于尚未实现的付费执行面，现在改无处验证 |
| G5 | 单次运行预算上限 | F3 复审时按实测 token 收紧（建议不超过预期最坏单次的小倍数），总额 $120 不变 | $40 太松，跑飞时兜不住；但总额有界，不急于本轮 |
| G6 | 付费锁 | **维持锁定**：真实 API、付费、Docker 仍需用户单独授权；阶段 B 继续只做离线工作 | 用户明确要求，且 WBS §6 授权门本就如此 |

## 验收判定

- **做得对不对**：**不通过**。五项交付物本身正确，但冻结模板与门 1 判据不自洽，
  且该缺陷已被实测证明会让合规的付费运行必败。属必须先修的窄缺陷。
- **是否实现预期**：**部分达成**。离线前置设施、彩排链路与就绪自检都达成了；
  但本轮的目标是"停在付费门前、一切就绪"，在模板修好并以模板一致序列复跑绿之前，
  **"一切就绪"尚不成立**。
- 执行者对范围、未完成项与彩排性质（"不是门 1 通过"）的自述属实，文档口径诚实，没有拔高。
