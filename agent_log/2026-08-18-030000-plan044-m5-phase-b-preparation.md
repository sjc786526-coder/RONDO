# Plan 044 / Multi M-5 阶段 B 离线前置准备

日期：2026-08-18 ｜ 分支：`worktree-044-multi-m5-real-workflow-and-nondegradation` ｜ 基线：`7957997`
｜ 本轮无费用：未跑 Docker、未调真实 API、未加载本地模型

## 结论

阶段 B 的离线前置准备完成，**门 1 整条链路在花钱之前已经验成绿的**。
真实付费与 Docker 仍未授权、未执行。

## 交付

| 交付物 | 落点 | 入口 |
|---|---|---|
| 门 1 host runner | `gate1.py` + `command.py` + `capture.py` | — |
| 门 1 离线彩排 stub | `rehearsal.py` | `just eval-multi-m5-rehearsal` |
| 门 2 轻量交错执行面 | `gate2.py`（真实执行器 fail-closed） | `just eval-multi-m5-gate2-fake` |
| 预算记账 | `budget.py`（批次 `multi-m5-phase-b`，$120 硬上限在代码里） | — |
| 归档落盘 | `store.py` → `eval-data/multi-m5/archives/records.jsonl` | — |
| 就绪自检 | `ready.py` | `just eval-multi-m5-ready` |

`command.py` 是唯一的 argv 构造点，团队能力 `-c` 项只来自
`contracts.team_capability_override_items()`，与之不符即抛错；loopback、彩排与将来的付费门 1 共用它。
`capture.py` 的 stub 与 forward 两模式共用同一套监听、整体请求体记录与 JSONL 写入（F5），
且 forward 的上游被限制为 127.0.0.1 —— 这个模块自身无法直连付费端点。

## 门 1 彩排结果（本轮最重要产出）

冻结二进制真跑，stub 只替代模型侧。**连续五次全绿，请求数稳定 16，无 stub 错误、无未归属证据。**

判定：七项谓词全真，`passed=true`，`event_id=evt-1-495b9aaa…`，`ignored_evidence=[]`。

真实 canonical 状态（从捕获的 `team_inspect` 输出独立复核，不是 stub 自述）：

- 参与者两名：`/root`（root）与 `/root/worker`（member），均 available —— 成员是真 spawn 出来的。
- 同一 Event 三个 Version 跨两个作者：`ver-1.1`（成员）、`ver-1.2`（Root）、`ver-1.3`（成员）。
- 证据：`fct-2` 由成员真实的 `exec_command` 结果铸成，挂在成员的 `ver-1.1` 上。
- route `rte-1.1` → `/root/worker`，`duty=assigned`、`delivery=delivered`。
- Root 把**成员作者的** `ver-1.1` 置为 `root=resolved`。
- 变更日志的唤醒规则逐条成立：`member_publish` 唤醒 Root、`root_does_not_self_wake`（设计合同第 9 条）、
  `assignment_wakes_target` 唤醒成员、`delivery_does_not_wake`。
- `wait_agent` 返回真实 TeamActivity 原文。

即 M-1 世界状态与唤醒、M-2 route/指派/投递、M-3 证据锚定在一次真实纵切里全部被触发。

**这不是门 1 通过**：协议由 stub 脚本驱动，证明的是产品与判据这条链路能走通，
不是真实模型会遵守协议。记录标注为 `evidence_kind=loopback`、`rehearsal=true`、`counts_as_effective=false`。

## 本轮修复

- **门 2 重试记录丢失**：`run_slot` 原来每个槽位只返回最后一条记录，被重试掉的 infra 尝试
  在归档里整个消失（只有计数器加了 1）。改为返回该槽位的全部尝试记录，调用方逐条归档。
  这直接影响"infra 不计有效结果"的可核对性 —— 没有 infra 行就无法证明它没被计入。
- **Gate2Error 不计入 infra 预算**：执行器抛 `Gate2Error` 时原来直接返回、既不计数也不重试，
  等于绕过 infra 总上限。改为与其它 infra 失败同一条路径：计数、按 `max_slot_attempts` 重试、
  计入总上限 12。
- **假二进制哈希**：`_record_for` 原先在 `codex_sha256` 缺失时回填 64 个 `0`。公平合同要求每行都带
  双方二进制身份，占位哈希会让未冻结的 bundle 看起来可比。改为 fail-closed。

## 验证

- `tests.test_multi_m5` + `tests.test_multi_m5_exec`：**39/39** 通过。
- 完整离线 `just eval-test`：**865 项**（基线 854 + 新增 11），仅剩既有的
  `test_l6_b10333_pair`、`test_local_m4_holdout_anchor` 两项 Local 模块加载失败
  （干净 `main` 同样复现，属另一任务，未动）。
- `just eval-multi-m5-rehearsal`：5/5 全绿。
- `just eval-multi-m5-gate2-fake`：20 个基础槽位、0 条件复跑、0 infra、记账正常、20 条归档。
- `just eval-multi-m5-ready`：`ready=true`，`missing=[]`；两侧 bundle 哈希与锁相符，
  `.env.local` 存在/非符号链接/0600/所需变量非空（只做布尔检查，未读出任何值）。
- 归档落盘复核：`records.jsonl` 四条门 1 记录，全部 `loopback` / `counts_as_effective=false`。
- 未跑 Rust（`multidev/` 零改动）、未跑 Docker、未调真实 API、未产生费用。

## 付费前仍缺的

1. **门 1 付费入口**：`capture.py` 的 forward 模式已具备，但没有把"预算代理 + forward 捕获 + 真实模型"
   接成一个付费门 1 运行函数。
2. **门 2 真实执行器**：当前是 `DockerNotAuthorizedExecutor`，直接 fail-closed。真实执行须走既有
   `terminal_bench` adapters/runner/results，不套 v7 campaign。
3. 这两件按阶段 A 收口的 F3 决议，实现后须再过一次独立审查，通过后才申请真实 API/付费授权。
