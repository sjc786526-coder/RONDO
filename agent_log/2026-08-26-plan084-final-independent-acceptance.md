# Plan 084 / M4-W0 最终独立验收

## 结论

验收通过，任务目标完成，最终唯一终态为 `BINDING_ONLY_GO`。首次独立验收报告中的两个 P2 与三项直接证据缺口均已闭合；未发现
新的 correctness/functionality finding。Binding 具有值得进入正式 W1 的独立产品价值，现有合理自然语言说明与 Git
branch/HEAD/status/diff 已足以交接，本任务没有证据支持新增 minimal structured handoff。

## 整改复验

- 初次 `bind` 在 canonicalize 或系统 Git 读取目标前，先以调用者有效 workspace roots 与写策略完成纯 admission；未授权且不存在的
  目标直接返回 roots 不兼容，未先探测其内容。
- bound action 对 actual target 而非固定 probe 应用现有 filesystem policy，只接受普通相对组件，并在授权根内逐组件以 no-follow
  metadata 拒绝 symlink。父目录、绝对路径和 symlink 跨 writer 反例均在写入前拒绝，另一 writer 的 marker 保持不变。
- cold reload 在旧 runtime 丢弃后遇到暂时缺失的原 worktree，由 reload 本身拒绝且没有 action；恢复 worktree 后重新核对成功。
  repository、首次 admission、permission、roots 与 execution-context 失败后均直接证明另一已绑定 writer 继续可用。
- baseline 显式包含合理任务文本、动作前 branch/HEAD/status/diff 与同一 fake action；正确 caller context 下现有流程可用，caller-relative
  漂移时缺少结构保证。证据只判断控制面结构，不声称 deterministic fake 测得真实模型自然语言遵循率。
- replacement 与 handoff 场景保持原职责：失败 replacement 不覆盖旧 binding，成功 replacement 不隐藏或改写旧成果；现有 Git
  事实与路径说明可分别定位两侧成果，未形成 structured handoff 专属失败。

## 证据与边界

- 复验增量：`17fb9d751b9745b8217cce3543cc18f5aad90b3a..c1870836cb3cc829d5055ffe77b042a500df18b0`；
  `git diff --check` 通过，复验前 worktree clean。
- 保存的正式 JUnit `de36d02e-b180-49a1-b271-0b0e9de3b80b` 为 8 tests、0 failures；watchdog
  `.codex/build-watchdog/20260826-031241-1000-2470703` 为 `run_rc=0`、`final_rc=0`、`stop_reason=none`、
  `cleanup_reason=none`，资源峰值低于任务门限。scoped fix/fmt 已通过且没有额外代码修写。
- 本轮以代码、fixture、JUnit/watchdog 和文档一致性完成复验，没有重跑重型 Cargo；未运行 full workspace、Docker、真实模型/API、
  训练、性能测评、CI/PR 或远端操作。
- 原型全部受 `cfg(test)` 隔离，shared workspace 默认行为不变；未实施 M4-W1、上游适配、workspace 生命周期或 structured handoff，
  未读取或操作 Plan 082 私有现场。

## 替用户作出的决策

- 接受 `BINDING_ONLY_GO`，不改判 `BINDING_HANDOFF_GO`：现有 handoff baseline 已闭合，没有为代码量扩建第二套交接能力的依据。
- 接受 W0 的相称文件约束证据；生产级 race-free 文件锚定、持久 binding 与正式 API 留给未来 M4-W1，不在 test-only 价值门中继续扩张。
- M4-W1 与任何上游窄适配均不在本任务自动启动。后续应先按 W1 的实际消费决定是否及如何适配相关上游增量，再另行立项实施。
