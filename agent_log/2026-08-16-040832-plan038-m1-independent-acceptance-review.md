# Plan 038 / Multi M-1 独立验收审查

## 审查对象与结论

- 对象：`worktree-039-multi-m1-team-world-state` 的提交 `f974af0062535c2907e32360120ef4105e36b95e`，基线为计划提交 `d515b09`。
- 范围：按 `doc/WBS/multi-agent-trusted-evidence.md` 与
  `plan/038-multi-m1-team-world-state-execplan.md` 审查 M-1 的领域语义、真实产品接缝、测试和交付状态；不扩大到
  M-2 及后续能力，也不新增审计或可信设施。
- **验收状态：不通过。**
- **任务目标：失败（当前提交尚未完整实现冻结的 M-1 完成标准）。** 主体架构和真实纵切已经成立，以下问题均可在
  现有设计内窄修复，不需要推倒重做。

## 已确认成立的部分

- `codex-team-state` 与 `codex-core` 分层合理；canonical store 挂在共享 `AgentControl`，authored 内容与双生命周期的
  存储边界、Mutex 下的检查/提交、counted wake 的主设计成立。
- `core/tests/suite/team_world_state.rs` 的主链路使用真实 Session、真实 V2 spawn/wait/sampling/tool 接缝；fake 只替代
  provider。Root 等待、child 发布、唤醒、下一采样投影、Root resolve、child 保留自身事项、追加 Version、Root 再获
  协调机会的纵切确实跑通。
- request-only 投影在 provider retry 循环外取快照，挂在正常输入末尾，并在返回前移除；retry 同快照、rollout/history
  不落盘、compaction 后重建、同一 Root 树内成员 reload 的主路径均有真实集成覆盖。
- 本次独立复跑通过：
  - `just test -p codex-team-state -p codex-features`：69/69。
  - `just test -p codex-core -E 'test(/team_world_state/)'`：5/5（3329 skipped）。
  - `UV_CACHE_DIR=/home/sjc/desktop/RONDO/.uv-cache just fmt-check`：通过。
  - `git diff --check d515b09..f974af0`：通过。
- 两组 Rust 测试都走仓库共享锁与 cgroup 看门狗；最后一次记录约为 project 73.68 GB、target 52.80 GB，未触发资源停止。
  未使用 Docker、真实 API、本地模型或外部付费能力。

## 阻断验收的正确性问题

### 1. 投影硬预算与近窗口语义没有真正闭合

- `team-state/src/render.rs:97-121` 只能删旧 Version 或整 Event；只剩一个 Event 的最新 Version 后，即使仍超过预算也
  `break` 并返回。`title` / `summary` / `handoff` 又没有长度上限，因此单条超长 authored 内容可突破 4k hard cap，
  甚至把请求顶到 `ContextWindowExceeded`。
- `team-state/src/render.rs:76-82` 在预算不足最小阈值时对非空活动视图直接返回 `None`；
  `core/src/team/projection.rs` 没有触发 compaction，也没有附加显式 omission。该次 sampling 因而完全看不到活动团队
  状态，正好违反“每次采样可见、超出显式省略、不得顶爆请求”。
- `render_tests.rs:96-122` 只覆盖多条短内容，并把“接近窗口时静默跳过全部投影”固化成了成功测试；没有 WBS 明确要求
  的单条超长内容和真实近窗口请求用例。

### 2. `team_history` 既非真正有界，也不能完整下钻

- `store.rs:440-458` 的列表模式只限制 Event 数量，却对每个 Event 返回完整 Version chain；单个 authored 字段也无输出
  上限，查询整体仍可无界。
- `HistoryQuery` 只有 `event_id + limit`，没有 cursor/offset/before。列表永远只给最新最多 50 个 Event，指定 Event 也
  永远只给最新最多 50 个 Version；更老内容没有后续查询路径。
- 因而投影所报的 omitted 历史在规模超过上限后可能永远取不回来，不满足“有界、按权限、可下钻”。现有测试只断言
  返回数量和 omitted count，没有证明能够翻页取回；真实 `team_history` tool 也没有覆盖“投影省略后下钻取回”的产品链。

### 3. Member 可通过 append 自行扩大权限

- `store.rs:193-202` 对 `ExistingEvent` 只校验引用存在，不校验 actor 已对该 Event 可见/有贡献资格；而
  `TeamEvent::is_readable_by` 会在 actor 成为任一 Version 的作者后开放整条 Event。
- Event ID 由当前实例 tag 和递增 ordinal 构成。已登记 member 可猜 sibling/root Event ID，先向无权读取的 Event 追加，
  再因成为作者读到完整 chain。这与同一 store 的 history 拒绝规则矛盾，也违反“可见性决定第一版贡献资格”。
- M-1 无需 ACL：Root 保持全队读写；member 只可向自己已可见/已贡献的 Event 追加；M-2 再通过 route 扩大可见性与贡献
  资格即可。当前跨 member 并发 append 测试不应固化越权，应改为有权作者并发并补一条 sibling 拒绝回归。

### 4. Root 的终态可被原地重开

- `store.rs:305-340` 对 `SetRootState` 只校验调用者是 Root 和前置状态相符，允许
  `resolved -> pending/tracking`。设计合同明确“已进入终态的 Version 不原地重开；重新相关时追加新 Version”。
- 当前 `a_closed_version_cannot_be_reopened_in_place` 只覆盖 producer `closed`，没有覆盖 Root `resolved`。这会让旧 Version
  被原地重新拉回活动视图，破坏追加式历史语义。

### 5. 产品身份边界仍有缺口

- `core/src/agent/control.rs:157-172` 在 `Session::new` 路径把所有 `Internal` 和所有 `SubAgent` source 自动登记为 member，
  缺 agent path 时还回退为 `/root`；它没有只接受可核验的 V2 `ThreadSpawn` registry 身份。领域层的
  `UnknownParticipant` 测试因此不能证明真实 Session 的“身份缺失 fail-closed”。Review/Compact/Internal 当前通常没有
  团队工具，降低了实际暴露面，但注册政策本身仍与完成标准不一致。
- `team-state/src/ids.rs:14-35` 的对外引用只携带 UUID 前 8 个 hex 字符（32 bit），不是完整团队实例身份。tag 碰撞时旧
  引用可能解析到新实例同 ordinal 对象，无法严格保证实例不匹配 fail-closed。无需引入可信设施，直接让引用携带足以
  唯一校验的实例身份即可。

## 其他需要在复验前窄修的事项

- 幂等表只保存 `(actor, request_id) -> outcome`，没有绑定原请求。相同 id 配不同 payload 会被静默报告 deduplicated，
  第二份真实内容丢失；应返回冲突而不是把不同请求当重试。
- team protocol/projection/wait 只检查嵌套 `team_state_enabled`，工具注册还受 MultiAgentV2/Collab 总开关约束；组合配置可
  出现“模型看到协议/投影但没有工具”。应共用一个 effective gate。
- 新增 Cargo 依赖后未执行 `multidev/AGENTS.md` 要求的 `just bazel-lock-update` / lock check。无需跑完整 Bazel，只需在
  修复提交前跑 lock 门禁并记录结果；若 lock 无变化，保持无变化即可。
- 执行日志中的 85 个宽门禁失败没有原始清单或 baseline，独立审查不能把“全部不是回归”当作已证实事实；其 V8 预编译
  404、缺 package 外 binary、网络依赖三类解释合理，因此本轮将其记为“环境归因、未确认”，不要求为此扩大到全 workspace
  重跑。

## 替用户作出的决策

1. **保留 `team_state_enabled = false` 默认值。** M-1 完成标准要求能力与真实纵切，不要求立即默认开启；当前先保留显式
   rollout gate，避免无关 Multi prompt/tool snapshot churn。
2. **采用最小权限政策。** Root 可读写全队；member 仅读写自己已可见/已贡献的 Event；M-2 route 再授予新增可见性和贡献
   资格。不建设 ACL、角色矩阵或审计系统。
3. **接受 4k cap / 2k headroom / 20% share 作为 M-1 暂定常量。** 本轮不测量调参、不配置化；只要求算法无条件执行 hard
   cap，并在省略/compaction 路径上显式可见。
4. **不要求补跑全 workspace、Docker、真实 API、本地模型或完整 Bazel。** 修复后只需领域/features 定向测试、M-1 真实纵切、
   fmt/fix、diff check 与 Bazel lock 门禁；新增覆盖应精准对应上述缺口。
5. **保持共享顶层 WBS 不动。** L6 仍并行修改共享文档；M-1 子 WBS 当前“实现完成，待独立审查”应在修复复验时改为准确的
   “修复中/待复验”或通过状态，不能现在冒充验收完成。工作树不得合并或推送。

## 交付状态

- 本次只新增本审查报告，没有修改实现、ExecPlan、WBS 或 L6 工作树。
- `main`、L6 分支未合并、未推送；`f974af0` 仍是被审查的实现提交。
- 建议执行者在原 M-1 工作树内做一轮聚焦修复并提交，然后按本报告的窄门禁复验；不需要新工作树或新设施。
