# Plan 044 / M-5 阶段 B 第五轮整改验收审查

日期：2026-08-19  
分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`  
审查主范围：`3d9af92..5bdacc3`，并沿正式运行调用链复核相关既有接线  
结论：**FAIL**

## 总结

执行者对上一轮 9 项问题的主要整改方向是正确的：workflow / nondegradation v2 锁已建立，
Gate 1 改读冻结二进制 rollout trace，Gate 2 的 root/member 模型已传到实际 adapter，
token 信封也让正式 `$120` 账本的单请求结算不再越过预留。

但本轮仍发现 3 项 P0、2 项 P1 和 2 项 P2。它们会突破合同外冒烟的 `$40` 授权、
使两道正式门的归档身份失真、令 Gate 2 条件复跑无法启动，或在停止线已触发时错误通过 Gate 1。
因此当前不得运行合同外付费冒烟、正式 Gate 1 或正式 Gate 2。

## Findings

### [P0] 把 provider probe 真正纳入 `$40` 冒烟上限 — `eval/rondo_eval/multi_m5/__main__.py:136`

`smoke` 虽然先打开了 `$40` ledger，但随后调用的 `run_provider_probes()` 没有收到这份 ledger；
该函数会在自己的输出目录下另建一份 `PROBE_TOTAL_CAP_USD = $5` 的 Plan 013 ledger
（`eval/rondo_eval/provider_probe.py:154-160`）。而正式 smoke run 直到 probe 完成后才
`claim_run`。因此每换一个新 label，都可以先在 `$40` 账本之外再花最多 `$5`；即使 `$40`
账本已耗尽或 run slot 已满，新的 label 仍会先外发 probe，入口没有统一数学上限。

这正是上一轮 P1-6 要求“probe 纳入同一份持久 cap/receipt”但尚未实现的部分，属于真实授权突破。

### [P0] 归档实际钉死的 terra 成员身份 — `eval/rondo_eval/contracts.py:290`

本提交把机器级默认成员模型恢复为 sol，同时给
`team_capability_config_projection()` 增加了显式 `subagent_model` / `subagent_effort`
参数；但 `archive_record()` 及 Gate 1 / Gate 2 调用点仍未传这两个参数。
所以实际命令运行 terra，归档必填的 `team_capability_config.default_subagent_model`
却写成 sol。

离线复现：

```text
locked_member=gpt-5.6-terra
archived_member=gpt-5.6-sol
```

Gate 2 的 live row 还会在 `model_projection` 里写 terra，形成同一行内部互相矛盾；
Gate 1 则没有另一份字段替它纠正。这样的记录不能作为正式证据。

### [P0] Gate 2 记录必须使用 nondegradation v2 身份 — `eval/rondo_eval/multi_m5/gate2.py:983`

默认 loader 已固定读取 `multi-m5-nondegradation-v2`，但 `_record_for()` 仍把每一条
Gate 2 记录的 `lock_id` 硬编码为 `multi-m5-nondegradation-v1`。

离线复现：

```text
loaded_lock=multi-m5-nondegradation-v2
archived_lock=multi-m5-nondegradation-v1
```

因此即使真实运行完全成功，也只会产出声称受 v1 约束的记录；v1 又不包含本轮冻结的完整诊断、
usage envelope 与模型贯通合同。旧归档不得升级冒充 v2 的原则在 Gate 2 这里尚未落实。

### [P1] 为 Gate 2 每个 attempt / round 使用唯一 staging 身份 — `eval/rondo_eval/terminal_bench/runner.py:521`

Gate 2 的 `run_id` 已按 round/attempt 唯一，但 materializer 的 `staging_name` 仍只有
`batch + side + task_slug`。同题同侧的第二次 materialization 会命中第一次留下的目录，
而 `PinnedTaskMaterializer` 按设计拒绝复用。

离线连续 prepare 同一 slot 的 attempt 1 / 2，第二次稳定得到：

```text
MaterializationError: staging destination already exists
```

这意味着一次 infra 后的重试，以及最关键的 round 2 / 3 条件复跑，都无法进入 Docker。
在恰好需要三次观察判退化的路径上，Gate 2 只能得到设施失败/证据不完整，无法执行冻结合同。

### [P1] 停止线必须先于 Gate 1 成功分支判定 — `eval/rondo_eval/multi_m5/gate1.py:488`

当前代码先判断 `verdict.passed && returncode == 0`，之后才处理 `stop_class == budget/infra`。
因此只要协作谓词和报告已经形成，随后同一 run 出现
`upstream_terminal_failed`、缺失 usage、容量耗尽或其它 ledger stop，最终仍会归档为
`completed/passed=true`。这与本轮“上游失败归 infra、预算硬停止立即停”的合同相反，也可能让
Gate 1 在停止线实际触发后错误通过。

应先处理 budget / infra / unknown stop，再判断无停止的正常完成；“证据已经形成”可以保留作排障材料，
但不能把已停止的 run 改判为正式通过。

### [P2] 修正仍在读取 v1 的 loader 漂移测试 — `eval/tests/test_multi_m5_exec.py:1175`

`test_the_lock_must_carry_an_executable_diagnostic_contract` 仍读取
`multi-m5-nondegradation-v1.json`，再把变体交给只接受 v2 lock id 的 loader。
这些 case 会在检查 `runs_when`、`verdict_effect` 或额外键之前，就因 lock id 不符而抛错，
所以测试虽然为绿，实际是空验收。应改读 v2，并先断言未修改的临时副本能成功加载。

这也解释了为什么正式行仍写 v1、测试却没有报警：当前测试没有断言运行结果使用 loader 的 v2 `lock_id`。

### [P2] 清掉权威当前文档中的 v1 / 未冻结旧事实 — `doc/WBS/multi-agent-trusted-evidence.md:143`

同一份当前 WBS 前文仍写“Multi 目前没有冻结的 runtime bundle”，后文又写阶段 A bundle 已冻结；
Plan 044 当前状态的前部仍把 workflow / nondegradation 写成 v1，并保留累计费用 `$0`，
而后部已经改成 v2 并承认历史 smoke 账目。历史形成时点可以留在旧日志，但 WBS 与 Plan 当前状态不应
同时给出相反事实。上一轮 P1-9 尚未完全关闭。

## 验证

- `just eval-lock`：通过。
- code-mode trace 与 Terminal Bench 定向测试：58 个真实测试通过；首次命令另有 2 个审查者写错类名造成的
  selector error，随后已用正确类名复跑。
- 模型隔离、付费边界、smoke 隔离和停止语义定向测试：25/25 通过。
- 额外离线复现：
  - Gate 2 fake row 确认 `loaded v2 / archived v1` 与 `locked terra / archived sol`。
  - 同题同侧第二次 prepare 确认 staging 冲突。
- 未重跑全量 932；未调用真实 API、Docker、Cargo 或本地模型。

现有测试通过只能证明已覆盖路径成立，不能推翻上述未覆盖的确定性复现。

## 代用户作出的决定

1. **smoke 中删除 Plan 013 provider pre-probe。** 完整 flow 本身已经能证明 endpoint/model 可用；
   为它改造通用 probe 以共享外部 ledger 会增加不必要接线。若以后确实需要单独 provider probe，
   应作为独立、单独授权的动作，而不是藏在 `$40` smoke 入口里。
2. **不修改产品的 `ToolCallSource::Direct` 证据保留设计，也不弱化 `team_evidence` 谓词。**
   先修完本报告的离线确定性问题并复验，再用全新 label 做一次真实 smoke 回答模型实际会不会产生
   Direct 证据；没有真实轨迹前不改产品语义。
3. **现有 `$40` smoke 授权不扩张。** 修复并重新验收前不得使用；修复通过后可在原授权总额内继续，
   不把本轮审查当成新增费用授权。
4. **v2 是两道门唯一当前合同。** v1 文件只保留历史，任何正式新行都必须写 v2，旧行不得重标。
5. **正式 Gate 1 / Gate 2 继续禁止启动。** Gate 1 真正通过后才允许进入 Gate 2。

## 当前项目状态

- 验收：**不通过**。
- 任务目标：**失败（尚未实现预期）**。这里指本次 M-5 交付尚未完成，不是对 Multi 产品能力作失败判定。
- Gate 1：未通过；当前仍无真实通过证据。
- Gate 2：未启动；不存在“未观察到稳定单向退化”的结论。
- M-5：未通过，不能表述为 Multi 路线已收口。
- `$120` 正式账本仍未产生消费；本次审查未产生外部费用。
