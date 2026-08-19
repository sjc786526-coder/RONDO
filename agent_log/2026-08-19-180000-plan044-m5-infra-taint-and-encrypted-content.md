# Plan 044 / M-5：证据污染语义修复与 `invalid_encrypted_content` 归因

日期：2026-08-19 ｜ 分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`
范围：冒烟验收审查 5 项（1×P0、3×P1、1×P2）。**本轮未调用真实 API，未产生费用。**

## 结论口径

**M-5 未通过，门 1 未通过，门 2 未启动，不存在"未见退化"结论。** 正式 `$120` 账本仍不存在。
上一轮"真实模型不遵守协作协议"的结论**已撤回**，理由见下。

## P0：阈值只管"继续/停止"，不管"算不算产品证据"（属实，是我引入的缺陷）

我上一轮加的 `unpriced_stop_threshold` 把两件事混成了一件。低于阈值的保守结算只扣钱，
不写 stop，于是 `run_stop_reason()` 返回 `None`，门 1 会判 `completed`/`agent_failed`、
门 2 会 `counts_as_effective=true`。

cm4 正是这个形态：**8 次 `invalid_encrypted_content` 上游终止**，账本却是
`stopped=false / stop_reason=null`，归档写成 `agent_failed` —— 一个这次运行从未挣得的模型判决。
正式阈值当时是 4，意味着每个正式 run 可以带 3 次设施错误仍算产品观察，门 2 由此可能制造假退化。

**修法**：把"污染"与"停止"彻底分开。

- `PersistentBudgetLedger` 在**每一次**保守结算与 operator-confirmed-unbilled 结算时写
  `infra_taint = {count, first_reason}`，与是否触发 stop 无关；
- 新增 `infra_taint()` / `run_infra_taint()` 读取口；
- **门 1**：run 带 taint 一律判 `infra_failed`，即使七个谓词全真（新增回归直接钉住这一点）；
- **门 2**：带 taint 的 slot 一律 `counts_as_effective=false` 且记 `infra_failed`，
  不进入退化判定（新增回归构造"只有某题 Multi 侧被污染"的场景，断言该题不会得出
  `stable_one_way_degradation`）；
- 归档行新增 `infra_taint` 字段。

`infra_taint` 在 run state 里是**可选键**，`_validate_state` 相应放宽，因此
既有账本文件（含 cm1—cm4）不改写也能继续加载。

**与审查建议不同的一处（已加严）**：审查给了两个选项，推荐冻结 v3 并在正式门保留
"可继续但证据作废"。我选了**最小修法**：正式批次 `UNPRICED_STOP_THRESHOLD` 恢复为 1，
阈值 >1 只留给合同外冒烟。理由是——既然 taint 已经让运行无法成为证据，正式 run 继续下去
不可能产出可用观察，只会多花钱；恢复 1 同时避免了现在就冻结 v3（审查自己也希望把 v3
推迟到 provider 修复后一次冻结）。因此 v2 锁无需改动，也不产生锁漂移。

复核：把 cm4 的真实账本喂给新读取口，`taint.count=8`，门 1 判决从 `agent_failed`
变为 `infra_failed`。

## P1：撤回"真实模型不遵守协议"（属实，且比审查判断的更明确）

审查指出 cm4 不是干净观察。逐线程复核后结论比这更强 —— **失败全部集中在成员线程**：

| 线程 | agent_path | inference_started | inference_failed | tool_call |
|---|---|---|---|---|
| `01a0185c-10c4…` | `/root` | 22 | **0** | 19 |
| `01a0185c-2f5d…` | `/root/worker` | 8 | **8** | **0** |

**成员 8 次推理 8 次失败，从未完成一个回合。** 它当然不可能 publish / route / evidence。
所以"成员没做这些动作"完全无法归因给 terra 的指令遵循，上一轮那句结论撤回。

（附带勘误：我上一轮说"所有失败都在 Root 线程"是错的。两个 thread id 都是 UUIDv7、
共享前 8 位时间前缀，我按 8 位截断分组把两条线程并成了一条。现按完整 id 复核。）

## P1：`invalid_encrypted_content` 归因（已定位到具体构造）

30 个已结算请求里 8 个是 `upstream_status=200` + `terminal_event_type=error` +
`terminal_error_code=invalid_encrypted_content`，全部属于成员线程。

抓包定位到确切位置（**未打印、未归档任何密文**，只记录键路径）：

```
failing body 2: ['/input[]/content[]/encrypted_content']
   agent_message keys: ['author', 'content', 'id', 'recipient', 'type']
   author: /root
```

即：**成员请求里带着一个 `author=/root` 的 `agent_message`，其 `content[]` 内嵌
`encrypted_content`** —— Root 的加密推理被带进了成员会话。会话级请求配置是
`store=false` + `include=['reasoning.encrypted_content']`，Root 自身逐轮累积并回传自己的
加密推理是正常的（Root 侧 22 次全部成功）；把**另一个会话**产生的加密推理放进成员请求，
正是 `invalid_encrypted_content` 的字面含义。Root 发起 spawn 时用的是 `fork_turns:"all"`。

**归因倾向：产品侧子线程构造**（确定性 8/8，而不是抖动）。但**不下定论**：
无法排除第一方 endpoint 会接受、而 relay 因不保留加密上下文才拒绝。要定论需要在
第一方 endpoint 上对同一构造做一次对照，或对 fork 路径做离线产品测试。

**未按"剥离 encrypted content"来绕过** —— 那会改变模型上下文，审查明确禁止，我同意。

## P1：`team_evidence` / Direct fact 风险仍未验证（属实）

cm4 里唯一 `requester=model` 的调用是 Root 一次**失败**的、无 namespace 的 `wait`；
所有 `collaboration.*` 都是 code-cell 嵌套调用；成员零调用。
所以既不能证明成员会产生可供 `team_evidence` 引用的 Direct fact，也不能证伪。
`multidev/codex-rs/core/src/team/evidence.rs` 的既有风险原样保留。

## P2：文档相反入口（属实，已清理）

Plan 里仍写 smoke 内置 `provider_probe`（该 probe 已于上一轮删除），
WBS 同时写"真实付费运行仍未开始"和"四次冒烟已执行"。已分别改为
"**正式两道门未启动**"与"smoke **不含**独立 provider probe"。

## 验证

- 定向门禁 `tests.test_multi_m5_exec`：74 用例全绿（含 3 条新回归：
  污染在可继续时也被记录、门 1 tainted 必判 `infra_failed`、门 2 tainted 不得计为有效观察）。
- `tests.test_api_budget_proxy`：56 用例全绿 —— 默认 threshold=1 与既有 campaign 行为未变，
  且旧账本（无 `infra_taint` 键）仍可加载。
- 全量与 `just eval-lock`：见提交说明。
- 未调用真实 API、Docker、Cargo 或本地模型。

## 下一步（含新授权）

用户本轮追加授权 **$500 用于冒烟测试**。但按审查决定与我的判断，**不应立刻开跑**：
当前失败是确定性的（成员 8/8），再跑同一 relay + 同一构造只会以同样方式失败并烧钱。
顺序应为：

1. （已完成）证据污染语义。
2. 定位 `invalid_encrypted_content` 归因：对 fork 路径做离线产品测试，
   或在第一方 endpoint 上对照同一构造。
3. 归因清楚并修复后，**一次性**冻结 v3（endpoint、retry/backoff、continuation threshold、
   `any_unpriced_invalidates_observation`），避免连续改锁。
4. 用全新身份做一次 clean smoke，验收条件不是 `returncode=0`，而是
   `conservative_exposure_usd=0`、无 infra taint、**成员至少完成一次工具调用**、trace 绑定无误。
5. 只有 clean smoke 仍不走协议，才进入"加强指令"分支；换模型是最后选项。
6. 正式 Gate 1 / Gate 2 继续禁止启动。
