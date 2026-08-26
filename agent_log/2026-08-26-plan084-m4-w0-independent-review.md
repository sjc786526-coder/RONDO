# Plan 084 / M4-W0 独立验收报告

## 结论

本轮验收不通过，`BINDING_ONLY_GO` 暂不接受；任务目标尚未完成。实现范围、test-only 边界、Git fixture、handoff 分责和已保存的
8/8 正式门禁证据整体合理，但仍有两个会直接违反 ExecPlan 权限/隔离硬约束的 P2 correctness finding，以及一组会影响价值门证据强度的
聚焦缺口。无需扩建 registry、审计或可信设施；在现有 W0 原型内窄修、补最小回归并重新跑同一聚焦门禁即可。

## Findings

### P2：首次 binding 在授权检查前读取目标路径和 Git

`BoundWriterRuntime::bind` 先调用 `WriterWorkspaceBinding::capture`，后者会 canonicalize 目标并执行多条系统 Git 读取；直到随后的
`reload` 才执行 `ensure_pre_authorized`。因此一个不在调用者 workspace roots 内的目标会先被访问，再以 roots 不兼容拒绝。现有
roots mismatch 测试先在授权上下文中手工 capture，再更换 caller，未覆盖真实 `bind` 顺序。

这与“binding 不扩大调用者既有 workspace/Git/宿主访问权限”的硬约束不一致。应让初次 binding 在任何目标 Git 读取前完成不依赖目标
内容的调用者授权检查，并补一个能观察拒绝顺序的回归；具体内部 API 形状由执行者自行选择。

### P2：实际 fake action 目标未受 bound root 与 permission 约束

`BoundWriterRuntime::run` 重验 binding 后直接调用 `FakeWriterAction::execute`；后者用 `config.cwd.join(relative_path)` 后裸
`fs::write`。权限检查只验证固定的 `writer-output.txt` probe，并没有验证实际输出目标。于是 binding 到 writer A 的 action 仍可用
`../writer-b/marker.txt` 改写 writer B；绝对路径、父目录或符号链接形状也可能越过 effective workspace root。

这会直接反驳“workspace roots、permission/sandbox 共同生效”和“writer 不污染另一 writer”的原型证据。应对实际 action 目标应用
既有 filesystem policy 与明确的 bound-root 约束，在写入前 fail-closed，并补跨 writer/越界写入不产生副作用的回归。可以复用现有路径
校验设施或采用等强的更简洁实现，不要求为 W0 新建通用 sandbox。

### P2：价值门直接证据还需最小闭合

- cold reload 用例只 drop 旧 runtime 后原样 reload；即使实现未在 reload 阶段重读 Git，该场景也会通过。应在 capture 与 reload 之间让
  worktree 缺失或 Git identity 改变，并断言 reload 本身拒绝且没有 writer 动作。
- “每种失效只影响对应 writer”的直接隔离证据目前只在 worktree missing 场景出现。无需做场景笛卡尔积，但 repository、权限/roots、
  execution-context 代表性失败应各能证明另一已绑定 writer 仍可执行，或以等强的聚焦测试闭合这一合同。
- baseline 的 cooperative caller 场景和 caller-relative 漂移本身有价值，但当前 baseline 直接调用不消费 `intended_worktree` 的 helper，
  没有把合理自然语言目标与当时可得 Git facts 显式纳入对照。应明确表达同一任务意图、Git 观察与 fake 工具动作：既承认调用者已在目标
  workspace 时现有流程可用，也证明上下文漂移时现有产品没有结构性保证；不得把 deterministic fake 表述成真实模型遵循率统计。

这些都是对已有五个 W0 场景的窄补强，不要求真实模型/API、跨进程产品持久化或新的 structured handoff。现有 handoff 场景已证明路径说明
加 branch/HEAD/status/diff 能定位双方 tracked 未提交成果，本轮未发现支持 `BINDING_HANDOFF_GO` 的独立缺口。

## 已核对证据与边界

- 审查范围为 `ef16e8c4a833e0e353c7c3a40da9ce615983be81..fbb5332d4cd1e766c50a76e395a9cf0d3828452f`；
  worktree 在审查写报告前 clean，写集未实施 W1，也未触碰 Plan 082 内容。
- 保存的 JUnit `9b80362c-1181-4a45-8fe9-2ed2a43cedda` 确为 8 tests、0 failures；watchdog 为 `run_rc=0`、
  `final_rc=0`、`stop_reason=none`、`cleanup_reason=none`。本轮复用该正式证据，未重跑重型 Cargo。
- 文档候选状态、M4-Z(core) 既有结论、W1 未立项、deterministic/fake/offline 与真实本地系统 Git 的证据分类均正确。
- 最终收口时可把 WBS 价值门定义中的“跨进程重验”收窄为“reload/resume 重验”；W0 没有生产跨进程持久保证。该项为文案精度，
  不单独阻断。

## 复验与决策

执行者可自主选择最契合现有架构的窄修路线。完成上述 correctness 与直接证据闭合后，从全新 `TempDir` 重跑 W0 五项场景及相邻
spawn/resume/reload 聚焦回归，并运行范围内 fix/fmt；不扩大到 full workspace、Docker、真实模型/API、训练或性能测评。若修复后的同口径
证据仍支持 binding 且未出现 handoff 独有失败，继续提交 `BINDING_ONLY_GO` 是合理决策；无需因本轮 finding 改成 handoff GO，也不要预先
扩建 W1 能力。
