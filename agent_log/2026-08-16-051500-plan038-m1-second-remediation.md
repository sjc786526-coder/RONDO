# Plan 038 / Multi M-1 第二轮审查整改

日期：2026-08-16 ｜ 工作树：`.claude/worktrees/039-multi-m1-team-world-state` ｜ 被复验提交：`5ce7e4c`
｜ 复验报告：`agent_log/2026-08-16-045257-plan038-m1-remediation-revalidation.md`

## 结论先说

复验报告的 5 项缺口**逐条核对后全部属实**，已全部修复。其中第 5 项（`team_history` 产品测试假阳性）
是我自己上一轮引入的：断言在整个 request JSON 上搜字符串，而那段文字早就随最初的 `team_publish`
参数进了 history，所以工具即使什么都没返回，断言也会通过。这类测试比没有测试更糟。

## 逐项修复

### 1. 整次请求预算（阻断）— 接受裁决，撤回决策 015

**确认两点都成立**：一是最小通告被允许超预算，那不是 hard cap；二是更根本的问题 —— 预算输入用的是
`context_window_token_status`，它基于 Session 缓存的 provider usage，本轮刚写入的 user/tool output 与
即将组装的实际 prompt 都没计入，所以"计入整次请求"这句话当时并不成立。

**修复**：
- **预算改为按实际待发请求计算**。渲染时机从"retry 循环之外"移到"第一次尝试内、`build_prompt` 之前"，
  用真正要发出去的 `prompt_input` 加 base instructions 估算余量：
  `remaining = context_window - instructions - prompt_input`。渲染结果随后被后续 retry 复用，
  所以"同一逻辑采样同一份快照"仍然成立，同时预算终于对着真实内容算。
- **取消一切预算例外**。`render_active_world_index` 返回 `ProjectionOutcome`：`Idle` / `Rendered` /
  `NoRoom`。硬边界无条件成立 —— 要么返回的东西装得下，要么什么都不返回。
- **`NoRoom` 时由调用层去腾地方**。`core/src/team/projection.rs` 调
  `session.request_new_context_window()`，turn 循环在下一步走已有 compaction，再按新 prompt 重新计算。
  这正是报告建议的路线，也终于让"近窗口时先 compaction"成为代码里真实发生的事，而不是注释里的说法。

**这里我多做了一步**：改成硬边界后，新集成用例立刻暴露出一个我原方案没想到的后果 —— 极紧预算下投影
会把**所有 Event 连同其 ID 一起**削掉，只剩一句"有活动事项但放不下"。那样"可通过有界历史查询下钻"
在产品上是断的：模型拿不到 Event ID 就没法调 `team_history`。所以削减顺序改成先削尽 Version、**保留
Event 标题行**，只有连标题行都放不下才整条丢弃。一行标题比一条完整 Version 便宜得多，却带着下钻所需
的标识符。集成用例现在显式断言被压缩的投影里仍有 `evt-` ID。

### 2. 同批重复 target 绕过终态（阻断）

**确认**：验证阶段全部 target 都对着批次前的旧状态检查，写入阶段再顺序应用。
`[V: expect(open,pending)->resolved, V: expect(open,pending)->tracking]` 两项都能通过旧 pending 的校验，
顺序写完变成 tracking，刚加的终态检查被完整绕过。

**修复**：同一批内拒绝对同一 Version 的同一生命周期轴重复下手，返回 `ConflictingTargets`。producer 与
root 是两条独立轴，同批分别修改仍然合法，并有用例守住这一点。

### 3. retry 指纹可静默合并不同请求（阻断）

**确认**：`handoff=None` 与 `Some("")` 经 `unwrap_or_default()` 后拼出同一字符串；字段内含 U+001E 时
也能跨字段构造碰撞。

**修复**：不再拼字符串，直接保存并结构化比较 `PublishRequest`（本就 `derive(Eq)`）。判断"是不是同一次
提交"因此是精确的，而不是取决于某种编码 —— 任何对模型可控文本的编码都可能被构造出碰撞。
补了"空 handoff 不等于没有 handoff"的用例。

### 4. 陈旧终态 mutation 未返回最新状态（阻断）

**确认**：终态检查排在通用 expected-state 检查之前，携带陈旧 expected 的调用会先撞上
`VersionClosed` / `RootAttentionResolved`，拿不到 `LifecycleConflict { current }`。

**修复**：校验顺序改为 **谁有权 → 你的认知是否还成立（不成立就返回当前完整快照）→ 这个转换是否合法**。
陈旧调用现在一律先拿到最新的 producer/root 双状态。加了一条用例：一个 Version 被 Root resolved、
又被作者 closed 之后，两个方向的陈旧调用都收到完整当前快照。

### 5. `team_history` 产品测试假阳性（阻断）

**确认**：断言把整个 request JSON 转字符串后搜 `orders.legacy_total`，而该文本早已随最初的
`team_publish` function-call arguments 进入同一 request。工具返回空也能过。

**修复**：改为精确读取 `history-1` / `history-2` 的 `function_call_output` 正文再断言；并按建议让真实
handler 走一次 `next_before -> before` 往回翻页 —— 第一页故意只要 1 条，必须拿游标才能取到另一条。

## 关于"整次请求不越界"的诚实说明

我先写了一条"整个 request 估算不超过 window"的断言，但它**测错了东西**：用 `item.to_string().len()/4`
会把 JSON 包装、转义、id 与 metadata 全算进去，结果在 10k window 下报 ~11.5k，与投影无关。
真实的内部估算只算 model-visible 字节。要在集成测试里忠实复刻那个估算等于把内部实现抄一遍，很脆。
所以改成断言**投影自身占比**：10k window 下投影必须小于 window/5。这条能证明预算规则确实按余量收缩、
没有膨胀成"团队有多少就带多少"，但**不等于证明了整个 request 一定不越界** —— 后者由
`remaining = window - instructions - prompt_input` 的算法本身与 `NoRoom -> compaction` 路径保证，
如实记录在此，不夸大。

## 测试结果

全部经共享构建锁与看门狗，未直接调用 cargo，代理变量已剥离。

| 命令 | 结果 |
|---|---|
| `just test -p codex-team-state -p codex-features` | **80/80 通过**（team-state 47，本轮 +4） |
| `just test -p codex-core -E 'team_world_state + only_verifiable_sessions'` | **7/7 通过** |
| `just test -p codex-core -p codex-rmcp-client` | 3541 跑，**3456 通过**，85 失败，13 skip |
| `just fmt` / `fmt-check` / `just fix -p codex-core -p codex-team-state` | 通过，fix 无改动 |
| `git diff --check` | 干净 |

85 个失败与**首轮基线逐条比对，集合完全一致**（`comm` 双向差集为空）。按复验报告口径，这可作为
"本轮无新增宽门禁失败"的证据，但其环境根因仍不宣称已独立证实。

**一次未复现的 flaky**：某次 `-p codex-team-state -p codex-features` 合并运行中 nextest 报了 1 个 flaky
（重试后通过，未记录具体用例名）。随后单独与合并共 12 次重跑均为全绿，没能复现，因此无法定位。
嫌疑最大的是 handle 层三个带 wall-clock 超时的唤醒用例，但它们的预算相当宽松（正向 5s、负向 200ms），
且负向用例在负载下只会更容易通过。**如实记录为"观察到一次、未复现、未定位"，不宣称已排除。**

## 未验证项（不阻断）

- `BUILD.bazel` / `MODULE.bazel.lock`：当前环境未安装 Bazel，按用户与复验决策记为未验证、非阻断；
  两个文件均无变化。
- 未跑全 workspace；未使用 Docker、真实 API、真实本地模型、付费测评。
- `wait_agent_enabled` 保持独立开关，未并入 team-state gate；M-1 产品链验收配置同时启用 wait，
  主纵切用例已按此覆盖。

## 顶层文档

L6 仍有未合并提交且改动 `doc/WBS.md` 与 `doc/WBS-COMPLETED.md`，继续不动这两份共享文档。
M-1 子 WBS 保持"已按独立审查整改，待复验"，不冒充验收通过。
