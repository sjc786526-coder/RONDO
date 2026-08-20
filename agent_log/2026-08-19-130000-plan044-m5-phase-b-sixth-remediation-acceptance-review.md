# Plan 044 / M-5 阶段 B 第六轮整改验收审查

日期：2026-08-19
分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`
审查范围：`5bdacc3..5a2a72d`

## 结论

**本轮七项整改验收通过。**

未发现会影响正确性、付费边界或两道门执行的新缺陷。上一轮的 3 项 P0、2 项 P1、2 项 P2
均已按决定落实，新增的 fail-closed 守卫是合理加严，没有改变既有授权或产品语义。

这里通过的是第六轮工程整改，不是 M-5 总任务：

- Gate 1 尚无真实模型通过证据；
- Gate 2 尚未启动；
- 因此 M-5 仍未通过，也不存在“未观察到稳定单向退化”的结论。

## 复核结果

1. **smoke 费用边界**：`run_provider_probes` 已从 smoke 入口删除；入口只打开并使用
   `multi-m5-code-mode-smoke` 的单一 `$40` ledger。模型、endpoint 和费率仍在外发前冻结校验，
   完整 flow 自身承担 provider 可用性验证，不再存在每个新 label 额外绕出 `$5` 的路径。
2. **归档成员身份**：`archive_record()` 已显式接收 member model / effort；Gate 1、Gate 2 和
   loopback 均传入实际运行合同的值。Multi 行遗漏成员模型会直接失败，避免再次静默回落到宿主 sol。
3. **Gate 2 合同身份**：`_record_for()` 使用本次实际加载的 `contract.lock_id`；离线行现为
   `multi-m5-nondegradation-v2`，Multi 成员为 terra，Codex 无成员投影。
4. **Gate 2 重试与条件轮次**：staging 名增加由 run 唯一 `docker_task_id` 派生的安全短哈希。
   attempt 1/2/3 连续 materialization 均成功且目录不同；重复同一 run identity 仍会按原设计拒绝。
5. **Gate 1 停止语义**：budget / infra / unknown stop 先于成功分支处理。即使七项谓词已全真，
   `budget_capacity_exhausted`、`upstream_terminal_failed` 或缺失 usage 也不能归档为 completed。
6. **loader 漂移测试**：改读 v2 合同，并先证明未修改副本可以加载；目标字段、未知键和费用预测漂移
   现在确实到达各自校验点，不再提前死于 v1 lock id。
7. **文档事实**：当前说明中的 runtime bundle、v2 合同和历史冒烟费用口径已统一；v1 仅作为历史保留。

## 独立验证

- 定向运行归档、诊断、staging、停止语义、smoke 隔离及 Terminal-Bench 相关测试：**54/54 通过**。
- `just eval-lock`：通过。
- 静态复核 smoke 调用链：不存在 `run_provider_probes` 调用。
- 未重跑执行者已完成的全量 936；接受其“936 通过、2 条既有 collection error”的限定口径，
  不将其表述成无 collection error 的全量全绿。
- 本次审查未调用真实 API、Docker、Cargo 或本地模型，未产生费用。

`git diff --check 5bdacc3..5a2a72d` 仅报告上一份验收日志中三个 Markdown 强制换行空格；
不涉及代码、合同或运行结果，不构成本轮整改缺陷。

## 代用户作出的决定

1. **下一步执行一次真实付费 smoke：同意。** 使用现有、未扩张的 `$40` 授权，必须使用全新
   `--label`，只运行一次当前 smoke 入口；不得附加独立 provider probe，也不得触碰正式 `$120` 账本。
2. 本次 smoke 只回答真实模型是否产生可验证的 `ToolCallSource::Direct` / `team_evidence`，
   不能算 Gate 1 attempt，成功也不能表述为 Gate 1 或 M-5 通过。
3. 若 smoke 中其它协作证据成立但 `team_evidence` 因没有 Direct fact 失败，保留完整 trace 和归档后停止；
   不自动弱化谓词、不自动修改产品设计，由真实证据驱动下一次决策。
4. 正式 Gate 1 / Gate 2 继续禁止启动；Gate 2 仍必须等 Gate 1 真正通过。
5. 当前不合并、不推送。付费 smoke 结果及账本口径记录完成后，再进行下一次验收和分支交付决定。

## 当前项目状态

- 本轮整改验收：**通过**。
- M-5 任务目标：**失败（尚未实现预期）**。这是“尚未完成”，不是 Multi 产品能力被判失败。
- Gate 1：未通过。
- Gate 2：未启动。
- Multi 路线：尚未收口。
