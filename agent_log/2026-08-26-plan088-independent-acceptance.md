# Plan 088 / #39153 独立验收

审查对象：`worktree-088-permission-restore-adaptation@57b7efbe12808b6e06089194ab6676b5a7e537e4`。

## 结论

验收通过，任务目标完成，接受 `M4_W_39153_ADAPTATION_PASS`。未发现未关闭的高/中等级 correctness 或 security finding；
本结论记录在 088 分支，仍等待用户批准整合本地 `main`。在进入 `main` 前，M4-W1 继续锁定且未立项；进入 `main` 后也只解锁
“另行规划 M4-W1”的资格，不自动启动实现。

## 独立审查

- canonical `TurnContext` 以 missing / explicit null / `Some(identity)` 表达 legacy、明确无 named profile 与明确持久 profile，普通
  turn 和 compaction 共用 writer；recent-settings 投影在最新 identity 边界停止，不从 concrete permission snapshot 推断 identity，
  也不复活更老 ID。
- cold resume 与顶层 fork 对 approval policy、approvals reviewer、active profile identity 采用分域的显式 override 优先级；
  loaded、legacy、paginated 与 boundary source 最终收敛到同一 merge/config 链。
- persisted identity 只作为当前 Config catalog、Plan 086 hardened project trust、profile inheritance、workspace roots、network 与
  requirements 的输入。missing/invalid/disallowed/incompatible profile 返回错误，不切换 configured/required default；合法显式
  permission override 会先清除 persisted 来源。
- cold resume 在 `thread_processor.rs:3355-3366` 的 config load 失败后、`3378-3387` 创建 runtime/thread 前返回；fork 在
  `4421-4426` 完成 config load 后才可能进入 `4470-4495` child 创建。不存在 invalid persisted profile 启动可执行 runtime、child、
  MCP/model/tool 链或使用默认权限继续成功的路径。
- 代码写集没有引入 M4-W1 binding/scoped authorization、第二套 permission/config/recovery 权威、registry、审计/可信平台或无关重构；
  普通 new/running thread 和 S/C 已完成链没有被改写。

## 验证证据

独立验收复核保存的 watchdog/JUnit，而没有重复运行重型门禁：

- protocol 三态 serde：run `20260826-075636-1000-3029848`，`1/1`，`final_rc=0`；
- app-server lib：run `20260826-080748-1000-3068099`，`279/279`，`final_rc=0`；
- core 当前重解析与 fail-closed：run `20260826-081120-1000-3078649`，`6/6`，`final_rc=0`；
- legacy/paginated resume/fork 正反集成：run `20260826-081144-1000-3079811`，`5/5`，`final_rc=0`；
- scoped fix：run `20260826-081415-1000-3089181`，`final_rc=0`；随后 fmt 通过。
- 验收后副作用顺序测试加固：提交 `ea99e979ec4189311d6319cc93a0d7dd526829b4`，run
  `20260826-084312-1000-3172734`，`1/1`，`final_rc=0`；随后 fmt 通过。

上述通过批次均为 `stop_reason=none`、`cleanup_reason=none`、swap peak `0`。通过批次最高项目采样为
`273,409,286,144 B`（约 `273.41GB`），低于本任务 `285GB` 主动停止线；调试失败轮的最高项目采样为
`274,184,130,560 B`，同样未触发停止或清理。scoped fix 内存峰值为 `6,263,377,920 B`，未触发 21/22GB 门。
`git diff --check` 通过。未运行完整 workspace、Docker、真实 API/模型、训练、测评、CI/PR 或远端操作，均未冒充通过。

## Finding 与代表用户作出的决定

- **无剩余 finding。** 首次验收记录的低等级测试保障余项已由 `ea99e979` 窄修闭合：既有 invalid-profile 场景现在比较拒绝前后
  `thread/list` 的完整 thread ID 集合，并确认消息缓冲没有 `thread/started`。独立复核确认该断言覆盖目标顺序，且没有新增 helper、
  生产逻辑或副作用审计设施。
- 接受 legacy/paginated 正向主链、recent-settings 单测、严格 config 反例与一条端到端 invalid/override 反例的分层组合；不扩成
  history mode × invalid variant × resume/fork 的重复笛卡尔矩阵。
- 接受不运行完整 workspace `just test`。实际共享写集已由 protocol、core、app-server lib 和端到端主链覆盖；扩大门禁与本任务风险
  不成比例。
- 修正实施日志的资源峰值口径；该记录误差不影响资源门、实现正确性或验收结论。验收后测试加固首轮两次均停在 initialize 基线，
  未触达新增断言；热目标复跑通过，不扩大到 app-server 全库或 workspace。
- 088 与并行 087 后续由获批的后整合者加法式保留彼此 WBS 状态。本次不读取或覆盖 087 未提交内容，不合并、不推送，也不启动 M4-W1。

最终状态：`ACCEPTED / TASK_GOAL_COMPLETE / M4_W_39153_ADAPTATION_PASS / PENDING_LOCAL_MAIN_INTEGRATION`。
