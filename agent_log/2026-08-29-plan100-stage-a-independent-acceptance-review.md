# Plan 100 阶段 A 独立验收审查

## 结论

`STAGE_A_REJECTED_REMEDIATION_REQUIRED / STAGE_B_REMAINS_LOCKED`

阶段 A 的主体实现方向成立：Rust 三臂/provider 接缝、strict parser、本地 C gate、v10 validation-only 投影、周末谷价修复、route residual、基础
write-once/恢复与 B1 结果对象均有实质实现，执行者报告的工作树/无外部动作边界也成立。本轮独立复跑 Plan 100 Python unittest 为 15/15 通过，三项只读专项
审查没有发现 Rust High/Medium。

但真实付费入口仍能绕过成功 B1/冻结源码，20 RMB 与 formal authority 还不是唯一 task-wide 闭环，formal transient technical receipt 也无法按合同只补
未完成项。这些问题会在 B1/B2 真实执行时导致未 commissioning 的 formal、预算重置/authority 后继续消费或无谓整轮重跑，属于付费前 correctness
阻塞。因此阶段 A 本轮验收不通过，不批准进入阶段 B；以下窄整改继续属于已授权的阶段 A 非付费范围。

## 阻塞项

### High 1：`run-formal` 未重新验证成功 B1 与实际冻结源码

- `validate_freeze()` 对 formal 只要求一个合法形状的 `commissioning_binding_sha256`；实际 9/9 strict success、usage recount 校准和 B1/B2 identity
  比较只在 `prepare-freeze` 路径发生。
- `run-formal` 不接收/读取 commissioning binding，也不再次调用 `validate_commissioning_binding()`；当前测试甚至用任意 64 位 binding hash 直接运行
  81-row fake formal，说明 provider-capable 入口本身没有硬门。
- 运行入口只复核 executable、descriptor、recounter，未确认当前 worktree 仍 clean、HEAD 等于 freeze 的 git commit、diagnostic contract 和
  environment lock 仍与 freeze 一致。冻结后修改 Python runner 或合同仍可沿用旧 freeze 执行。

最小整改：B2 provider-capable 入口必须取得实际 commissioning binding，校验文件 hash、完整 9/9/calibration 结果及 B1/B2 identity；B1/B2 运行时都
重新验证当前 clean commit 与 contract/environment/executable/descriptor/recounter identity。纯函数 fake 单测可继续绕过真实入口，但实际 CLI 不可绕过。

### High 2：20 RMB 与 authority 尚未形成唯一 task-wide 闭环

- CLI 接受任意绝对 `runs_root`，只要求 ledger 是其 sibling；换一个路径即可创建第二份 20 RMB ledger。freeze/B1 binding 没有证明 commissioning、
  formal、retry、恢复和技术 clean rerun 使用主物理根唯一 Plan 100 namespace。
- 同一路径下形成 formal authority 后，commissioning mode 仍可创建新 run、reserve 并调用 provider；“首个有效 formal 后停止新增 API 消费”没有覆盖
  全任务。
- `recompute` 用会自动创建/加锁的 ledger constructor，不是严格 existing/read-only；也不按 authority 中的 freeze/result hash 验证复算结果。ledger
  丢失、重置或 authority 后漂移时可能输出另一份“复算结果”。

最小整改：从 Git common/main physical root 派生并验证唯一
`eval-data/publication-critic/plan100/{runs,budget-ledger.json}`，或采用等强固定 task-root 方案；B1 首次创建账本，B2/recompute 必须复用已有账本，
formal 准入还须证明当前账本包含 binding 中已经结算的 B1 记录。authority 存在后所有 provider-capable mode 均 fail closed；recompute 只读打开既有账本，
并验证 authority 的 run/freeze/result hash。无需建设第二套账本、签名、事务或通用审计设施。

### High 3：formal technical receipt 无法只补未完成 logical item

- 首次 typed technical failure 会写 receipt、结算并停止，这是正确的；但同一 namespace 恢复时一看到该 technical receipt 就再次停止，永远不会创建下一
  ordinal attempt。
- 结果只能放弃此前已验证 terminals 并 clean rerun 整轮，违反“技术中断保留有效进度、只补未完成项”；普通 provider transient failure 不应自动等同
  实现/基础设施使整轮无效。

最小整改：parse/output-contract failure 继续作为不可重试的正式质量 terminal；无 terminal 的已结算 typed technical receipt 在下一次显式 resume 时，
只允许同 freeze、同 logical item 追加下一 ordinal attempt，已完成 terminals 零重放。无 receipt 的 ambiguous reservation 继续 fail closed；明确属于
整轮实现/基础设施无效的情况仍走新 clean namespace。

## Medium

1. **无 response 的 usage-missing attempt 不能被错误当作可精确 recount。** 当前 recounter 接口允许在 `response_text = None` 时返回
   `completion_tokens = 0` 并按 token 小额结算；对 transport/重试失败而言输出 token 与是否计费仍不确定，应按合同进入 0.1 RMB fallback，除非 provider
   usage、完整 response 或明确 unbilled 证据使金额可确定。可在 `_settlement_attempts` 做窄约束并补一正一负回归。
2. **正式详细质量报告出口尚不完整。** raw metrics 已含 candidate errors、逐 pair rows 和 A curve，但现有 tracked projection 丢弃 candidate 级错误与
   pair rows，也没有明确的 bounded final-report projection。阶段 B 前需保证独立复算能产出用户要求的 A/B/C candidate 错误切片、12 pair 结果、A 完整
   curve 与 C target closure/non-target invariance；可保留现有 aggregate summary，并另加一个不含 packet/response/credential 的小型详细报告出口，
   不需要通用报告平台。

## 非阻塞核验

- v10 loader 只打开精确 manifest、validation candidates/pairs；provider 输入由 canonical public packet bytes 重建，local labels/pairs 未进入 evaluator。
- A/B/C schema、Rust/Python 双层 parser、C non-compensating AND、model echo、usage/attempt timestamp 与 parse failure terminal 语义成立。
- B1 结果与 binding 校验函数本身要求 9/9 strict success、至少一项 usage-present 且对应 recount 全部匹配；正式入口复核仍由 High 1 要求闭合。
- residual mapping 保留原 metrics 并显式标记；北京时间周一至周五峰窗、周末全天 off-peak 的代码/contract/边界测试一致。
- Rust 专项审查只有注释漂移 Low，不要求本轮为此改 Rust或重跑 68 项 Rust 门禁。
- 本轮命令：`PYTHONPATH=eval python -m unittest -v eval.tests.test_publication_critic_plan100_structured_diagnostic`，15/15 通过；未运行 Rust、Docker、
  API、模型、GPU、RunPod 或其它重型测试，未读取 qualification、v9 test 或其它 unseen 正文。

## 状态与再次验收条件

- 验收：`不通过`
- 阶段 A 任务目标：`本轮失败，可在既有授权内整改后再次验收`
- 阶段 B：`LOCKED / NOT_AUTHORIZED_TO_START`
- Plan 100 总任务：`IN_PROGRESS / NO_QUALITY_CONCLUSION`
- 执行者完成上述窄整改、补相称 Python 回归、更新合同/日志/ExecPlan 当前状态并提交 clean worktree 后，再通过既定 queue 申请阶段 A 复验；若未改 Rust，
  不要求重复 Rust 测试。
