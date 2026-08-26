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
