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
- **最小接线**：`features.multi_agent_v2` 仍是单条 inline TOML，只注入 Multi；另加
  `agents.default_subagent_model` / `agents.default_subagent_reasoning_effort`，并关闭
  `expose_spawn_agent_model_overrides`。Codex/Local 禁止这些项。TB adapter、loopback、归档与
  Python 合同测试已落地。根 `just eval-sync`/`eval-test`/`eval-lock` 从 worktree 经
  `git-common-dir` 解析主根 venv；新增 `just eval-multi-m5-loopback`。
- **无 API 演练**：`just eval-multi-m5-loopback` 通过；`loopback_tool_round_trip=true`，
  `counts_as_effective=false`，`evidence_kind=loopback`。证明团队工具在 `code_mode_host=true` 下已注册
  并可走 `team_publish` 往返。**不是门 1 真实通过。**
- **定向门禁**（均无 API / 无 Docker）：
  - `tests.test_multi_m5` 25/25（门 1 窄整改 + 采集自查后）
  - `tests.test_binary_freeze.MultiProductFreezeTests`
  - `tests.test_terminal_bench.TerminalBenchTests.test_adapter_run_uses_safe_permissions_and_no_secret_in_exec_argv`
  - `just eval-lock`
  - 清代理后 `just test -p codex-team-state -p codex-core -E 'package(codex-team-state) or test(suite::team_world_state) or test(suite::team_routing) or test(suite::team_evidence) or test(suite::team_coordination)'`：**142/142**（metrics `eval-data/build-metrics/rondo-multi-m5-team-tests-noproxy`）。带残留 `HTTP_PROXY` 的首次 15 fail/1 timeout **不可复用**。
- 阶段 B 授权清单已写入本节。用户要求先完成门 1 窄整改并复验，本轮不进入阶段 B。

### 当前工作

- 阶段 A 已复验通过并收口（报告 `agent_log/2026-08-18-010000-plan044-m5-gate1-attribution-rereview.md`）。
- **阶段 B 离线前置准备已完成**：门 1 runner 与彩排 stub、门 2 轻量交错执行面（fake）、$120 预算记账、
  归档落盘、就绪自检五项全部落地；**门 1 完整离线彩排连续五次全绿**，真实 canonical 状态已独立复核。
  详见 `agent_log/2026-08-18-030000-plan044-m5-phase-b-preparation.md`。
- **前置准备经独立审查发现门 1 模板与判据不自洽，已整改**：冻结模板按字面执行必然过不了
  `two_authors`（Root 从不发布 Version，而 `team_update` 不产生 Version），已在冻结二进制上实测复现；
  模板补入 Root 在同一 Event 发布的步骤、重算 `instruction_sha256`，并新增两条回归把模板与判据绑定。
  顺带把 `gate2` 的 `evidence_kind` 写死为 `fake` 这处付费陷阱就地修掉。
  详见 `agent_log/2026-08-18-070000-plan044-m5-template-predicate-remediation.md`。
  复验通过：`agent_log/2026-08-18-090000-plan044-m5-template-remediation-rereview.md`。
- **门 1 付费入口与门 2 真实执行器已落地，仍锁在授权门后**：`run_gate1_paid` 走
  CaptureProxy(forward) → LoopbackResponsesProxy → HTTPS provider；`TerminalBenchSlotExecutor`
  走既有 TB adapters/runner/results，不套 v7 campaign。CLI / `just` 不内嵌授权口令，无口令时
  退出码 78 且不加载 `.env.local`。未跑真实 API、未拉 Docker、未产生费用。
  独立审查先因门 2 `$8`/`$24` `ensure_run` 冲突判 FAIL，已修并复审通过。
  详见 `agent_log/2026-08-18-110000-plan044-m5-paid-entries.md`。
- **付费入口独立验收通过（审查者窄修后）**：预算这一层查出三处只会在真花钱时暴露的缺陷，均已修复
  并各钉一条反向回归 —— 门 1 可用额度因 Guardian 附加预留只有 `$8`（等于点估计，余量 1.0 倍）；
  预算掐断被记成 `agent_failed`，门 2 还会 `counts_as_effective=True` 污染退化判据；
  共享账本槽位按 `60+12` 算，没给门 1 的 3 次尝试留位。
  详见 `agent_log/2026-08-18-130000-plan044-m5-paid-entries-acceptance-review.md`。
- **最终独立验收通过（审查者窄修后）**：又查出三处只在真实运行才显形的问题，均已修复并各钉一条
  已验证的反向回归 —— 真实 TB 槽位把 `request_count` 写死成 1，使冻结的「每 run 80 请求」上限成为死代码；
  离线捕获链被宿主 `HTTP_PROXY` 劫持（Python 的 `no_proxy` 不认 `127.*` 通配），在用户日常 shell 里假失败 502；
  门 2 真实批次 `require_frozen=False`，bundle 不在位时要烧完 12 次 infra 才停。
  门禁 **240/240** + `just eval-lock`。详见
  `agent_log/2026-08-18-150000-plan044-m5-paid-entries-final-acceptance.md`。
- **第三轮终审判「不通过、暂不应授权付费」，6 项阻断已全部关闭并各钉反向回归**：
  门 2 在退化/证据不完整时仍退出 0；「每 run 80 请求」只是事后分类、第 81 次仍会真实发出计费；
  付费配置未绑定冻结合同（预算代理拿 `rondo.local.toml` 的费率给 $120 记账，实测快照日期已漂移）；
  Docker 的 80GiB/60GB 硬停止被当普通 infra 重试；Docker 前后证据未进归档；门 1 载体只是协议演示。
  前五项已修，第六项**决定保持冻结载体**并把边界写进锁文件与文档（理由见决策 032）。
  门禁 **292/292**（含 `test_docker_supervisor`）。详见
  `agent_log/2026-08-18-170000-plan044-m5-paid-boundary-remediation.md`。
- **第四轮终验判「不通过」，2 项阻断 + 2 项伴随缺口已全部关闭**：请求上限是 `snapshot→判断→reserve`
  的 TOCTOU，代理跑在 ThreadingHTTPServer 上、Root 与成员并发，实测上限 8 被冲到 13 → 包装层加锁合成
  单一临界区；付费 endpoint 只记录不比较、锁里也没冻结 → 锁新增 `provider_base_url` 并逐字校验，
  门 1 的独立上游参数一并绑定；资源硬停止携带的 samples 被丢弃 → 新增 `docker_stop_summary`；
  `image_reference` 读了不存在的属性恒为 null → 读正确字段。门禁 **297/297** + 配置类 **124/124**。
  详见 `agent_log/2026-08-18-190000-plan044-m5-paid-boundary-remediation-2.md`。
- **Python 门禁复现注意**：必须清掉 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` 再跑，否则环回假上游会被宿主代理劫持。
- 044 分支提交后停止。未合并、未推送。真实 API、付费与 Docker 仍未授权、未执行。

### 本任务剩余步骤

- 按本节「阶段 B 精确授权清单」向用户申请一次真实 API/付费/Docker 授权，不得自行开工。

### 阻塞项

- 阶段 B 所需的 Docker、真实 API 与付费授权尚未取得，按 §3 硬约束 2 处理。两个付费函数已存在，
  但在独立审查通过并取得口令前不得调用真实上游。
- `.env.local` 已确认存在、非符号链接、权限 `0600`。未打开文件。阶段 B 开始前执行者须静默确认
  `OPENAI_API_KEY` 存在且非空（relay / CCTQ Responses），不得记录其值。

### 当前验收状态

- 规划现场核对、worktree 创建与 ExecPlan：已完成。
- **阶段 A：两轮独立验收均不通过，第二轮缺口已由审查者直接修复。** 冻结 bundle、两份运行合同、
  接线与无 API loopback 核验通过；第一轮的门 1 谓词缺陷（Root 独角戏误判、未验 Root 唤醒）已整改并经复验确认；
  第二轮发现证据采集不绑定工具身份（`exec_command` 回显即可伪造门 1 通过），已按下述修复。
  在阶段 B 真实运行前，仍**不得**表述为 M-5 / 门 1 通过或未见退化。
- **门 1 证据绑定（审查者修复，2026-08-17）**：dump/log 只采纳 `team_inspect` 输出，唤醒信号只采纳
  `wait_agent` 输出；其它工具产出的"团队形状"负载记入 `unattributed` 并在判定中忽略、同时通过
  `CollaborationVerdict.ignored_evidence` 暴露，便于区分"模型伪造"与"wire 形状变了"。
  指令模板补充 `next_cursor` 续页要求（`MAX_OBSERVE_LIMIT=50`），并重算 `instruction_sha256`。
- **wire 形状已用冻结二进制实测确认**（无 API）：团队工具以 `name=team_inspect` +
  `namespace=collaboration` 的 function_call 直接调用即可执行，CLI 写回的 `function_call_output`
  正文就是真实 dump 负载；`non_code_mode_only` 取 true/false 都如此（true 只是把团队工具移出
  code-mode 嵌套面）。因此现有 `evidence_source` 设计成立，无需改动门 1 的运行配置。
- loopback 证明的是团队工具注册、一次 `team_publish` 往返与归档字段；**没有**证明投影进入后续采样
  或证据下钻。那两件事仍由阶段 B 门 1 真实运行判定。
- 阶段 B：**付费入口已接线，两轮独立验收分别窄修三处预算缺陷与三处运行期缺陷后通过，真实运行未开始。**
  §1 阶段 B 五项全部未做。不得开始花钱，除非用户按清单授权。

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
| 017 | 门 1 Event 局部谓词必须落在**同一个 Event**；按 `TeamStore::dump_entries` 顺序分组，不读 Version 上的 `event_id` | 真实 dump 的 Version 行没有 `event_id`；各自扫全表会让 Root 独角戏 + 游离成员噪声误判通过 | 门 1 判据 | 已采纳 |
| 018 | `root_resolved` 只认成员作者 Version；新增 `root_woken`（inspect log 对 Root 的 `signalled`，或 JSONL 里 `wait_agent` 的 TeamActivity 原文） | ExecPlan 五项能力含 Root 唤醒；mailbox 的 `Wait completed.` 不算 | 门 1 判据 | 已采纳 |
| 019 | 成员模型：补 `agents.default_subagent_*`，并设 `expose_spawn_agent_model_overrides=false` | 只设默认值仍可被 spawn 的 `model` 覆盖；关掉 schema 字段才能钉死 | Multi 运行配置 | 已采纳 |
| 020 | 门 1 dump 只从 harness 捕获的 Responses `function_call_output` 采集，不读 `TEAM_REPORT.md`，也不把 `codex exec --json` 当成工具输出源 | exec JSONL 不映射 `team_inspect`；wait 的 ThreadItem 也不带 TeamActivity 原文。真实工具结果出现在下一轮 Responses `input` 里 | 门 1 证据 | 已采纳 |
| 021 | 门 2 归因边界写入不退化锁：比较的是「上游 V2 + 团队状态」对「上游默认 V1」；真退化再跑 `V2 开、team_state 关`，本轮不预跑 | 结论要能说清退化归谁；不预跑省钱 | 门 2 合同 | 已采纳 |
| 022 | 采集按文档顺序吸收；无 cursor 的 dump 整页替换，带 cursor 的同快照页拼接；jsonl 一旦提供就覆盖调用方 dump | 整树 DFS last-wins 会把后一页 visibility 盖掉 Event，也会让伪造 dump 在 jsonl 空时漏进来 | 门 1 采集 | 已采纳 |
| 023 | 账本默认单次上限 $24；门 2 `ensure_run` 用 $8；门 1/门 2 请求预留 $8 / $2 | 默认 $40 加上 Guardian 附加预留会顶破单次上限；门 1 按约 $8/次的小倍数收紧 | 预算 | 已采纳 |
| 024 | Capture forward 超时 180s、SSE 边读边写、原样转发非 hop-by-hop 头（含 User-Agent） | 30s 会把正常慢请求打成 infra；预算代理要求恰好一个 User-Agent；整包缓冲会堵流 | 门 1 捕获 | 已采纳 |
| 025 | 付费入口用冻结口令解锁；测试走 `PaidAuthorization` + fake transport，justfile 永不内嵌口令 | 函数可以存在，但不能在未授权时加载密钥或打开付费上游 | 授权门 | 已采纳 |
| 026 | 门 1 单次预留改 `$4`（可用额度 = `cap − 2×预留` = `$16`）；门 2 维持 `$2`/`$8` | main 预留要同时过 Guardian 附加容量校验，`$8` 预留把门 1 掐在 `$8` = 点估计，余量 1.0 倍；`$4` 给 2 倍余量且仍高于最坏现实单轮（≈`$2.32`） | 预算 | 已采纳 |
| 027 | 预算掐断单独落 `budget_stopped`，门 2 记 `counts_as_effective=false` 并停批；门 1 不重试 | 代理对耗尽的 run 就地回 429 而非抛异常，掐断会被误记成产品失败；Multi 成本更高，会系统性偏向"稳定单向退化" | 判据诚实性 | 已采纳 |
| 028 | 共享账本槽位改 `60+12+门1的3次 = 75`，`$120` 硬上限不变 | 两道门共用一个账本，按 `60+12` 算会在最坏合法路径截断门 2 | 预算 | 已采纳 |
| 029 | 「每 run 请求上限 80」真正执行：真实槽位从账本读逻辑请求数，超限落 `infra_failed` 且不计有效 | 授权清单答应了这个数就该作数；代理层的 `max_logical_requests` 被校验成 `1..4`，拦不住。分类成 infra 使最坏结果是「不确定」而非假退化 | 门 2 判据 | 已采纳 |
| 030 | `_UrllibTransport` 的 test-only `endpoint_override` 挂空 `ProxyHandler({})` | Python 的 `no_proxy` 不认 `127.*` 通配，宿主 `HTTP_PROXY` 会劫持环回假上游；生产 env 代理行为不变 | 测试可复现性 | 已采纳 |
| 031 | 门 1 沙箱 `network_access=true` 保持不动 | 它属于阶段 A 冻结 argv，改动会作废五次全绿彩排；作为残留风险记录而非静默修改 | 门 1 运行配置 | 已采纳 |
| 032 | 门 1 载体保持冻结（协议演示级 fixture），改为把边界写进锁的 `scope_limits` 与文档，不换成有分析负载的任务 | 换载体等于改冻结的完成标准（须请示用户）、作废唯一验证过的五次彩排，且新载体在花钱前无法离线验证；决策 010 冻结它正是为了避开「模型自己做完、团队工具零调用」这一相反失效模式。代价是 WBS 的「真实任务上跑通完整协作语义」必须门 1+门 2 合起来读，任一门单独不得引用 | 门 1 载体 / 结论口径 | 已采纳 |
| 033 | 「每 run 80 请求」用账本包装层在 `reserve()` 上硬拦，停止原因与「钱不够」分开 | 事后分类挡不住第 81 次真实发出与计费；预算代理的 `max_logical_requests` 被校验成 `1..4`，用不了。钱是全批共享的（停批），请求上限是每 run 的（只停槽） | 付费边界 | 已采纳 |
| 034 | Docker 容量停止线单独用 `DockerResourceStop` 子类，门 2 立即停批不重试 | 80GiB/60GB 是 CLAUDE.md §3 的「立即停止」，被压成普通 infra 会继续开容器；子类化保持既有 `except DockerSupervisionError` 调用方不变 | 资源边界 | 已采纳 |
| 035 | 门 2 退出码由 `gate2_passed`（未停批 + 十任务齐全 + 全部无退化）决定，不再只看 `stopped` | 退化结论或证据不完整都是 M-5 失败，shell 层必须看见失败 | fail-closed | 已采纳 |
| 036 | 付费运行前用 `require_frozen_provider` 把 provider 身份/effort/重试/全部费率绑到锁，日期差异只记录不阻断 | 预算代理用 `rondo.local.toml` 的费率给 $120 记账，改那个文件就能改变授权上限的实际购买力；费率决定花钱，日期只是出处 | 预算/公平性 | 已采纳 |
| 037 | 不强制门 2 依赖门 1 通过；不改 `base_order` 的 Codex 先后顺序 | ExecPlan §1 明写两门相互独立；顺序偏差方向利于 Multi，只会让退化判定更保守，不会造出假退化，已写进锁的 `scope_limits`。实际付费顺序仍应先门 1 后门 2 以减少无效支出，靠流程而非代码依赖 | 门 2 合同 | 已采纳 |
| 038 | 请求上限的「读计数 + 预留」在包装层加锁合成单一临界区，不改共享账本 | 代理跑在 ThreadingHTTPServer 上、Root 与成员并发，`snapshot→判断→reserve` 是 TOCTOU（实测上限 8 被冲到 13）。真实槽位里交给代理的唯一 reserve 路径就是这个包装层，故在此串行即充分；账本不回调包装层，无锁反转 | 付费边界 | 已采纳 |
| 039 | 付费 endpoint 写进不退化锁并逐字校验，缺失即 fail-closed | provider 名称不说明密钥、工作区内容与费用实际流向何处；同名换 endpoint 原先照样通过 | 安全边界 | 已采纳 |
