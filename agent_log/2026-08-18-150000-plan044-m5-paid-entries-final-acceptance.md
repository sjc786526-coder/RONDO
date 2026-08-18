# Plan 044 / Multi M-5 付费入口最终独立验收

日期：2026-08-18 ｜ 工作树 `worktree-044-multi-m5-real-workflow-and-nondegradation`
｜ 审查对象：`848a414` + `1c30098` + `0d40d3c`（门 1 付费入口、门 2 真实执行器，含前一轮审查者的窄修）
｜ 本轮无真实 API、无 Docker、无费用

## 结论

**验收通过（经本轮窄修后）。任务目标达成**：阶段 B 所缺的两个付费部件确实落地，方向正确、授权门有效、
证据分区没有被绕过。本轮又查出三处只在真实运行时才会显形的问题，已就地修好并各钉一条已验证的反向回归。

M-5 仍**未通过**，门 1 未通过，退化结论不存在。真实 API、Docker 与付费仍未授权、未执行。

## 一、复核确认无误的部分

- **授权门确实前置**。`gate1-paid` / `gate2-real` 先比对冻结口令，再 `load_provider_secret`；
  无口令退出 78，且在碰 `.env.local` 之前失败。两条 `just` 配方是纯 stub，永不转发口令。
- **密钥不落盘**。捕获代理只见预算代理的 `downstream_api_key`，真实 key 只在预算代理内存里；
  `requests.jsonl` 只有请求正文。`--strict-config` argv 里没有密钥。
- **公平性最小集成立**。团队 `-c` 项只来自 `team_capability_override_items(product)`，
  该函数对非 Multi 产品返回空元组；门 2 的 Codex 槽位 `product=None`，拿不到任何团队开关。
  成员模型 `gpt-5.6-sol` 与 Root 一致，捕获代理的 `model` 校验因此不会误杀成员请求。
- **门 2 没有套 v7 campaign**：`TerminalBenchRequest` 无 campaign id、无 preflight receipt。
- **重试策略是诚实的那一种**。门 1 只对 `infra_failed` 重试；`agent_failed` 与 `budget_stopped`
  都直接收尾。模型一次没跑通协作就如实记 FAIL，不会重掷到绿为止。
- **前一轮的三处预算修复复核无误**：`$4` 预留（可用额度 `$16`）、`run_stop_reason` 分类、
  账本槽位 `60+12+3=75`，逐条对着代码和账本语义确认。
- 本批次**没有动 `multidev/`**，无 Rust 回归面，因此未跑 Rust 门禁。

## 二、本轮发现的缺陷与修复

### F1（中）真实 Terminal-Bench 槽位把 `request_count` 写死成 1

一个 TB 槽位是一个宿主进程打很多次模型调用，写 `1` 有两个后果：归档行里的数字是假的；
`run_light_interleaved` 里那条 `request_count > max_requests_per_run` 判断成了死代码 ——
冻结授权清单答应用户的"每 run 请求上限 80"实际上**没有任何东西在执行**。

顺带确认了这个上限没法在代理层拦：`LoopbackResponsesProxy.max_logical_requests` 被校验成 `1..4`，
是给短诊断请求用的，传 80 会直接抛错。

**修复**：新增 `budget.run_request_count(ledger, run_id)`，从账本读该 run 真实登记的逻辑请求数
（未计费重试复用同一 request id，因此数的是逻辑请求不是 socket 尝试）；`_run_live` 的结果构造抽成
`_slot_result(parsed, run_id)` 并读这个真实值。超过 80 时走既有分支落 `infra_failed` +
`counts_as_effective=False`，不会以"Multi 未完成"的身份进退化判据。

### F2（中）离线捕获链在用户日常 shell 里会假失败

`test_capture_forwards_through_the_budget_proxy` 在本机直接跑是 **502 `unclassified_upstream_failure`**，
不是 200。原因是宿主导出了 `HTTP_PROXY=http://127.0.0.1:7897`，而 Python 的 `no_proxy` 匹配看不懂
本地代理管理器普遍导出的 `127.*` 通配，于是 `_UrllibTransport` 把本该指向环回假上游的测试请求
送进了用户的真实代理。前几轮报的 49/49、237/237 是清过代理的环境跑出来的，数字本身没问题，
但这个陷阱留着，等于在花钱前给自己埋一个"捕获链坏了"的假警报。

**修复**：`_UrllibTransport` 只在设了 `endpoint_override`（本就是 test-only 参数）时挂一个空
`ProxyHandler({})`。生产路径的 env 代理行为一个字没改 —— 真实 provider 仍照常走宿主代理。

### F3（小）门 2 真实批次不检查冻结 bundle 就开跑

`run_light_interleaved` 用 `require_frozen=False` 载入 runtime identity，且没传 `common_root`。
bundle 不在位时不是立刻说清楚，而是一槽一槽抛 `Gate2Error` 记 `infra_failed`，把 12 次 infra 预算
烧光才停批。

**修复**：`evidence_kind == "real_api"` 时 `require_frozen=True` 并传入 `common_root`，第一槽之前就失败。
fake / loopback 路径保持不变，没有 bundle 也照样能跑。

## 三、验收

- `tests.test_multi_m5` + `tests.test_multi_m5_exec` + `tests.test_api_budget_proxy`
  + `tests.test_terminal_bench` + `tests.test_terminal_bench_results` + `tests.test_binary_freeze`：
  **240/240**（含冻结二进制彩排）。
- 新增 3 条回归（`MultiM5PaidEntryHardeningTests`），**逐条确认在对应修复前失败**：
  `1 != 3`（请求数写死）、`URLError timed out`（环境代理劫持）、`M5ContractError not raised`（未检查冻结）。
  第三条最初写得不discriminate（靠 `_binary` 抛错碰巧通过），已改成用不碰 bundle 的执行器，
  并断言失败发生在第一槽之前。
- `just eval-lock` 通过。
- 未跑 Rust（本批次未动 `multidev/`）、未跑 Docker、未调真实 API、未产生费用。
- **门禁复现注意**：Python 门禁请在清掉 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` 的环境下跑。F2 修掉了
  测试自身这一处，但仓库其它用环回假上游的测试仍可能被宿主代理影响。

## 四、代用户做出的决策

| 项 | 决策 | 理由 |
|---|---|---|
| 三处缺陷是否阻断验收 | **不阻断，已就地窄修** | 都在花钱前才有意义，改动面共约 40 行，留到阶段 B 才发现的代价是真金白银 |
| 「每 run 请求上限 80」是执行还是删掉 | **执行**，用真实请求数喂既有判断 | 给用户的授权清单写了这个数就该作数；分类成 infra/不计有效，所以最坏结果是"不确定"而不是假退化 |
| 上限触发时算 infra 还是 budget | **infra_failed** | 它是编排器强加的截断，不是模型能力，也不是钱不够；走 infra 槽位并被重试是既有语义 |
| 门 1 跑出 `agent_failed` 要不要重掷 | **不重掷**，维持现状 | 重掷到绿就是硬约束 9 明令禁止的挑结果；3 次尝试是 infra 的上限，不是"再试一次运气" |
| 是否改 `$120` 硬上限或任何锁文件 | **不改** | 合同已冻结；三处修复只动实现，不碰 `eval/locks/*` |
| 门 1 沙箱 `network_access=true` 是否收紧 | **不收紧** | 它是阶段 A 冻结 argv 的一部分，改了会作废那五次全绿彩排；已在下方作为残留风险如实记下 |
| 阶段 B 真实付费 / Docker 授权 | **不代批，留给用户** | 真实花钱与不可逆外部操作，超出可代决策范围；清单见 ExecPlan §6 |

## 五、残留风险（不阻断，供授权时知情）

- **门 1 在宿主上跑真实模型**，配置是 `approval_policy=never` + `sandbox_mode=workspace-write` +
  `sandbox_workspace_write.network_access=true`。写入被限制在临时工作区，但模型执行的 shell 命令
  可以联网。门 1 的协作任务并不需要网络。这是阶段 A 冻结的运行配置，本轮不动；若下次重开门 1 合同，
  建议把 `network_access` 关掉。
- `run_gate1_paid` 不捕获 `ledger.ensure_run` 抛出的 `BudgetStopped`（槽位耗尽时会是裸 traceback
  而不是退出码 78）。门 1 先于门 2 执行，实际不可达，未修。
- `_slot_outcome` 里 `parsed.outcome is BUDGET_STOPPED` 是死分支（`parse_single_task_result` 不返回该值）。
  无害，留着。

## 六、边界

未合并 `main`、未推送、未删改 worktree/分支。真实 API、Docker 与付费仍未授权、未执行。
**不得**表述为 M-5 通过、门 1 通过或未见退化。
