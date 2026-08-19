# Plan 044 / M-5：本轮中断接手（审查 FAIL 之后）

日期：2026-08-20
工作树：`.claude/worktrees/044-multi-m5-real-workflow-and-nondegradation`
HEAD：`fda60fe`（已提交、未合并、未推送）
主工作区：`main` = `origin/main` = `45efac6`，干净，勿动。

历史合同、决策 001–046、v3 冻结步骤、cs1/cs2 结果仍以
`plan/044-multi-m5-real-workflow-and-nondegradation-execplan.md` §6–§7 为准。
本文件只补 **plan 停更之后** 发生、接手者否则看不见的事实。

**口径不变：M-5 未通过；门 1 未通过；门 2 未启动；正式 `$120` 账本仍不存在。**

---

## 1. 本轮从哪份审查开始

入口：`agent_log/2026-08-20-070000-plan044-m5-bundle-v2-clean-smoke-acceptance-review.md`

审查结论：**验收不通过；本轮任务目标失败。** runtime-v2 / 两把 v3 锁 / 明文修复本身成立；
clean smoke（cs1/cs2）未闭合；另发现三项缺口。用户随后改口令：

> 你直接替我修复吧，额外授权 500USD 预算可以用于任何你觉得需要的真实 API 测试，
> 直到停在可以正式进行 M5 的测评之前，或者任务彻底失败。

审查代作决定（已执行方向，不要再问）：

- 拒绝放宽 zero-taint（选项 B）。
- 不把 HTTP 200 流内 `server_error` 自行当成可重试且未计费（选项 A）。
- 先修三项缺口，再用全新 `clean-smoke-v2` 身份只跑一次，硬上限 `$23.10`。
- 允许清理本任务自建的
  `.claude/worktrees/044-m5-multi-bundle-measurement-v2/multidev/codex-rs/target`
  （约 5.9G）；**尚未清理**。不得扩及其他缓存。

---

## 2. 中断时的待办（真实进度）

| 项 | 状态 | 落点 |
|---|---|---|
| 修 Gate 1 在代理排空前归档 + 尾部 taint 回归 | **代码已做，未提交** | `gate1.py` 在读 stop/taint/exposure 前调用 `drain_budget_proxy=proxy.close`；回归 `test_gate1_drains_a_trailing_terminal_error_before_building_its_record` |
| 收紧明文判据 + 隔离 clean-smoke-v2 身份 | **代码已做，未提交；且已被真实 smoke 用过** | `collect.py` 只计 `author=/root` 的 `input_text`；`unknown_parts` fail-closed。账本/归档：`multi-m5-clean-smoke-v2` / `clean-smoke-v2-records.jsonl` |
| 定向离线测试与锁/就绪门禁 | **修三项时已绿；当前脏树已不再 ready** | 见 §5 地雷 |
| 新 v2 身份真实 API clean smoke | **已跑完** | `--label final-v2`，见 §3 |
| 判定 code-mode 成员证据链 | **已判清，未写进 plan/WBS** | 见 §4 |
| 修证据链产品/合同 + 最小回归 | **半成品，未提交** | 见 §5 |
| 重冻 bundle/锁 | **未开始** | `eval/locks/multi-m5-runtime-v3.json` **不存在** |
| 新身份最终 smoke，停在正式门前 | **未跑** | 代码已把 smoke 身份预写成 v3，但 bundle 还是 v2 |
| 更新权威文档与核对 | **未做** | plan/WBS 仍停在 cs1/cs2 |

审查报告本身当时是 044 树唯一未跟踪文件；现在又多了未提交工程改动和两把未冻结的 v4 锁。

---

## 3. `final-v2` 干净观察（plan 没有）

身份：`batch/lock = multi-m5-clean-smoke-v2`，`run_id = m5-g1-smoke-final-v2`
归档：`eval-data/multi-m5/archives/clean-smoke-v2-records.jsonl`（1 行）
账本：`eval-data/budgets/multi-m5-clean-smoke-v2.json`，`max_runs=1`，`cap=$23.10`
捕获：`eval-data/multi-m5/captures/m5-g1-smoke-final-v2/`
二进制仍是 runtime-v2 / 源码 `6fe1379`。

结果：

- `outcome=agent_failed`，原因仅 `predicate:team_evidence`
- 29 请求全部有 usage；`priced_usd=charged_usd=$0.389633`；`conservative_exposure_usd=0`；`infra_taint=null`；`stop_reason_class=none`；进程退出 0
- `member_message_delivery=plaintext`（26 / 0 / 0）
- 七谓词：`spawn_member` / `event_with_two_versions` / `two_authors` / `team_route` / `root_resolved` / `root_woken` = true；**只有 `team_evidence=false`**

旧 `cs1/cs2` 与 `cm1–cm4` 未改写。`code-mode-smoke-records.jsonl` 从现在起只读。
这轮 `$500` 授权实际只花了这一笔约 `$0.39`。正式 `$120` 仍未开。

---

## 4. `team_evidence=false` 的判定（plan 里仍写成“尚未验证”）

**不是**模型漏调 `team_evidence`。成员调了 `team_publish` 和 `team_evidence`。
**是** code_mode_only 下成员证据链结构不可达，彩排靠作弊才绿。

实证（final-v2）：

- 成员在 cell 内 `exec_command` 读到 `NOTES.md`（payloads/25.json 含 finding 行）。
- 随后 `team_publish` 返回 `evidence_refs: []`（payloads/40.json）。成员 Version 因此无 fact。
- 成员后来的 `team_evidence` 读的是 **Root 的** `fct-1-9c0677857124488586e5e81374d9ea69`，`producer=/root`，`tool=exec`，观察文本是 yielded 初始的 `Script running with cell ID 2...`，不是成员读 NOTES 的结果。
- dump 里只有 Root fact。谓词要的是**成员作者 Version 带 `fact_ref_count>=1`**，因此为假。

机制（两层叠在一起）：

1. `note_completed_tool_result()` 仍只认 `ToolCallSource::Direct | DirectPlaintextMessage`。嵌套 cell 调用按设计不单独留 fact（输出折进外层 cell）。
2. 外层 `exec` 的保留结果是 `CustomToolCallOutput` + `ContentItems` 若干条 `input_text`（script status + 输出）。`supported_observation()` 原先只认 `FunctionCallOutputBody::Text`，**整段 content-item 被丢掉**，所以连外层 cell 也不能铸 fact。
3. 彩排 `_shell_call` 以前走顶层 `function_call` 的 Direct shell。terra 冻结能力是 `code_mode_only`，真实模型看不见这条路。彩排绿 ≠ 真实可达。

附带现象：Root 那条唯一 fact 来自 Direct `wait` 接到 yielded cell 的初始 “Script running…”，不是最终 cell 结果。不要把这条当成成员证据。

结论：当前 M-5 **设计在真实 code-mode 下不能满足冻结的 `team_evidence` 谓词**。不要再靠加码指令硬跑三次门 1。也不要把谓词放宽成“调过 `team_evidence` 就算”。

选用的最小修法（已开做，未完成）：让**已保留的全文本 content-item cell 结果**成为可确认 observation；嵌套步骤仍然不单独铸 fact。彩排 shell 改走与真实模型相同的 `exec` cell。指令 v2 只写清“成员必须挂上自己的 `evidence_refs`”，不替代产品修复。

---

## 5. 工作区地雷（接手第一件事）

`git status` 相对 `fda60fe` **脏**：

已改：`gate1.py` `collect.py` `store.py` `budget.py` `load.py` `rehearsal.py` `evidence.rs` `evidence_tests.rs` `test_multi_m5.py` `test_multi_m5_exec.py`
未跟踪：审查报告、`eval/locks/multi-m5-workflow-v4.json`、`eval/locks/multi-m5-nondegradation-v4.json`、`eval/templates/multi-m5/collab-workflow-instruction-v2.md`

**`load.py` 已切到还不存在的运行时：**

```
WORKFLOW_LOCK_ID = multi-m5-workflow-v4
NONDEGRADATION_LOCK_ID = multi-m5-nondegradation-v4
RUNTIME_LOCK_ID = multi-m5-runtime-v3
```

磁盘上仍只有 `multi-m5-runtime-v2.json`。当前脏树跑 `ready` / 彩排 / smoke **会 fail-closed**。
HEAD 提交上的 v3 合同与 runtime-v2 仍自洽；不要用脏树去解释 `fda60fe` 的 ready=true。

smoke 常量也已预写成下一轮身份（**尚未使用、账本文件不存在**）：

- `SMOKE_BATCH_ID/LOCK_ID = multi-m5-clean-smoke-v3`
- 归档 `eval-data/multi-m5/archives/clean-smoke-v3-records.jsonl`
- 账本 `eval-data/budgets/multi-m5-clean-smoke-v3.json`
- 仍是 `SMOKE_MAX_RUNS=1`，`SMOKE_CAP_USD=23.10`

产品半成品：`supported_observation()` 已接受“非空且全部为 `InputText`”的 content-item（混媒体/密文整段拒绝）。单元测试 `team::evidence::tests` **6/6**（看门狗，target=`eval-data/build/m5-code-mode-evidence`）。
**嵌套 CodeMode 仍不 note。** 彩排 `_shell_call` 已改为 cell 内 `exec_command`/`shell_command`/`shell`。
指令 v2 sha：`3cb8d4eb110b269a6f3f3d431e22a8445cba742d6bfe694db17c401a6075d7ca`。

v4 锁草稿已写 `runtime_lock_id=multi-m5-runtime-v3`，但 v3 runtime 锁和 bundle **都还没有**。不要把草稿当成已冻结合同。

---

## 6. 接手后直接做什么

授权范围仍有效：修到可以正式开 M-5 之前，或认定彻底失败；真实 API 可花剩余 `$500`；不要为常规进度停下来请示。
**禁止启动正式门 1/门 2。** 正式 `$120` 账本仍不得创建。

建议顺序：

1. **先把脏树收成可验证状态**，不要用当前 `load.py` 去跑 HEAD 上的 ready。
2. 补齐证据链回归：全文本 cell 结果能被 note+retain+挂到成员 Version；混媒体仍拒绝；彩排不再发 Direct shell。
3. **提交产品修复后**再建 measurement 树、按 plan §6 的两次构建流程冻 `multi-m5-runtime-v3`（源码必须含本轮 `evidence.rs`，不能再冻 `6fe1379`）。`CARGO_TARGET_DIR` 必须是 `eval-data/build/rondo-multi-<commit>-x86_64-unknown-linux-musl`，不要用 measurement 树里那个 5.9G 的 `codex-rs/target`（`prepare` 会拒收）。
4. 落盘 `multi-m5-runtime-v3.json`，确认 v4 两把锁、loader、彩排、loopback、`ready=true` 都指向它。旧 v2/v3 归档不得升级冒充 v4。
5. 新 bundle 上重跑彩排：七谓词必须在**无 Direct shell** 时全真。
6. 一次 `smoke --label <新 id>`，身份必须是 `clean-smoke-v3`，硬上限 `$23.10`。验收仍是：ledger=归档、zero taint、`conservative_exposure_usd=0`、成员明文任务、成员 Version 真有自己的 evidence_refs、trace 绑定无误。
7. 只有这次过了才停在“可以正式开 M-5 之前”交回。仍不过：写清是产品链还是 terra 不按协议，不要再烧正式门次数。
8. 再更新 plan §6、WBS、本任务日志。5.9G target 仍可按审查授权清理，确认无构建进程且 runtime-v3 已不依赖它。

重型构建口令、看门狗租约条件、`CARGO_BUILD_JOBS=2` 仍用 plan / `agent_log/2026-08-20-050000-plan044-m5-bundle-v2-and-clean-smoke.md`，此处不重复。

---

## 7. 费用快照（本轮增量）

| 批次 | 文件 | 扣减 | 说明 |
|---|---|---|---|
| 合同外 cm1–cm4 | `eval-data/budgets/multi-m5-code-mode-smoke.json` | 见 plan | 旧 bundle，只读 |
| clean-smoke v1 cs1/cs2 | `eval-data/budgets/multi-m5-clean-smoke.json` | `$11.52` | plan 已记；混写过旧归档 |
| **clean-smoke-v2 final-v2** | `eval-data/budgets/multi-m5-clean-smoke-v2.json` | **`$0.389633` 全为 priced** | plan 没有 |
| 正式 `$120` | `eval-data/budgets/multi-m5-phase-b.json` | 文件不存在 | 未动 |

---

## 8. 不要做的事

- 不要在 runtime-v3 落盘前对脏树宣称 ready=true 或彩排全绿。
- 不要重跑 cs1/cs2/final-v2，也不要复用 `--label final-v2`。
- 不要把 nested dispatch 的 JSON 当证据；不要解析 JS；不要信 `custom_tool_call_output` 文本。
- 不要把 HTTP 200 流内错误加进重试白名单。
- 不要合并/推送，除非用户再要求（决策 009）。
- 不要表述 M-5 / 门 1 通过或未见退化。
