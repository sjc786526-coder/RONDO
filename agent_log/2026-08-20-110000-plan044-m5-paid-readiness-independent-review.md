# Plan 044 / Multi M-5 正式付费前独立终审

日期：2026-08-19（PDT）｜对象：`worktree-044-multi-m5-real-workflow-and-nondegradation@68268b5`

## 结论

**NO-GO，不应启动正式 Gate 1 或 Gate 2。验收不通过；本轮“正式门前全部就绪”目标失败。**

M-5 本身仍是未完成，不是已经得到“产品退化”或“产品目标失败”的测评结论：正式 `$120` 账本与锁仍不存在，正式
Gate 1 / Gate 2 均未启动。当前阻断是门前判据与执行设施仍会测错或污染证据。

## 阻断发现

### P0：Gate 1 可在冻结协作协议未完成时假通过

- WBS 与冻结指令要求成员真实调用 `team_evidence` 下钻自己的 Fact，并在 Root route 后再追加一个成员 Version。
- `workflow-v5` 的 required tools 只有 `team_inspect` / `wait_agent`；collector 也只强制这两类 dispatch。
- `predicates.py` 的 `team_evidence` 只检查成员 Version 挂有任意 Fact，版本数只要求两个。于是 Root 一个 Version +
  成员一个 Version、完全没有 `team_evidence` 调用，也可满足七项谓词。
- 独立红队已用纯内存最小反例得到 `passed=true`、7/7。该缺口会把“未发生证据下钻、成员未完成第二次追加”归档为
  正式 Gate 1 通过，直接违反 M-5 完成标准。

最小整改：要求成员线程存在 completed `team_evidence`；其 `fact_id` 绑定同一 Event 的成员 VersionFact；返回
available、producer 为该成员、observation 非空且对应冻结 finding；同一 Event 至少有 Root 一个、成员两个 Version。
补缺调用、Root Fact、失败/空结果、仅两版本四类反例即可，不建设新框架。

### P1：测试与正式 Gate 1 共用 capture namespace，当前已污染

- 正式运行固定使用 `m5-g1-paid-a1..a3`；M-5 测试也以真实 common root 调用同一入口，`persist=False` 只跳过
  archive，不隔离 capture。
- runner 会删除同名 `requests.jsonl`、替换 `rollout-trace`、覆盖 `verdict.json`，但
  `budget-metadata.json` 会读取旧文件后追加。
- 本次审查误并发启动两轮 136 项测试，现场复现该缺陷：a1 metadata 已有 19 条测试 observation，a2 有 1 条。
  当前直接启动正式 Gate 1 会从第一笔起混入 fake metadata；正式运行后再跑回归又会覆盖正式 raw trace/verdict。
- 同一缺陷已把 v5 rehearsal 的 archive→raw 链打断：archive 最后一行 Event 是 `evt-1-d5a...`，当前 canonical raw
  verdict 已被测试改为 `evt-1-eaa...`。正式 archive 本身仍为 26 行、原 SHA-256，正式账本未受影响。

最小整改：测试使用临时 capture root/唯一测试 run id；正式 capture 对既有非空目录 fail-closed 或使用版本化正式
namespace；隔离本轮明确产生的测试残留，并以新身份重新形成一次可下钻的离线 rehearsal 证据。历史只增不改。

### P1：Gate 2 在 provider 冻结预检前先消费正式 run id

- `ready` 只查模型投影与预算上界，不调用 `require_frozen_provider`。
- 正式 Gate 2 先打开 `$120` ledger，并在首槽 `claim_run`；endpoint、effort、retry 与费率校验直到 executor
  `_run_live` 才执行。
- 若机器配置漂移，入口在零 API、零 Docker 时退出，但首个确定性正式 run id 已永久占用且没有 archive 行；修正配置后
  同一批次无法重启。

最小整改：把完整 provider frozen preflight 放到创建/打开正式账本和任何 `claim_run` 之前，并纳入 `ready`。

### P1：正式批次缺少可继续执行的中断恢复语义

- 当前 Gate 1 / Gate 2 使用固定 run id；Gate 2 重启时又从内存中的零计数和第一个基础槽开始，已 claim 的首个 id 会直接
  阻断同一批继续。对最长可运行一天的批次，这会把一次进程退出放大成整批无法完成。
- 用户明确选择把“有效样本数”与“设施修复机会”分开，不再接受 one-shot / 不可 resume 作为本次正式运行边界。

整改合同如下：

1. Gate 1 最大尝试由 3 提高到 6；Gate 2 每槽 infra 尝试由 3 提高到 5、全批 infra 总上限由 12 提高到 40。
2. 共享 run 槽位改为 `60 effective + 40 infra + 6 Gate 1 + 10 diagnostic = 116`。`$120` 总硬上限、每 run
   80 个逻辑请求、provider 单请求最多 5 次 HTTP 尝试均不变。
3. 无 usage 或流中断仍立即 taint 当前 run；不在已污染 run 内继续请求，而是占用一个 infra 机会转入新 attempt。
4. resume 必须先核对相同的 batch、合同锁、runtime 与 provider 投影，再从正式 archive/ledger 重建 effective、infra、
   diagnostic 和 Gate 1 进度：已有完整归档的槽位无论 `completed` 还是 `agent_failed` 都按原分类跳过并计入有效观察，
   `infra_failed` 消耗一次 infra 后转下一 attempt；已 claim、零逻辑请求、`spent=reserved=0`、无 taint/stop、无冲突产物且
   无存活 writer 的槽位才允许原 id 安全重领；已经发过请求但没有完整归档的 id 先保守结算悬挂 reservation，再只追加一次
   `abandoned=true, outcome=infra_failed, counts_as_effective=false` 恢复记录，不复用该 id，转入下一 attempt。
   调度应从 archive+ledger 重建全部计数和每槽 attempt；基础轮完整后才能重建 conditional slots，verdict 完整后才能重建
   diagnostics；重复/冲突行或非连续未来行 fail-closed。恢复动作必须幂等，反复重启不能重复计数或重复追加 abandonment；
   `budget_stopped`、Docker 容量停止和全批 infra 耗尽仍终止批次，resume 不得绕过。
5. 被测模型正常完成后得到的任务失败仍按产品结果计入原判据，不能改标 infra 来换取额外样本；Gate 2 的 60 个有效样本、
   条件复跑与稳定单向退化判据不变。Gate 1 的产品/证据失败可按协议进入下一 attempt，但保留原失败分类。若必须修改 RONDO
   产品代码，则冻结新的 runtime/合同/批次身份，并在新身份下重启相应 Gate，不混用修复前后的有效结果。

按冻结的经验单次估计，放宽后的**最坏调度形状预测**为 `$67.80`：60 个有效运行 `$21.60` + 40 个最贵侧 infra
`$21.60` + 10 个诊断 `$5.40` + 6 次 Gate 1 `$19.20`。点估计仍为 `$10.40`。`$67.80` 不是实际费用硬上限，
合法 token 用量仍可能令实际消费高于预测；累计 reservation/settlement 的 `$120` 才是硬停止，因此无需提高总上限。

### P1：正式授权清单仍指向旧合同与旧费用

- Plan “阶段 B 精确授权清单”仍写点估计 `$16`、最坏 `$38.40`，镜像指针仍引用 nondegradation-v2；“当前状态”
  前部也仍把 workflow-v2 / nondegradation-v2 / runtime-v1 写成现行。
- 当前机器合同实际是 `workflow-v5 → runtime-v4 → nondegradation-v5`，费用为 `$10.40 / $43.08 / $120`，
  endpoint 为 `https://www.cctq.ai/v1`；它还没有包含本报告新增的放宽与 resume 决策。

正式付费授权必须基于整改后新冻结的 workflow-v6/nondegradation-v6（runtime-v4 可复用）：绑定上述 endpoint，费用口径
更新为“点估计 `$10.40` / 最坏调度形状预测 `$67.80` / 硬上限 `$120`”，并明确 6 / 5 / 40 / 116 的尝试与槽位上限。
现有 v5 已承载 rehearsal/smoke 历史，不得原地改写。因此该文档漂移应与上述窄修一起收口，不能再以 v5 或旧费用作为正式
起跑对象。

## 已确认正确的部分

- Rust 产品修复 `0eee6dc` 独立静态审查无 P0/P1；code-cell/Direct、thread/turn/session、terminal/Yielded、
  output-item、Fact→Version→observation 与权限/容量边界均失败关闭。既有共享 build-lock 结果 146/146。
- runtime-v4 与 Codex baseline 的 CLI、code-mode host、bwrap、manifest 实物摘要均与锁一致；measurement-v4
  detached clean 于 `0eee6dc`。
- v5 锁绑定关系、十任务、terra/medium、60 有效运行、12 infra、80 请求/run、token envelope 与 `$120` 数学硬上限
  未发现绕过。
- clean-smoke-v5 仍是独立有效的非正式 smoke：20/20 settled，计价 `$0.273138`，零 taint/保守暴露，18/18
  code-cell dispatch，且实际发生了成员 Fact→Version→`team_evidence` observation 链；它不替代正式 Gate。
- 主工作区 `main=origin/main=45efac6` 干净；任务 worktree 受跟踪文件在写入本报告前干净。未运行 Docker、真实 API、
  重型 Cargo 或正式测评。

## 验收恢复条件

只需完成上述四处有效设施窄修与一处文档收口；随后串行运行 M-5 Python 136 项、`eval-lock`、ready、loopback 与
rehearsal，并核对新 rehearsal archive/raw 一致。无需重跑 Rust 重型门禁、Docker 或任何付费 smoke。复验通过后，
先正式 Gate 1；只有 Gate 1 通过后再授权并启动 Gate 2。

## 其他已接受边界

- Gate 1 的协议演示 fixture 保留，不把它夸大为分析任务；真实任务由 Gate 2 提供。
- 账本保留为 `$120` 硬停止与恢复状态来源，但 run 槽位不再作为过早结束批次的购买力限制；正式执行采用上述受限、幂等的
  resume，而不是放开重复消费。
- Harbor 已返回 Docker evidence 后若结果解析失败，当前 infra 行不带该 evidence；建议顺手保留，但不单独阻断起跑。
