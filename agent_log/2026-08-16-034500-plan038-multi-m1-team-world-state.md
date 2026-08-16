# Plan 038 / Multi M-1：团队世界状态纵切

日期：2026-08-16 ｜ 工作树：`.claude/worktrees/039-multi-m1-team-world-state` ｜ 基线：`d515b09`

## 做了什么

在 `multidev/` 落地 RONDO Multi M-1：团队协作状态由 Harness 持有，不依赖模型记忆，不进入
conversation history 与 rollout，并且跨等待时序、采样重试、compaction 与成员卸载/重载保持正确。

### 新增领域 crate `codex-team-state`（`multidev/codex-rs/team-state/`）

不依赖 `codex-core`，只依赖 `codex-protocol` 与 token 估算工具，便于单独测试。

- `ids.rs`：`TeamInstanceId` / `EventId` / `VersionId` / `TeamRevision`。**每个对外引用都内嵌团队实例
  短标签**，所以上一个实例铸造的引用无法静默命中当前实例，只会得到显式的 `InstanceReset`。
- `model.rs`：`AuthoredVersion`（作者、summary、handoff、证据引用）为私有字段 + 只读 getter，
  store 只能改 `producer_state` / `root_state` 两个生命周期字段 —— "authored 内容不可改写"由类型
  可见性保证，而不是靠约定。活动视图谓词与历史可读性判定也在这里。
- `store.rs`：canonical 状态与全部不变量。同步实现，由 handle 用单个 mutex 包住，因此每次 mutation
  都在没有 await 的情况下先校验再提交。
- `wake.rs`：按参与者计数的唤醒账本（signalled / consumed），而不是发送一次性通知。
- `render.rs`：request-only Active World Index 渲染 + 预算与省略清单。
- `handle.rs`：`TeamStateHandle`，每个 Root 树一份，克隆给全部子 Agent。

### 接入真实产品运行面（`multidev/codex-rs/core/`）

- `AgentControl` 增加 `team: Arc<TeamStateHandle>`。`AgentControl` 本来就是"每个 Root 树创建一次、
  被所有子 Agent clone"，所以团队状态天然是每个存活 Root 树一份，且不随成员是否驻留而变化。
- `Session::new` 里从**权威身份**注册参与者：thread id + session source 决定 Root/Member 与标签，
  模型自报字段完全不参与。注册按 thread id 幂等，这同时就是"卸载后重载仍属原实例"的实现。
- `core/src/team/`：`TeamAccess::resolve` 做 fail-closed 能力解析；`capture_team_projection` 生成投影。
- `core/src/tools/handlers/team_tools/`：`team_publish` / `team_update` / `team_history` 三个工具。
  工具面不接受 author/producer/root 自报字段；幂等身份默认取 harness 自己的 tool `call_id`。
- 采样接入 `session/turn.rs`：**快照在 retry 循环之外捕获一次**，在循环内于
  `attach_pending_to_prompt` 之后、`build_prompt` 之前追加到 input 尾部 —— 这是历史规范化与
  tool call/result 配对都已完成之后的最后一个协议安全位置。返回给调用方的 input 会把投影截掉，
  所以它不会经由 hook 或任何下游路径进入 history/rollout。
- 等待接入 `multi_agents_v2/wait.rs`：`wait_agent` 在原有 mailbox 订阅之外并行 select 团队唤醒。
- 稳定协议前缀：`TeamProtocolState`（world-state section，版本化）+ `TeamProtocolInstructions`，
  随 initial context 落在指令前缀，compaction 会连同 initial context 一起重新注入。

### 配置

新增 `features.multi_agent_v2.team_state_enabled`，**默认关闭**，`config.schema.json` 已用
`just write-config-schema` 重新生成。默认关闭是为了不扰动既有 multi-agent 测试的工具面与 prompt；
M-1 的集成测试显式打开它跑真实链路。

## 疑难与取舍

- **唤醒不能只发瞬时通知**。V2 的 `wait_agent` 等的是调用者自己的 mailbox，而团队变化没有 mailbox
  投递（M-2 才有 route 通知）。因此团队唤醒做成"可消费的计数"而不是一次性信号：先订阅再检查，
  等待前发布与等待中发布都不丢；消费之后同一变化不再唤醒。
- **投影预算必须按整次请求算**。投影不进 history，history 侧的 token 估算不会替它兜底，所以预算由
  `context_window_token_status` 的剩余量推导，逼近窗口时先砍最老的 version、再砍整个 event，
  砍掉的东西列进省略清单并指向 `team_history`；余量太小时整个投影跳过，绝不把请求顶爆。
- **接受的取舍（沿用 WBS 已定结论）**：request-only 投影会让 WebSocket 的"严格扩展"增量复用基本失效。
  本轮按正确性优先，没有持久化旧投影、没有累积补丁、没有把 team revision 编进缓存键。
- **测试中发现并修掉一个真实缺陷**：最初的陈旧视图判定对"新开 Event"也成立，导致第一次发布就被标成
  `authored_on_stale_view`。已改为只有 append 才可能陈旧，并补了回归断言。
- **重载测试不靠运气**：把 residency 容量压到 1 个子 Agent，第二个 worker 只有在第一个被卸载后才可能
  启动；测试断言第二个 worker 确实跑过，所以"发生了真实卸载"是被证明的，不是假设的。
  写这个用例时踩到一个真实约束：容量为 1 时，重载 worker 必须先把 auditor 换出去，所以 auditor 也得
  先跑完；用例里 Root 因此多等一轮。这不是缺陷，是 residency 语义本身，记下来免得后续误判。

## 测试结果

全部通过共享构建锁（`scripts/with-build-lock.sh` 经 `just`），未直接调用 cargo。

| 命令 | 结果 |
|---|---|
| `just test -p codex-team-state -p codex-features` | 69/69 通过（team-state 36 + features 33） |
| `just test -p codex-core -E 'test(/team_world_state/)'` | 5/5 通过 |
| `just test -p codex-core -p codex-rmcp-client` | 3539 跑，3454 通过，85 失败，13 skip |
| `just fmt` / `just fmt-check` | 通过 |
| `just fix -p codex-core -p codex-team-state` | 无改动 |
| `just write-config-schema` | 仅新增 `team_state_enabled` 一项 |
| `git diff --check` | 干净 |

M-1 集成用例（真实 Session / 真实 spawn / 真实 V2 wait / 真实采样，仅 provider 用 wiremock 假造，
且假 provider 按它实际收到的投影内容决定下一步，所以断言的就是模型真会看到的东西）：

1. `root_and_child_share_one_canonical_team_state_across_wait_and_sampling` —— 完整链路：
   Root 派生子 Agent 并等待 → 子 Agent 发布 Event → Root 被唤醒并在下一次采样看到 `root=pending`
   的团队状态 → Root 标记 resolved → 该事项仍留在子 Agent 自己的活动视图（`root=resolved
   producer=open`）→ 子 Agent 追加新 Version → Root 再次获得协调机会并看到完整 2 条 Version chain。
   同时断言子 Agent 首次采样没有投影（空活动视图零成本）。
2. `the_projection_is_request_only_and_never_enters_history_or_rollout` —— 每次请求投影恰好出现
   一次且是最后一个 input item；rollout 文件中不含投影标签；相邻两次采样的 revision 递增
   （证明每次采样取新快照）。
3. `provider_retries_of_one_sampling_reuse_the_same_snapshot` —— 同一逻辑采样的失败尝试与重试
   携带逐字节相同的投影。
4. `compaction_rebuilds_the_projection_and_leaves_no_residue` —— 压缩摘要请求完全看不到投影；
   compaction 之后投影从 canonical 状态重建，内容仍在，仍在尾部；rollout 无残留。
5. `a_reloaded_member_keeps_its_team_instance_and_its_own_items` —— residency 容量压到 1，
   第二个 worker 启动证明第一个被真实卸载；重载后的 worker 仍看到自己写下的内容与 `producer=open`。

领域层 36 个单测覆盖：双生命周期独立、Root 自建 tracking 不自唤醒、普通参与者 pending 唤醒 Root、
已消费不重复唤醒、producer 关闭仅在 Root 仍欠注意力时唤醒、终态不可原地重开、只有作者能关闭 /
只有 Root 能改 root_state、增量与批量只动显式目标、幂等重试、陈旧追加被标记、陈旧生命周期变更被拒
并返回最新状态、并发追加与并发生命周期竞争、有界按权限历史、跨实例引用报 reset、未注册身份 fail-closed。

## 未运行 / 未验证（如实记录）

- `just test -p codex-core -p codex-rmcp-client` 的 85 个失败**全部是环境限制，不是本次回归**，
  分三类：(a) `code_mode::*`、`code_mode_elicitation::*`、`hooks` 中的 code-mode 用例、
  `responses_lite`、`agent_websocket` 的 responses-lite 用例 —— 需要 code-mode host，而
  `codex-code-mode-host` 依赖的 V8 预编译包在本机下载 404；(b) `cli_stream::*`、
  `multi_exec_server_sandbox` —— 需要 package 范围外的 `codex` / exec-server 二进制；
  (c) `realtime_conversation` 的连接失败用例与 `streamable_http_*` —— 依赖真实网络。
  我改动涉及的所有模块（team、world_state、spec_plan、session/turn、wait、compact、multi-agent）
  均未出现在失败清单中。**未做基线对比运行**，上述判断依据是每条失败的具体错误信息。
- 未跑全 workspace 测试；未跑 Bazel。新 crate 已按惯例添加 `BUILD.bazel`，但**未经 Bazel 验证**
  （bazel 需要网络）。`MODULE.bazel.lock` 未变化，因为只新增了 path 依赖、没有新外部依赖。
- 未使用 Docker、真实 API、真实本地模型、付费测评，均不在本任务授权内。
- 本机 shell 存在全局 `HTTP(S)_PROXY` / `ALL_PROXY`，会拦截 wiremock 的 loopback 请求导致集成测试
  假性超时。所有测试均在剥离代理变量的环境下运行（与仓库 `eval-*` 配方的既有做法一致）。

## 顶层文档同步

L6（`037-l6-first-lora-paired-artifacts`）有 12 个未合并提交，且修改了 `doc/WBS.md` 与
`doc/WBS-COMPLETED.md`。按 ExecPlan 决策 005，本次**不动这两份共享文档**，只更新 M-1 权威子 WBS
`doc/WBS/multi-agent-trusted-evidence.md`（L6 未触及该文件），顶层同步留给最终集成。
