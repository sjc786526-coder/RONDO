# Plan 084 / M4-W0 Writer Workspace Binding 执行日志

## 实质修改

- 在 `codex-core` AgentControl 邻接处增加仅由 `cfg(test)` 编译的 W0 原型；它以不可变 Git worktree identity、当前调用者预授权
  workspace roots、有效写权限和执行环境建立 binding，并在 cold reload、每次 fake action 与 replacement 前重新验证。
- 增加 task-owned 临时 Git repository 与两个 linked worktree 的 deterministic fixture。baseline 与 candidate 使用相同 fake writer
  action；覆盖首次动作、cold reload、worktree 缺失、同路径换库、权限/roots/执行环境失配、失效隔离及事务式 replacement。
- 原型未增加产品 API、配置、schema、持久状态、feature gate、workspace 生命周期或 structured handoff。

## 价值门结论

唯一执行者候选为 `BINDING_ONLY_GO`，待指定审查者接受。公平 baseline 证明 initiating turn 已正确位于目标 worktree 时现有流程可用，
也复现了 caller-relative cwd 漂移时两个同名动作落到父 cwd 并碰撞；candidate 则把两个首次动作稳定约束到各自 worktree。cold reload
从不可变 binding 与当前授权重建，失效 writer 不影响另一 writer，失败 replacement 不覆盖旧 binding。

换绑前后的路径说明加真实 Git branch、HEAD、status 与 diff 已能分别定位未提交成果；没有出现 minimal structured handoff 独有且可重复
闭合的失败，因此不支持 `BINDING_HANDOFF_GO`。这是 test-only 可行性和产品价值证据，不是生产 trust/binding 保证，也未实施 M4-W1。

## 验证与资源

- 调试期首次编译暴露三处测试 `Debug` 约束，下一轮 5 项中 4/5 暴露 replacement fixture 预期错误；均窄修后达到 5/5。首次 wrapper
  在受限 sandbox 内因无法核对用户级 systemd scope 于 payload 前 fail-closed，随后仅为 canonical wrapper 的 cgroup/资源计数使用已授权
  宿主访问；没有绕过共享锁或看门狗。
- 独立只读复核无阻断 finding；其唯一低严重度建议是首次 fixture commit 显式关闭宿主 Git signing，窄修后从全新 `TempDir` 运行正式轮：
  `CARGO_TARGET_DIR=/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target CARGO_BUILD_JOBS=1 RONDO_BUILD_PROJECT_WARN_BYTES=270000000000 RONDO_BUILD_PROJECT_STOP_BYTES=285000000000 RONDO_BUILD_PROJECT_MAX_BYTES=290000000000 UV_CACHE_DIR=.uv-cache just -f multidev/justfile test -p codex-core --lib -E 'test(workspace_binding_w0) | test(build_agent_spawn_config_uses_turn_context_values) | test(build_agent_resume_config_clears_base_instructions) | test(ensure_v2_agent_loaded_reloads_registered_unloaded_agent)'`。Nextest
  `9b80362c-1181-4a45-8fe9-2ed2a43cedda`，8/8 通过、2290 skipped；watchdog
  `.codex/build-watchdog/20260826-024807-1000-2413029`，`stop=none`、`cleanup=none`。
- `just -f multidev/justfile fix -p codex-core` 通过，仅移除测试中的一次无必要 `Config` clone；随后 `just -f multidev/justfile fmt`
  通过。依就近规则未在 fix/format 后重跑测试；该机械所有权移动不改变正式链行为。
- 首批前：项目 `251389988864` B，069 target `188302737408` B，deps `152793751552` B，incremental `34694021120` B，
  Windows `C:` 实际余量 `75320213504` B。最终 fix 后：项目 `254426632192` B，target `191334596608` B，deps
  `152785104896` B，incremental `37817475072` B，`C:` 余量 `75229712384` B。各批均使用共享锁、069 target、单 job 与命令级
  270/285/290GB 门限；Plan 082 大型下载进程在批次前空闲，未操作其任务或资产，容量趋势无需清理 069 target。

全部证据为 deterministic/fake/offline，加任务自有 fixture 中的真实系统 Git；未运行 Docker、真实模型/API、训练、性能测评、CI 或远端操作。

## 首次独立验收整改

- 审查报告 `17fb9d7...` 的两个 P2 均确认存在：initial bind 在 roots/permission admission 前读取目标 Git，actual fake action 只验证固定
  probe 后裸写相对路径。整改把 admission 提前到任何目标读取之前；bound action 只接受普通相对组件，按 actual target 检查现有
  filesystem policy，并在授权根内逐组件使用 no-follow metadata 拒绝 symlink。父目录、绝对路径和 symlink 跨 writer 写入均在副作用前拒绝。
- cold reload 现在在丢弃旧 runtime 后先以暂时缺失的原 worktree 证明 reload 本身拒绝且没有 action，再恢复并证明重验后可用。
  repository、permission、roots、execution-context 与首次 admission 失败后均直接证明另一已绑定 writer 可继续执行。
- 公平 baseline 现在把合理自然语言任务、预动作 branch/HEAD/status/diff 和同一 fake action 显式组成对照：正确 caller context 下成功，
  caller-relative 漂移下仍无结构保证；结论不表述为真实模型遵循率。
- 调试整改轮 Nextest `4c1c0d3d-dced-4cb9-b452-582690836c6a` 为 8/8。冻结代码后以原精确命令从全新 `TempDir` 运行正式轮，
  Nextest `de36d02e-b180-49a1-b271-0b0e9de3b80b` 为 8/8、2290 skipped；watchdog
  `.codex/build-watchdog/20260826-031241-1000-2470703`，`stop=none`、`cleanup=none`。随后 scoped fix/fmt 通过且未产生额外代码修写，
  依就近规则未再重跑测试。
- 整改首批前：项目 `254427115520` B，069 target `191334600704` B，deps `152785104896` B，incremental `37817479168` B，
  Windows `C:` 实际余量 `75174096896` B。最终 fix 后：项目 `254524301312` B，target `191431712768` B，deps
  `152785145856` B，incremental `37914550272` B，`C:` 余量 `75172151296` B。各批继续使用共享锁、单 job 与命令级
  270/285/290GB 门限；Plan 082 大型下载进程空闲，未操作其任务或资产，未触发 cleanup。

整改未产生 structured handoff 独有缺口，唯一执行者候选仍为 `BINDING_ONLY_GO`，待指定审查者复验；生产级 race-free 文件锚定仍明确
属于 W1 设计问题，不由 W0 test-only 原型冒充。
