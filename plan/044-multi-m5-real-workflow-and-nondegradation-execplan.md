# Multi M-5 真实协作工作流与小样本不退化验收 ExecPlan

> 本计划是本任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述 Multi M-5；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 为唯一来源。

## 1. 目标

### 最终目标

在 M-0—M-4 已合入 `main` 的基础上，用真实运行回答 M-5 的两个独立问题：

> 一、RONDO Multi 在一次真实任务里是否真的形成了协作闭环 —— 团队工具被模型实际调用，Event/Version 发布、
> Root 唤醒、选择性路由、多作者追加与证据下钻确实发生，注意力按正常路径收尾，工作流本身达到预冻结的完成标准。
> 二、在固定的小样本同题运行中，Multi 相对冻结 Codex CLI `v0.147.0` 是否存在稳定的单向退化。

两个门相互独立，缺一不可；任一未满足，M-5 都不能关闭。本任务不主张 Multi 质量更优，不做统计显著性，
不建设新的大规模 benchmark。

任务分两个阶段：**阶段 A（离线准备与冻结，本次已授权）** 与 **阶段 B（真实运行与最终判断，需另行单独授权）**。
阶段 A 完成只能表述为“M-5 已具备真实运行条件”，**不得**表述为 M-5 通过。

### 完成/验收标准

**阶段 A（无费用、无 Docker、无真实 API）**

- [ ] Multi runtime bundle 已按产品身份冻结到 `eval-data/bin/rondo-multi/<bundle>/`，manifest 完整；
      其来源提交、构建命令与二进制哈希等身份事实同时写入本分支的受跟踪文件，使分支离开 ignored 目录仍可自证。
- [ ] 冻结 Codex bundle 与 Multi bundle 的身份、来源与必要伴随产物（如 code-mode host、bwrap 资源）已核验一致可用。
- [ ] **真实协作工作流合同已冻结**并写入受跟踪文件：运行载体与环境、给 Root 的任务陈述、成员规模上限、
      工作流自身的完成标准、以及“协作功能确实发生”的可观测判定口径（至少覆盖 Event/Version 发布、Root 唤醒、
      route、多作者追加、证据下钻五项）。不要求人为制造孤儿成员。
- [ ] **不退化运行合同已冻结**并写入受跟踪文件：`eval/tasksets/p2-b7-canary-catalog-v4.json` 的十任务、
      双方一致的任务条件、预先冻结且交错的执行顺序、Root/成员模型与推理配置、超时与请求上限、基础轮次、
      条件复跑规则、基础设施失败处理与尝试上限、价格快照来源与日期、费用预测与美元硬上限。
- [ ] 完成 M-5 所需的**最小**测评接线：Multi 侧以团队能力开启的状态运行，产品身份、运行合同版本与结果归档链路贯通。
      不新建通用框架，不改写历史结果，不动 Local 的既有公平运行合同。
- [ ] 在**无 API、无 Docker**条件下证明接线真的生效：至少一次 fake/loopback 级别的工作流演练，证明团队工具确实被
      注册并可被调用、投影与证据链路可观测、结果记录字段齐全；skip 或未运行不得写成通过。
- [ ] 受影响模块的定向门禁通过：`multidev/` 侧受影响的 Rust 定向测试（含既有 team 套件不退化）、
      `eval/` 侧受影响的 Python 测试与 `just eval-lock`；不扩大为全 workspace 测试。
- [ ] 输出**阶段 B 精确授权清单**（见 §3 硬约束 2 的条目），并在本计划“当前状态”记录，然后暂停等待授权。

**阶段 B（取得单独授权后）**

- [ ] 小规模连线检查通过：API、容器与结果归档链路可用，费用计入预算账本。
- [ ] **门 1 工作流**：冻结的真实协作工作流在功能开启状态下达到其预冻结完成标准，且五项协作能力确实被触发、
      注意力按正常路径收尾、无状态不变量失败。功能关闭、模型从未调用团队工具、工作流未完成，都不算通过。
- [ ] **门 2 不退化**：按 §4 运行合同取得完整有效证据，并给出结论。没有稳定单向退化时，结论只能表述为
      “该固定小样本下未观察到稳定单向退化”。
- [ ] 全部真实运行的结果、异常与重试、实际费用、双方二进制哈希与产品身份可核对；离线/fake/真实 API/Docker
      证据分区标注清楚。
- [ ] 本计划状态、`doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS.md`、`doc/WBS-COMPLETED.md` 与
      一份精炼 `agent_log/` 按各自职责同步；成果提交在 044 分支后停止，**未合并、未推送**。

## 2. 范围

### 允许修改

- `eval/` 中为 M-5 所需的最小接线、运行合同文件、结果归档与相应 Python 测试。
- `multidev/` 中因真实运行暴露的 M-1—M-4 小型正确性问题的窄修与对应回归测试。
- 本文件的“当前状态”与“关键决策记录”；一份精炼 M-5 `agent_log/`；完成时
  `doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS.md`、`doc/WBS-COMPLETED.md` 中各自职责内的当前事实/历史。
- 主工作区内 git-ignored 的产物目录（`eval-data/**`、build metrics、docker host volume、uv cache）—— 这是
  gitignore 造成的必要例外，见 §3 硬约束 1。
- 任务需要的普通依赖处理、生成文件/锁文件更新与只读源码/官方文档查询；生成差异用仓库既有工具产生并审查。

### 不允许修改

- `mydev/`、RONDO Local 行为与其既有公平运行合同、`training/`、Local 私有数据与模型工件。
- `codex-source-code/` 上游只读快照、`codex-doc/`、既有历史 plan/log/audit snapshot 的形成时点结论。
- 历史测评结果与既有 run 行（只增不改），历史 campaign identity 与预算账本。
- Multi 核心语义（M-1—M-4 已冻结的设计合同）、上游基线版本。
- 新建大规模 benchmark、统计显著性框架、通用测评框架、CI/PR、发布或任何远端资源。
- 主工作区内的受跟踪文件（受跟踪编辑一律在 044 worktree 内进行）。

### 不允许读取/查看

- `.env.local` 的任何内容。只允许静默检查存在性、非符号链接、权限 `0600` 与所需变量是否存在且非空；
  不得打开、搜索、打印、复制、记录或 source，也不得把它复制进 worktree。
- 与本任务无关的私有运行数据、模型权重、个人配置、其他 worktree 的未提交内容与项目外文件。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试、凑齐证据或提高局部指标而违反。

1. **隔离执行与 gitignore 例外**：所有受跟踪编辑、构建、测试与提交只在
   `.claude/worktrees/044-multi-m5-real-workflow-and-nondegradation`（分支
   `worktree-044-multi-m5-real-workflow-and-nondegradation`）进行。唯一例外是 git-ignored 资产：
   `eval-data/**`（冻结 bundle、uv cache、运行产物）、`eval/.venv`、`.env.local` 只存在于主工作区，
   允许从 worktree 通过 common-root 解析读写这些 ignored 路径，或在主工作区直接执行只涉及 ignored 产物的命令；
   但**不得**在主工作区修改任何受跟踪文件。不回退、覆盖、stash、移动或清理来源不明的修改，不进入其他 worktree 开发。
2. **阶段门**：阶段 B 开始前必须先提交阶段 A 成果并取得用户一次明确授权，授权清单至少冻结：API provider、
   Root/成员模型与 effort、真实工作流、十任务目录与执行轮次、最大有效运行数、基础设施尝试数与请求上限、
   当前价格与预计费用、美元硬上限、需要使用或拉取的明确 Docker 镜像、发送到外部模型的数据边界、预计执行时间范围。
   在取得该授权前：**禁止** Docker 拉取/构建/运行、真实 API、任何付费调用、真实本地模型加载与训练。
3. **资源与外部边界**：重型 Cargo 构建/测试必须走仓库根 `scripts/with-build-lock.sh`（优先已接入的 `just` 配方），
   `CARGO_TARGET_DIR` 位于受监控项目根内，遵守全局单构建、cgroup、项目容量与 Windows `C:` 实际余量门禁；
   拿不到锁或计数器时 fail-closed。阶段 B 的 Docker 与重型 Cargo、真实模型互斥，并发为 1，前后记录
   `docker system df` 与 Windows `C:` 实际余量，Docker 新增 40GB 告警 / 60GB 停止、`C:` 低于 80GiB 立即停止。
   不清理来源不明的既有镜像、容器、卷或缓存。禁止数据外发、远端写入与系统/全局配置变更。
4. **密钥边界**：真实运行只使用主工作区根 `.env.local` 经严格 `KEY=VALUE` 解析注入目标子进程的方式；
   不得当 shell 脚本 source，不得把密钥写入日志、结果、提交或提示词。
5. **两道门独立且不可互替**：门 1 只回答协作功能是否真的在工作，门 2 只回答有没有退化。
   内部的 Event/route/证据计数只作为“功能确实激活”的证据与诊断，**不得**混进跨二进制的任务完成率。
   门 1 不把“孤儿退休”列为必触发项。
6. **公平性最小集**（除产品本身的预期差异外双方必须一致）：相同任务、镜像、输入、验证器、沙箱、网络条件与任务超时；
   相同 Root 模型及适用推理配置；固定并交错的执行顺序；不得在看到首轮结果后临时选择任务、修改提示或调整超时；
   双方二进制哈希、产品身份、功能开关与运行合同版本必须记录。
   **Multi 的团队协议与成员调用属于被测产品能力，允许与 Codex 不同；不得为了形式上的完全相同而关闭 Multi 功能。**
7. **不退化判据**：不计算 `σ`/`delta`，不做统计显著性，不继承旧 M2 的机械阈值。只有在 §4 定义的三次有效观察都
   保持“Codex 完成、Multi 未完成”时，才判定为稳定单向退化。基础设施失败不计入有效结果。无法在冻结上限内取得完整
   有效证据时，结论为“未完成/不确定”，不得判定通过。Multi 完成而 Codex 未完成可如实记录，但本任务不据此宣称
   Multi 更优，也不扩大成统计意义或全面能力结论。
8. **预算与停止线**：真实运行必须走既有预算记账入口，实际花费不得超过授权的美元硬上限；触及费用、磁盘、
   Docker 增量、资源或范围任一停止线时立即停止并汇报，不得通过拆分、改口径或重开账本绕过。
9. **诚实记录**：fake/loopback、离线、真实 API、Docker 与真实模型证据必须分区标注；skip、未运行、无效比较与
   基础设施失败不得表述为通过；不得为凑绿弱化测试、门禁或判据；不得事后删题、改分母或挑选有利运行。
10. **允许自修复与有界重跑**：编译、格式、接线、fixture、容器瞬时故障、API 瞬时错误、归档与分页等窄问题，
    应自行分析、窄修、补必要回归并在冻结上限内重跑，**不因一个窄修就能解决的小问题停下来汇报**。
    只有触及原则性边界、需要未授权的高危能力、必须改变计划合同、资源/预算门禁持续不可满足，或多次合理尝试后
    仍有实质阻塞时才暂停汇报。不得用重试绕过门禁或挑选结果。
11. **范围熔断**：若真实工作流暴露出需要重新定义 Multi 核心语义的重大缺陷，停止 M-5、保留证据并汇报，
    由后续任务单独规划修复，不在本任务内改设计合同。
12. **交付边界**：完成后只在 044 分支提交，不合并 `main`、不推送、不删除或重命名 worktree/分支，等待用户批准。
    完成前只读检查主工作区与各 worktree 的 Git 状态与意外生成物概况，不读取其他 worktree 的未提交内容。

## 4. 不退化运行合同

以下是门 2 的判据骨架，属于硬约束；具体实现路线由执行者决定。

- 任务集：`eval/tasksets/p2-b7-canary-catalog-v4.json` 的固定十任务，不另选、不增删。
- 首轮：每个任务分别运行 Codex 与 Multi 各一次，共 **20 个有效运行**；双方顺序预先冻结并按任务交错执行。
- 条件复跑：只有出现“Codex 完成、Multi 未完成”的任务，才对**双方各追加两次**有效运行。
- 判定：仅当该任务的三次有效观察都保持“Codex 完成、Multi 未完成”，才判定为稳定单向退化。
- 基础设施失败不计入有效结果，只允许在冻结的尝试次数与预算内原槽位重试。
- 触发退化判定时，本任务的责任是如实记录并回头定位原因；是否在本任务内窄修由 §3 硬约束 10/11 决定。

## 5. 软性建议

以下是基于 `main@45efac6` 实时代码给出的高性价比候选，**不是固定约束**。执行者可依据实时源码、实际运行结果与
复杂度采用更小、更清晰或更可靠的等强方案，并在关键决策记录中简述取舍。

- **工作流载体的选择是本任务最大的不确定点，值得先想清楚**。用户草案建议直接用 P2/B7 v4 的 `fix-git`；
  它的好处是环境、镜像与验证器都已冻结。风险是这类单人小任务里，模型可能自己直接做完，团队工具一次都不调用，
  导致门 1 因为“任务太简单”而不成立 —— 那不是产品缺陷。可考虑的等强做法包括：在同一冻结容器内换一份明确要求
  分派与证据汇总的任务陈述；或另造一个受控的本地协作场景作为门 1 载体，门 2 仍严格用 v4 十任务。
  选哪条由执行者决定，但工作流的完成标准必须在真实运行前冻结。
- 花钱之前，先用 fake/loopback 把工作流骨架跑通一遍通常最省钱：能提前暴露“团队工具没注册”“投影没进上下文”
  “成员没被 spawn”“结果字段缺失”这几类接线问题。
- 门 2 不继承 `σ`/`delta`，因此不必强行套用完整 v7 campaign 流程；只要满足 §3 硬约束 6 的公平性最小集、
  预算记账与结果归档，可以走更轻的 runner 路径。若复用 campaign 设施更省事，也完全可以。
- Multi 侧需要团队能力开启：参考 `multidev/codex-rs/core/tests/suite/team_world_state.rs` 的做法
  （`Feature::Collab` + `Feature::MultiAgentV2` + `multi_agent_v2.team_state_enabled`），
  eval 侧已有 `-c` override 的成熟通道（见 `eval/rondo_eval/terminal_bench/adapters.py`）。
  产品身份唯一映射仍是 `eval/rondo_eval/contracts.py` 的 `product_layout()`。
- `eval-data/` 与 `eval/.venv` 只在主工作区存在。既有 `just` 配方多数已用 `git rev-parse --git-common-dir`
  解析主根，可以直接从 worktree 调用；`eval-sync`/`eval-test`/`eval-lock` 用的是相对路径，从 worktree 运行时
  按 Plan 022 的既有做法用 `UV_PROJECT_ENVIRONMENT`/`UV_CACHE_DIR` 指向主根即可（`eval` 是 `package = false`，
  跑的仍是 worktree 里的源码）。
- 冻结 bundle 落在 ignored 目录，分支里看不到；建议把 bundle 目录名、source commit、二进制 sha256 写进受跟踪的
  运行合同文件，避免将来只看分支无法复原当时用的是哪个产物。
- 价格与费用预测：只读查询官方定价页并记录快照日期与来源链接；预测按“十任务 × 双侧 × 轮次 × 单次预估 token”
  给出量级即可，硬上限留出条件复跑与基础设施重试的余量。
- 定向门禁建议范围：`codex-team-state`、既有 `suite::team_world_state` / `team_routing` / `team_evidence` /
  `team_coordination` 不退化、实际受影响的 core 子集，以及 `eval/` 侧受影响的 Python 测试；不跑全 workspace。
- 提交建议按“阶段 A 冻结与接线”“阶段 B 运行与结论”两个批次形成清晰提交，便于审查。

## 6. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。
> §1 验收框保持合同原文不改写；阶段完成情况以本节为准。

### 已完成

- 现场基线未变：`main` = `origin/main` = `45efac6`，主工作区受跟踪文件干净。044 工作树分支
  `worktree-044-multi-m5-real-workflow-and-nondegradation`；测量树
  `.claude/worktrees/044-m5-multi-bundle-measurement` 仍 detached 于
  `7a2ff684c504c7530660f9a33a372daa949bdb00`，未在其中开发。
- **门 1 合同**：`eval/locks/multi-m5-workflow-v1.json`。载体是 host `codex exec` +
  `eval/fixtures/multi-m5-collab-v1/` + `eval/templates/multi-m5/collab-workflow-instruction-v1.md`
  （sha `9879529f…d5333`），不是 TB `fix-git`。完成标准 = `TEAM_REPORT.md` 含 finding 行且六项协作谓词
  全真；孤儿退休不是必触发项。Docker 不用于门 1。
- **门 2 合同**：`eval/locks/multi-m5-nondegradation-v1.json`。十任务来自
  `eval/tasksets/p2-b7-canary-catalog-v4.json`（catalog sha `00b83e44…57ddf`），交错
  `task_major_codex_then_multi`，轻 runner，不套 v7 campaign，不计算 σ/delta。价格快照
  2026-08-17 官方页；硬上限 $120。
- **Multi runtime 已冻结**（ignored 产物 + 受跟踪身份）：
  `eval-data/bin/rondo-multi/7a2ff684c504c7530660f9a33a372daa949bdb00-x86_64-unknown-linux-musl-runtime-bundle/`
  已 `verify-runtime`。受跟踪锁 `eval/locks/multi-m5-runtime-v1.json` `status=frozen`：
  `codex_sha256=2f5f25e0…0c32`（legacy CLI）、`code_mode_host_sha256=eb54cac2…6705`（本次 musl host）、
  `bwrap_sha256=77360cb7…2c4c`（与 Codex 同资产）、`manifest_sha256=1c782d1d…6769`。
  对照 Codex bundle 身份见该锁 `codex_baseline`。重建 CLI sha `74989060…d266` **不得**写入 runtime 锁。
- **最小接线**：`TEAM_CAPABILITY_MULTI_TOML` 单条 inline TOML 只注入 Multi；Codex/Local 禁止。
  TB adapter、loopback、归档与 Python 合同测试已落地。根 `just eval-sync`/`eval-test`/`eval-lock`
  从 worktree 经 `git-common-dir` 解析主根 venv；新增 `just eval-multi-m5-loopback`。
- **无 API 演练**：`just eval-multi-m5-loopback` 通过；`loopback_tool_round_trip=true`，
  `counts_as_effective=false`，`evidence_kind=loopback`。证明团队工具在 `code_mode_host=true` 下已注册
  并可走 `team_publish` 往返。**不是门 1 真实通过。**
- **定向门禁**（均无 API / 无 Docker）：
  - `tests.test_multi_m5` 15/15
  - `tests.test_binary_freeze.MultiProductFreezeTests`
  - `tests.test_terminal_bench.TerminalBenchTests.test_adapter_run_uses_safe_permissions_and_no_secret_in_exec_argv`
  - `just eval-lock`
  - 清代理后 `just test -p codex-team-state -p codex-core -E 'package(codex-team-state) or test(suite::team_world_state) or test(suite::team_routing) or test(suite::team_evidence) or test(suite::team_coordination)'`：**142/142**（metrics `eval-data/build-metrics/rondo-multi-m5-team-tests-noproxy`）。带残留 `HTTP_PROXY` 的首次 15 fail/1 timeout **不可复用**。
- 阶段 B 授权清单已写入本节，执行暂停等待授权。

### 当前工作

- 阶段 A 收口：044 分支提交后停止，等待阶段 B 授权。不合并不推送。

### 本任务剩余步骤

- 阶段 A：044 分支已提交；独立审核无 P0。然后停止。
- 阶段 B（**仅在用户按下列清单授权后**）：按已冻结合同落地 host 门 1 runner 与门 2 轻量交错执行面（当前只有 loopback CLI）→ 连线检查 → 门 1 host 工作流 → 门 2 十任务 → 复核结果与费用 → 同步文档与日志 → 044 分支再提交后停止。

### 阻塞项

- 阶段 B 所需的 Docker、真实 API 与付费授权尚未取得，按 §3 硬约束 2 处理。
- `.env.local` 已确认存在、非符号链接、权限 `0600`。未打开文件。阶段 B 开始前执行者须静默确认
  `OPENAI_API_KEY` 存在且非空（relay / CCTQ Responses），不得记录其值。

### 当前验收状态

- 规划现场核对、worktree 创建与 ExecPlan：已完成。
- **阶段 A：已完成准备。** 含义仅是「M-5 已具备真实运行条件」。**不得**表述为 M-5 通过、门 1 通过或未见退化。
- 阶段 A 已落地：bundle 冻结与身份自证、Codex/Multi 核验、工作流合同、不退化合同、最小接线、
  无 API loopback、定向门禁、阶段 B 授权清单。loopback 证明的是团队工具注册、一次 `team_publish`
  往返与归档字段；**没有**证明投影进入后续采样或证据下钻。那两件事仍由阶段 B 门 1 真实运行判定。
- 阶段 B：未授权、未开始。§1 阶段 B 五项全部未做。

### 阶段 B 精确授权清单

取得一次明确授权后才可开始。授权范围建议按下表一次性批准或驳回；未列项仍禁止。

| 项 | 冻结值 |
|---|---|
| API provider | `rondo.local.toml` 的 `paid_eval.active_provider = "relay"`（CCTQ Responses；`api_key_env = OPENAI_API_KEY`）。不改官方入口，不把密钥写入文档或提示词。 |
| Root / 成员模型 | `gpt-5.6-sol` + `medium`（两侧相同） |
| 门 1 | host `codex exec` 协作 fixture，无 Docker；最多 3 次尝试、单次 1800s |
| 门 2 | v4 catalog 十任务；`task_major_codex_then_multi`；条件复跑仅当「Codex 完成、Multi 未完成」时双方各加两次 |
| 最大有效运行 | 60（基础 20 + 条件最多 40） |
| 基础设施 | 每槽最多 3 次尝试；infra 总上限 12；infra 不计有效结果 |
| 每 run 请求上限 | 80 |
| 价格快照 | 2026-08-17 官方页：input $5 / cached $0.50 / output $30 per 1M；长上下文 272k input×2 output×1.5；cache_write 1.25 |
| 费用 | 点估计约 $40；合同内最坏约 $96；**硬上限 $120**。账本批次 `multi-m5-phase-b` |
| Docker | **只为门 2**。十个 digest 钉死镜像（见 `eval/locks/multi-m5-nondegradation-v1.json` 的 `docker_images`）。不拉其它镜像，不跑完整数据集。门 1 不用 Docker。 |
| 外发边界 | 任务输入、工作区内容与模型可见工具结果进入 Responses；密钥、`.env.local`、个人配置不进提示词或结果文件 |
| 预计时间 | 门 1：数十分钟级，最坏约 1.5 小时。门 2：无条件复跑时数小时到十余小时；若多题触发复跑或打满超时，日历时间可到一天以上。全局串行，与重型 Cargo / 本地模型互斥。 |
| Git | 阶段 B 成果仍只提交 044 分支；合并 `main`、推送、删除/重命名 worktree 仍须另批 |
| 明确不做 | 本地模型加载、训练、发布、远端写入、清理来源不明的 Docker 对象、改 Local 公平合同、宣称 M-5 通过（除非两道门都按合同完成） |

十个门 2 镜像：

- `alexgshaw/db-wal-recovery@sha256:0e33ea5ec823975d1bd6c3778395c9f94251dd88f571146057bff6adb7e4594e`
- `alexgshaw/extract-elf@sha256:6932e4cb318464307eacd497ef8dc617eaf551b6a90231f815ec0b911895cfed`
- `alexgshaw/filter-js-from-html@sha256:92acda0f124b988036a6f426ce0bc47fac19f5efe9fc5e6ea3ea52ccb075d0a4`
- `alexgshaw/fix-git@sha256:389b9c8247610c2c5be080b1ac00429007c2c69bf57f7f26c79f0f75ba2d5c74`
- `alexgshaw/headless-terminal@sha256:eb7e209672bf6cef2785fafd9e13509b10626c327bcc2b37f5bf40ca83eaf3aa`
- `alexgshaw/openssl-selfsigned-cert@sha256:4c948a4e630af2435ae0a19108fc0814a946ac2fa29a512469e0fc77b38c8c12`
- `alexgshaw/polyglot-c-py@sha256:0f1c3b7816d70cf5551573fd6aeef76893f2ae3000be2419997b6871b5d987ed`
- `alexgshaw/sanitize-git-repo@sha256:4b5234da5bb0d67f3b0bf8db40a2883c07a5219f62b64c2bf9ff1ac84cd0f672`
- `alexgshaw/sqlite-db-truncate@sha256:aabac93c93bd1f310e6a6fb893911d7735026ed18491c72133c9196a09092ca4`
- `alexgshaw/vulnerable-secret@sha256:61ebb40454dd103aa2f7e71ad6dafd91cf2b301e6bb07e69d5b472412d1ee15b`

### 交接边界

- 阶段 A 完成后本计划仍作为任务合同；阶段 B 不另开 plan，按本节清单授权后继续同一 044 分支。
- 跨任务路线只链接 `doc/WBS/multi-agent-trusted-evidence.md`，不在此规划 M-5 之后的工作。

## 7. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | M-5 拆成阶段 A（离线冻结，本次授权）与阶段 B（真实付费运行，另行授权） | 把“无费用准备完成”和“真实付费验收通过”严格分开，避免用准备完成冒充 M-5 通过 | 任务编排 | 已采纳 |
| 002 | 门 1 工作流与门 2 不退化相互独立、缺一不可 | 二者回答不同问题，内部协作计数不能当能力分，任务完成率也证明不了协作在工作 | 验收口径 | 已采纳 |
| 003 | 不退化只用“完成/未完成”，三次有效观察全部单向失败才判退化 | WBS 已明确不继承 `σ`/`delta`，小样本下统计判据不稳定且与轻量定位冲突 | 判据 | 已采纳 |
| 004 | 固定复用 P2/B7 v4 十任务，不另选任务 | 任务、镜像与验证器已冻结，避免临时选题带来的选择偏差 | 任务集 | 已采纳 |
| 005 | Multi 侧团队能力保持开启，视为被测产品能力 | 关掉团队功能求形式对称等于不测产品 | 公平性 | 已采纳 |
| 006 | 工作流载体不预先写死，由执行者冻结后再运行 | 载体选择直接决定门 1 能否成立，需要结合实时代码判断；WBS 也把它交给本阶段 plan | 门 1 | 已采纳 |
| 007 | 冻结 bundle 等 ignored 产物写在主工作区，身份事实同步进受跟踪合同文件 | `eval-data/` 全局 ignored，分支内不可见，否则将来无法复原当时产物 | 交付与可复原性 | 已采纳 |
| 008 | 窄问题允许自主窄修并有界重跑，不因小失败停机汇报 | 给实现与真实运行合理冗余，同时保留原则性边界 | 执行流程 | 已采纳 |
| 009 | 044 只提交工作树分支；合并与推送等待用户批准 | 遵守本次明确交付边界 | Git 交付 | 已采纳 |
| 010 | 门 1 不用 TB `fix-git`，改用受控 host 协作 fixture | 单人小任务里模型可能自己做完、团队工具一次都不调用，门 1 会因任务过简而不成立 | 门 1 载体 | 已采纳 |
| 011 | 门 2 走轻量交错 runner，不套 v7 campaign / preflight receipt | 不继承 σ/delta，完整 campaign 对小样本完成/未完成检查过重 | 门 2 设施 | 已采纳 |
| 012 | Multi freeze 不共享 Local 的 0.147.0 lockfile checksum | Multi 与 Local 的 Cargo lock 不是同一份身份；强行共用会把错误 lock 写进 Multi bundle | binary freeze | 已采纳 |
| 013 | 冻结源码用测量树 `044-m5-multi-bundle-measurement`（detached `7a2ff68`），不在其中开发 | 冻结身份钉在 ExecPlan 提交，避免 044 未提交改动进入 binary provenance | 冻结流程 | 已采纳 |
| 014 | 团队 TOML 使用 `non_code_mode_only=false` | eval 固定 `features.code_mode_host=true`；为 true 时 spawn/团队工具不会在 Direct 路径注册 | Multi 运行配置 | 已采纳 |
| 015 | 团队能力必须是恰好一条 inline TOML，且只给 Multi | 拆成 `enabled=true` 再写嵌套键会互相覆盖；Codex `--strict-config` 会拒绝未知键 | adapter / 公平性 | 已采纳 |
| 016 | Multi musl freeze 身份包含 `CARGO_BUILD_JOBS=2` | 本机约 27GiB，不限并行会触发 `host_mem_available_below_floor` | 冻结身份 | 已采纳 |
