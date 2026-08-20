# Plan 044 / Multi M-5 付费边界整改

日期：2026-08-18 ｜ 工作树 `worktree-044-multi-m5-real-workflow-and-nondegradation`
｜ 起因：第三轮独立终审判「不通过，暂不应授权付费」｜ 本轮无真实 API、无 Docker、无费用

## 结论

终审列的 **6 项阻断问题全部复现属实，已全部关闭**，每项各钉一条已验证的反向回归。
次要项按下节逐条处理：4 项已修，3 项经核对后**不改**并给出依据。

M-5 仍**未通过**，门 1 未通过，退化结论不存在。真实 API、Docker 与付费仍未授权、未执行。

## 一、阻断项修复

### B1 门 2 会在失败结论下返回成功状态（属实）

`__main__.py` 只看 `stopped`，所以 `stable_one_way_degradation`、某槽三次 infra 用尽、
`uncertain`、有效运行不完整都可能退出 0，而且根本没打印 `verdicts`。

**修复**：新增 `gate2_passed(contract, verdicts, stopped)` —— 只有「未停批 + 十个任务都有判定 +
全部 `no_stable_one_way_degradation`」才算通过。`run_light_interleaved` 返回 `passed`，
`gate2-real` / `gate2-fake` 都据此决定退出码，并把 `verdicts` 打进输出。

### B2 「每 run 最多 80 请求」没有真正限制外部调用（属实）

上一轮我把它做成了事后分类，终审说得对：第 81 次及以后仍会真实发出、计费、外发内容。
补充一个事实：这个上限**无法**用预算代理的 `max_logical_requests` 实现，该参数被校验成 `1..4`。

**修复**：新增 `RequestCappedLedger`，包在账本外层拦 `reserve()` —— 每个逻辑请求在任何字节离开进程
**之前**都会走这里。到达上限即 `stop_run(logical_request_limit_exceeded)` 并抛 `BudgetStopped`，
第 81 次请求不再发出。停止原因与「钱不够」分开：钱是全批共享的、耗尽即停批；请求上限是每 run 的，
只结束当前槽位，记 `infra_failed` / 不计有效，下一次尝试用新 run id 拿到新的请求额度。

### B3 冻结的付费配置没有绑定到真实运行（属实，且已在漂移）

`_run_live` 只比对主模型名，其余 provider 身份、effort、价格、重试策略全部来自可变的
`rondo.local.toml` —— 而**预算代理正是用这些费率给 $120 记账**。改一下那个文件就能悄悄改变
授权的美元上限实际能买到多少。

**修复**：新增 `require_frozen_provider()`，把 provider id / API 类型 / 主模型 / effort /
`max_attempts` / 未计费重试状态码 / 全部 7 项费率与长上下文阈值逐项对锁文件核验，不符即拒。
两道门都调用，并把生效身份写进每一行归档（含 `provider_profile_sha256`、`provider_config_sha256`）。
实测当前机器配置：费率全部一致，**快照日期确实不同** —— 锁 `2026-08-17` vs 配置 `2026-08-11`。
费率决定花钱、日期只是出处，因此日期差异记录在每行而不阻断运行。

### B4 Docker 硬停止会被当成普通 infra 重试（属实）

80GiB 地板与 60GB 增量上限抛的是 `DockerSupervisionError`，被 `except RuntimeError` 压成
`Gate2Error`，然后照常重试三次并继续跑整批 —— 直接违反 CLAUDE.md §3 的「立即停止」。

**修复**：`docker_supervisor` 新增 `DockerResourceStop(DockerSupervisionError)` 子类，只在这两处
容量停止线抛出（子类化，现有 `except DockerSupervisionError` 的调用方行为不变）。
门 2 单独捕获它并**立刻停批**，不消耗槽位重试。

### B5 Docker 前后证据没有进入 M-5 归档（属实）

**修复**：新增 `docker_summary()`，把 Harbor 返回的 `docker_evidence` 投影进槽位行 ——
每个 sample 的 phase / `docker system df` 总量 / Docker 与任务增量 / VHDX 增量 / data-root 与宿主
剩余空间，加上 warnings、VHDX 峰值证据和 40GB / 60GB / 80GiB 三条阈值常量。
刻意只存有界投影，不把整份 `docker system df` 塞进每一行。

### B6 门 1 没有真正覆盖"真实任务上的协作"（属实，但**决定不改载体**）

事实核对无误：`eval/fixtures/multi-m5-collab-v1/NOTES.md` 就是那一行答案本身，指令模板逐步规定
调哪些工具、什么顺序。门 1 证明的是「真实模型会按协议驱动团队机制，且机制端到端可观测」，
不是「Multi 在有分析负载的任务上更强」。

**决定：保持冻结载体不动，改为把话说准。** 依据：

- 这是阶段 A 冻结的合同（`instruction_sha256` + `fixture_notes_sha256`），改它等于改 ExecPlan
  的完成标准，按本计划抬头必须先请示用户，不属于可代决策范围。
- 决策 010 冻结这个载体正是为了避开相反的失效模式：单人小任务里模型自己做完、团队工具一次都不调，
  门 1 会因「任务太简单/太难」而不成立 —— 那不是产品缺陷。
- 改载体会作废已复核的五次全绿彩排，而新载体在花钱之前**无法离线验证**。付费前夜换掉唯一验证过的
  载体，风险高于收益。
- 门 1 的五项能力（spawn / 同 Event 多作者 / route / 成员证据 / Root 唤醒）依然由真实模型触发并
  逐条判定，`team_evidence` 要求成员作者的 Version 有真实证据支撑 —— 成员确实在干活。

**代价已写进合同**：锁文件新增 `scope_limits`，`purpose` 改写为明确声明「协议演示级载体，
不证明 Multi 在有分析负载的任务上更强，也不单独满足 WBS 的『真实任务上跑通完整协作语义』；
该表述需要门 1 与门 2 合起来读」。同步写进 ExecPlan 决策 032 与方向 3 子 WBS。

## 二、次要项

| 项 | 处理 | 依据 |
|---|---|---|
| 门 1 通过时未要求 `codex exec` 返回码为零 | **已修** | 崩溃的运行不能算通过。先实测彩排 rc=0，确认这条收紧不会误杀正常运行；它只能把「通过」变成「失败」，反向不可能 |
| 真实记录未绑定 eval harness HEAD | **已修** | 新增 `harness_identity()`，每行付费记录带 `harness_commit` 与 `harness_dirty`。脏树如实记录而不拒绝 —— 运行确实发生了，瞒下来更糟 |
| worktree 不干净（`training/local-approval-l6/__pycache__/`） | **已修** | `.gitignore` 只忽略 `/eval/**/__pycache__/`，补一条全局 `__pycache__/`。不删来源不明的既有文件 |
| `doc/WBS-COMPLETED.md` 文件尾多余空行 | **已修** | |
| 门 2 未验证门 1 已通过，可绕过门 1 花预算 | **不改** | ExecPlan §1 明写「两个门相互独立，缺一不可」，强制顺序反而违反合同。槽位也不会饿死：账本 75 = 60+12+门 1 的 3，门 2 最多吃 72 |
| 固定 Codex 先、Multi 后，存在顺序/缓存偏差 | **不改，但如实记录** | `base_order` 是冻结合同。且方向相反：同一任务 Codex 先跑会替 Multi 预热镜像，偏差利于 Multi，而门 2 只把「Codex 完成 + Multi 未完成」判为退化 —— 这让退化判定更保守，不会造出假退化。它确实削弱「未见退化」这一侧的强度，已写进锁的 `scope_limits` |
| 稳定退化诊断槽位只有文字、无可执行路径与预算归属 | **不改** | 决策 021 明确「真退化再跑 `V2 开 / team_state 关`，本轮不预跑」，省钱且不预设结论。本轮十个任务都没跑过，无从归属预算 |

## 三、验收

- `tests.test_multi_m5` + `test_multi_m5_exec` + `test_api_budget_proxy` + `test_terminal_bench`
  + `test_terminal_bench_results` + `test_binary_freeze` + `test_docker_supervisor`：**292/292**。
  （本轮动了 `docker_supervisor.py`，故把它的套件一并纳入。）
- 新增 8 条回归（`MultiM5PaidBoundaryTests`），**逐条确认在对应修复前失败**：
  5 条行为回归在定点回退后失败（退化批次仍报成功、请求上限停批而非停槽、Docker 容量停止被重试、
  Docker 证据缺失、崩溃的门 1 仍判通过），另 3 条依赖修复前根本不存在的符号。
- CLI 端到端：`loopback` / `rehearsal` / `ready` / `gate2-fake` 退出 0；
  `gate1-paid` / `gate2-real` 无口令退出 **78**，且在加载 `.env.local` 之前失败。
- `just eval-lock` 通过。worktree 干净。
- 未跑 Rust（未动 `multidev/`）、未跑 Docker、未调真实 API、未产生费用。
- **门禁复现注意**：Python 门禁须在清掉 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` 的环境下跑。

## 四、边界

未合并 `main`、未推送、未删改 worktree/分支。真实 API、Docker 与付费仍未授权、未执行。
**不得**表述为 M-5 通过、门 1 通过或未见退化。
