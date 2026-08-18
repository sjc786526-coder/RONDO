# Plan 044 / Multi M-5 付费边界整改（第二轮）

日期：2026-08-18 ｜ 工作树 `worktree-044-multi-m5-real-workflow-and-nondegradation`
｜ 起因：终验判「验收不通过 / 目标失败」，列 2 项阻断 + 2 项伴随缺口
｜ 本轮无真实 API、无 Docker、无费用

## 结论

**4 项全部复现属实，已全部关闭**，每项各钉一条已验证的反向回归。上一轮我把请求上限和 Docker 证据
都做"一半"，终验指出的正是这两处半成品。

M-5 仍**未通过**，门 1 未通过，退化结论不存在。真实 API、Docker 与付费仍未授权、未执行。

## 一、阻断项

### A1 80 次请求上限不是并发硬边界（属实）

`RequestCappedLedger.reserve` 是 `snapshot()` → 判断 → `reserve()`。两次调用各自获取账本内部锁，
之间没有互斥。`LoopbackResponsesProxy` 跑在 `ThreadingHTTPServer` 上（`_LoopbackServer`，
`daemon_threads=False`），Multi 的 Root 与成员本来就并发发请求，所以这是真实付费风险。

**修复**：给包装层加 `threading.Lock`，把「读计数 + 预留」合成一个临界区。
充分性依据：真实槽位里交给代理的**唯一** reserve 路径就是这个包装层（编排器只对裸账本调
`ensure_run` / `run_stop_reason`，都不预留；`_charge` 只在无代理的 fake 路径），因此在包装层串行即可。
账本不会回调包装层，不存在锁反转。

**复现说明**：第一版并发回归用 `Barrier` 让 6 个线程同时起跑，**去掉锁后仍然通过** —— 起跑对齐
并不等于窗口打开，账本自身的锁把它们又排开了。改成注入一个 `snapshot()` 故意慢 50ms 的委托账本，
确定性地撑开 check/act 窗口：**去掉锁后上限 8 被冲到 13，加锁后恰好 8**。

### A2 付费 endpoint 没有被冻结（属实）

`require_frozen_provider` 把 `base_url` **记录**进归档，却从未与冻结值比较；锁里也根本没有这一项。
同一个 provider 名下换个 endpoint，密钥、工作区内容和费用就流向未批准的地址，校验照样通过。

**修复**：不退化锁新增 `provider_base_url: "https://www.cctq.ai/v1"`（就是授权清单里的 CCTQ relay），
`require_frozen_provider` 逐字比较（忽略结尾斜杠）。`load_nondegradation_contract` 要求该字段存在且
是 `https://`，缺失即 fail-closed。门 1 另有一个独立传入的 `upstream_base_url` 参数，也补了一致性校验，
不允许它悄悄指向别处。

## 二、伴随缺口

### A3 资源硬停止携带的 samples 被丢弃（属实）

上一轮只在**正常完成**路径归档 `docker_evidence`，而 `DockerResourceStop` 分支只写了 `str(exc)`。
撞线那一刻恰恰是证据最该留下的时刻。

**修复**：新增 `docker_stop_summary(exc)`，归档异常自带的 `samples` 与 `failed_probe`，
连同三条阈值常量。与正常路径共用 `_sample_rows` / `_stop_thresholds`。

### A4 `image_reference` 读了不存在的属性（属实）

`DockerImageIdentity` 的字段是 `image_reference`，我写的是 `getattr(identity, "reference", None)`，
实际恒为 `null`。**修复**：读正确字段，并一并记录 `image_id`。

## 三、验收

- `tests.test_multi_m5` + `test_multi_m5_exec` + `test_api_budget_proxy` + `test_terminal_bench`
  + `test_terminal_bench_results` + `test_binary_freeze` + `test_docker_supervisor`：**297/297**。
- 因改动了不退化锁的 schema，另跑 `test_config_hardening` + `test_contracts_and_evidence`
  + `test_fair_comparison`：**124/124**。
- 新增 5 条回归（`MultiM5ConcurrencyAndEndpointTests`），**逐条确认在对应修复前失败**：
  并发冲破上限（`13 != 8`）、换 endpoint 仍通过校验、门 1 接受非冻结上游、停止线 samples 缺失、
  `image_reference` 记成 `null`。
- CLI：`loopback` / `rehearsal` / `ready` / `gate2-fake` 退出 0；`gate1-paid` / `gate2-real`
  无口令退出 **78**。`just eval-lock` 通过，`git diff --check` 干净，worktree 干净。
- 未跑 Rust（未动 `multidev/`）、未跑 Docker、未调真实 API、未产生费用。
- **门禁复现注意**：Python 门禁须清掉 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` 再跑。

## 四、采纳终验的决策（无异议）

门 1 保持协议演示载体、口径不得包装成「有分析负载的真实任务协作」、两门判据独立但实际付费顺序
先门 1 后门 2、保留 Codex-first 且诊断只在退化后跑、结论只能表述为「小样本中未观察到稳定单向退化」——
这些与上一轮已写入锁 `scope_limits`、ExecPlan 决策 032/037 与子 WBS 的内容一致，本轮不改。

## 五、边界

未合并 `main`、未推送、未删改 worktree/分支。真实 API、Docker 与付费仍未授权、未执行。
**不得**表述为 M-5 通过、门 1 通过或未见退化。
