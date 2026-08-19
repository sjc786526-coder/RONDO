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
- **门 1 合同**：`eval/locks/multi-m5-workflow-v2.json`（v1 只留历史，不得作为 v2 证据）。
  载体是 host `codex exec` +
  `eval/fixtures/multi-m5-collab-v1/` + `eval/templates/multi-m5/collab-workflow-instruction-v1.md`
  （sha `9879529f…d5333`），不是 TB `fix-git`。完成标准 = `TEAM_REPORT.md` 含 finding 行且六项协作谓词
  全真；孤儿退休不是必触发项。Docker 不用于门 1。
- **门 2 合同**：`eval/locks/multi-m5-nondegradation-v2.json`（v1 只留历史）。十任务来自
  `eval/tasksets/p2-b7-canary-catalog-v4.json`（catalog sha `00b83e44…57ddf`），交错
  `task_major_codex_then_multi`，轻 runner，不套 v7 campaign，不计算 σ/delta。价格快照
  2026-08-18 官方页（terra）；硬上限 $120，且由冻结 token 信封使其成为数学上限。
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
- **付费前最后一项缺口已闭环：退化诊断从「文档声明」变成真实可执行**（`03b4469`）。
  原状态是 `load.py` 只在锁文本里 grep `diagnostic_v2_on_team_state_off` 字符串，没有任何代码能构造该槽位，
  一旦真的形成稳定单向退化，"归因到团队层"只能靠断言。现改为：`team_capability_override_items` 增加
  `team_state_enabled=false` 的诊断表（其余 `-c` 覆盖含成员模型完全不变）；adapter 拒绝非 Multi 侧携带该标志、
  并严格解析 Harbor 的 JSON 字符串形式（`"false"` 不会被真值化成开启）；gate 2 在**判定完成后**才构造诊断槽，
  锁的「不得预跑」由构造顺序保证；诊断行 `counts_as_effective=false`、不占 `max_effective_runs`，
  但共享 $120、infra 尝试与全部停止线；账本槽位补每题一个（`60+12+3+10=85`），否则要解释退化的那次运行反而开不了；
  锁新增 `attribution.diagnostic` 可执行块，loader 逐字段校验而非匹配一句话。九条定向回归。
- **模型换为 `gpt-5.6-terra`（用户决定，决策 042/043）**：冻结上游 v0.147.0 catalog 已含 terra，
  且 `multi_agent_version=v2` / `tool_mode=code_mode_only` / 272k 上下文 / 支持 medium 与 sol 全同，
  故二进制、catalog、`instruction_sha256` 均不动。官方页同日核对：terra 2/0.2/12 = sol 5/0.5/30 的 40%，
  点估计 $40→$16、最坏 $96→$38.40，$120 上限不变。
  关键副作用已就地修掉：宿主 `paid_eval.main_model` 是机器级全局别名，直接翻成 terra 会改写同机所有
  已冻结 campaign 的 provider 身份（P2/B7 基线锁当场 drift）。改为 M-5 用
  `paid_provider_projection(model_id=...)` 按模型 id 反查别名，宿主别名保持 `sol`，
  单智能体方向的历史基线不受影响。三条定向回归钉住该隔离性。
  离线复验：彩排 4 次全绿（七谓词全真）、loopback 通过（配置已显示 terra）、就绪自检 `ready=true`。
- **Python 门禁复现注意**：必须清掉 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` 再跑，否则环回假上游会被宿主代理劫持。
- 044 分支提交后停止。未合并、未推送。**正式两道门的 `$120` 账本仍未产生任何消费**
  （`eval-data/budgets/` 无 `multi-m5-phase-b` 账本）。但"累计费用 $0"对整个任务已不成立：
  2026-08-18 在合同外、单独授权的冒烟账本上发生过真实支出，见
  `agent_log/2026-08-19-060000-plan044-m5-phase-b-fifth-review-remediation.md` 的勘误一节
  （历史产物的账目不自洽，不能当完整费用记录）。Docker 与本地模型仍未执行。

### 移交入口（2026-08-19，第五轮审查整改后重写）

- **历史入口**：`agent_log/2026-08-19-030000-plan044-m5-phase-b-handover-review.md` 记录第四轮交接时的事实；
  其中"门 1 采集口径待定"与"smoke 账本"两节已被本轮取代，勘误见
  `agent_log/2026-08-19-060000-plan044-m5-phase-b-fifth-review-remediation.md`。
- **门 1 判据已重建并落地**（原"待授权"阻塞已关闭）。改的是观测手段而不是被测配置：
  `evidence_source` 从 `responses_function_call_outputs` 换成 `code_mode_rollout_trace`，
  读冻结二进制既有的 rollout trace（`CODEX_ROLLOUT_TRACE_ROOT`，无需改产品代码），
  只认 Rust dispatch 侧记录的工具身份与 handler 返回值，并强制绑定回抓包里模型真实发出的 code cell。
  已冻结 `multi-m5-workflow-v2`；**彩排 stub 已同步改成 code-mode 形状**（第四轮特别提醒的那一点）。
- **门 2 模型贯通已修复**：RunSpec 此前仍继承宿主 `paid_eval.main_model`（sol），与只认 terra 的预算代理
  不一致，真跑必被本地拒并记成产品失败。现已全链贯通并加了离线就绪自检。
- **$120 已是数学上限**：预留改为「冻结 token 信封 × 价目表」机械推导（$2.22），信封在账本 settle 处强制。
- **保守记账维持不变**：`response.failed` 无 usage 仍按整笔预留结算（无法机器绑定"未计费"证明时不放松安全线），
  但预留额已从 $4.00 降到 $2.22，且报表把 `priced_usd` 与 `conservative_exposure_usd` 分开，
  不再把预留描述成真实消费。
- **新发现的门 1 风险（尚未验证）**：团队证据 fact 只在 `ToolCallSource::Direct` 时留存，code cell 内的
  嵌套调用不留（`multidev/codex-rs/core/src/team/evidence.rs`）。若真实模型把所有调用都放进 cell，
  `team_evidence` 谓词无法成立。彩排里 shell 走直接调用可满足，真实模型是否如此只能由冒烟回答。

### bundle 重建与 v3 冻结（2026-08-19）

- **两次重型构建，不是一次**：`prepare_companion()` 拷进 bundle 的 `codex` 字节取自 **legacy artifact
  目录**（`eval-data/bin/rondo-multi/<commit>-musl/`），不是两 bin 构建的产物。因此要拿到带修复的 CLI，
  必须先补一次 legacy 单 bin 构建 + `prepare`，再做两 bin `v8-build` + `prepare-companion`。
  两次均走本 worktree 的 `scripts/with-build-lock.sh`，`CARGO_BUILD_JOBS=2`（决策 016），
  `status=0 stop=none`，分别 39m08s 与 32m41s，看门狗全程无告警。
- 另两处硬约束以代码为准：`CARGO_TARGET_DIR` 必须恰好是
  `eval-data/build/rondo-multi-<commit>-x86_64-unknown-linux-musl`（`_expected_target()`），
  `RONDO_BUILD_METRICS_DIR` 必须在 `eval-data/build-metrics/` 下且每次构建一个全新目录
  （`_validate_watchdog_summary()` 要求恰好一份 `summary.env` 且 `stop_reason=none`）。
- **新身份**：`multi-m5-runtime-v2`，源码 `6fe1379e4a77a604407b335fd94b3cc81d53501a`，
  `codex_sha256=7ec5ec76…f165`、`code_mode_host_sha256=1102b8f3…a64c`、`bwrap` 与 Codex 同资产、
  `manifest_sha256=bd5575e5…3ff7`；`codex_baseline` 原样沿用。旧 bundle、旧锁、旧归档一字节未动。
- **v3 冻结内容**：两把锁显式写 `runtime_lock_id`；门 1 增 `infra_taint_effect="infra_failed"` 与
  `provider_contract`；门 2 增 `provider_retry_backoff_seconds="2"` 与 `unpriced_settlement`
  （`unpriced_stop_threshold=1` + `any_unpriced_invalidates_observation=true`）。
- **顺带关掉的真实缺口**：退避此前门 1 硬编码 2.0、门 2 读宿主 `paid_eval.retry_backoff_seconds`
  （本机 `1.0`），两门实际不一致且都不受锁约束。按决策 043 的隔离方式统一从锁读，宿主全局量不动。
- **明文投递成为机器判据**：新增 `member_message_delivery`（`plaintext` / `encrypted` / `absent`），
  写进门 1 结果与 smoke 摘要。新 bundle 彩排 20/20 `input_text`、0 encrypted；旧 bundle 的 cm4 抓包
  37 个 `encrypted_content`。这是冒烟五项验收里唯一原本只靠人看抓包的一项。
- **clean smoke 账本**：旧 `$40` 批次已用尽且 cap 与磁盘文件绑定，无法就地扩容，故新建独立批次
  `multi-m5-clean-smoke`（`eval-data/budgets/multi-m5-clean-smoke.json`）。上限不是手填而是
  `SMOKE_MAX_RUNS(3) × 单次 run cap($23.10) = $69.30`，在 `open_smoke_ledger` 处机械校验，
  且强制小于两道门共享的 `$120`。旧账本与旧归档保留。
- 离线复验：定向门禁 216/216、`just eval-lock` 通过、`ready=true`、彩排七谓词全真且
  `member_message_delivery=plaintext`、loopback 通过（`lock_id=multi-m5-runtime-v2`）。

### clean smoke 结果（2026-08-20，2/3 次，剩 1 次未用）

- **产品修复确认成立**：`cs2` 有 Root（20 请求）与**成员**（15 请求）两个线程，成员从 code cell
  真实派发 8 次工具调用（`team_publish`×2、`team_evidence`×2、`team_history`、`team_route_update`、
  `send_message`、`exec_command`），`member_message_delivery=plaintext`（82 明文块 / 0 encrypted）。
  旧 bundle 的 cm4 同路径是 37 个伪 encrypted、成员 8/8 失败、从未完成回合。
- **clean smoke 未达成**，两个互相独立的原因：
  1. **上游终止**：HTTP `200` 之后在流内发 `error`/`server_error`。重试白名单是 HTTP **状态码**，
     状态码 200 时退避梯子完全不触发。cs1 1/1、cs2 4/35，`conservative_exposure_usd=$11.10 ≠ 0`。
  2. **模型未调用 `team_inspect`**：判据只接受它的输出作为 dump/log 证据源，因此 cs2 七个谓词
     **全部无法验证**（不是判为假）。**不得**据此对 Direct fact 风险或 terra 的指令遵循下结论。
- **勘误**：cm1–cm4 的 49 个请求终止错误**全是** `invalid_encrypted_content`、零 `server_error`。
  「中转站约三分之一掉流」是被产品缺陷污染的观测，不是中转站基线故障率。
- **费用**：clean smoke 批次共扣 `$11.52`（真实 token 计价 `$0.42`），剩 `$57.78`。
  **正式 `$120` 账本仍不存在、零消费。**
- 最后一次额度**未使用**：按当前约 11% 的终止率，一次 30+ 请求运行全程零 taint 的概率约 2%，
  验收又要求 zero taint，故不赌这一次；方向决定见 `doc/WBS.md`。

### 本任务剩余步骤

- 阶段 B 的离线准备已全部完成并提交。**$40 冒烟已执行并用尽**（四次，合计扣减 `$31.52`，
  其中真实 token 计价仅 `$0.44`，余 `$8.48` 不足再跑一次完整流程）。结论见
  `agent_log/2026-08-19-120000-plan044-m5-phase-b-sixth-review-remediation.md`：
  **trace 判据在真实模型上成立**（含判据必需的 `collaboration.team_inspect`，`spawn_member` 由真实
  证据判真）。**"真实模型不遵守协作协议"的结论已撤回**：cm4 的成员线程 8 次推理 8 次失败
  （`invalid_encrypted_content`），从未完成一个回合，故其"没有 publish/evidence"不可归因于模型。
  该错误**已归因并修复**：不是 Root 推理被 fork，而是 code-mode 的 `spawn_agent` 明文 message 被
  误包成 encrypted content（产品缺陷，已修并补 5 条 Rust 回归）。
  **当前阻断是冻结的 runtime bundle 早于该修复、仍带缺陷。**
  顺序：证据污染语义（已修）→ code-mode 明文（已修）→ 重建 bundle 并冻结 v3 →
  一次零 infra-taint 的 clean smoke → 才谈正式门 1。
  冒烟入口：`python -m rondo_eval.multi_m5 smoke --label <全新 id> --authorize-paid-api <口令>`
  （**不含独立 provider probe**，已按第六轮决定删除；入口能花的钱只受其自身账本约束）。
  每次必须换 `--label`：独立 run id、独立捕获目录、`claim_run` 拒绝重用，既有产物存在时直接拒绝启动。
- 门禁复跑口径：`tests.test_multi_m5`、`tests.test_multi_m5_exec`、`tests.test_multi_m5_trace_evidence`、
  `tests.test_terminal_bench` 与 `just eval-lock`。全量 `just eval-test` 为 932 用例、0 失败；
  其中 2 个 `ModuleNotFoundError: No module named 'eval'` 的加载错误
  （`test_l6_b10333_pair`、`test_local_m4_holdout_anchor`）在干净树上同样存在，属既有问题，不由本次引入。
- **terra 可用性已由 2026-08-18 冒烟证实**（中转站已解封，模型确实响应并调用了团队工具）。
  `smoke` 入口**不再内置 provider probe**：它会另开一份 $5 的 Plan 013 账本、绕出授权额度，
  已按第六轮决定删除。若确需单独 probe，应作为独立且单独授权的动作。

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
- **~~wire 形状已用冻结二进制实测确认~~（该结论已于第五轮作废，保留原文以存历史）**：当时用直接注入
  function_call 的方式验证团队工具可执行，结论本身没错，但**那不是真实模型的调用方式**。
  `code_mode_only` 模型只发 `custom_tool_call(name=exec)`，团队工具全在 JS 里调，顶层 function_call 数为 0，
  因此 v1 的 `evidence_source` 在真实配置下不可能成立。现已改为 rollout-trace 口径并冻结 workflow v2。
- loopback 证明的是团队工具注册、一次 `team_publish` 往返与归档字段；**没有**证明投影进入后续采样
  或证据下钻。那两件事仍由阶段 B 门 1 真实运行判定。
- 阶段 B：**经五轮独立审查整改；离线准备已就绪，正式付费运行未开始。**
  第五轮关闭了两个结构性阻断（门 1 判据在 code-mode 下不可能通过；门 2 RunSpec 与预算代理模型不一致），
  并把 $120 从"意图"变成机械推导的数学上限。§1 阶段 B 五项仍全部未做。
  已授权：$40 独立冒烟账本（不限次数，独立 batch/lock_id/归档，不动 $120）。
  正式门 1 与门 2 仍须用户按清单单独放行。**不得表述为 M-5 通过、门 1 通过或未见退化。**

### 阶段 B 精确授权清单

取得一次明确授权后才可开始。授权范围建议按下表一次性批准或驳回；未列项仍禁止。

| 项 | 冻结值 |
|---|---|
| API provider | `rondo.local.toml` 的 `paid_eval.active_provider = "relay"`（CCTQ Responses；`api_key_env = OPENAI_API_KEY`）。不改官方入口，不把密钥写入文档或提示词。 |
| Root / 成员模型 | `gpt-5.6-terra` + `medium`（两侧相同）。由 M-5 两把锁自行钉死，不继承宿主 `paid_eval.main_model`（仍为 `sol`） |
| 门 1 | host `codex exec` 协作 fixture，无 Docker；最多 3 次尝试、单次 1800s |
| 门 2 | v4 catalog 十任务；`task_major_codex_then_multi`；条件复跑仅当「Codex 完成、Multi 未完成」时双方各加两次 |
| 最大有效运行 | 60（基础 20 + 条件最多 40） |
| 退化诊断 | 仅在某题判为稳定单向退化后触发；每题最多 1 次、Multi 侧、V2 开 + team_state 关；不计有效结果、不改判定；与两道门共享同一 $120 与全部停止线 |
| 基础设施 | 每槽最多 3 次尝试；infra 总上限 12；infra 不计有效结果 |
| 每 run 请求上限 | 80 |
| 价格快照 | 2026-08-18 官方页：input $2 / cached $0.20 / output $12 per 1M；长上下文 272k input×2 output×1.5；cache_write 1.25。同日核对 sol 仍为 5/0.5/30，故 terra 为其 40% |
| 费用 | 点估计约 $16；合同内最坏约 $38.40；**硬上限 $120 不变**（余量约 3 倍，预算掐断风险大幅下降）。账本批次 `multi-m5-phase-b` |
| Docker | **只为门 2**。十个 digest 钉死镜像（见 `eval/locks/multi-m5-nondegradation-v2.json` 的 `docker_images`）。不拉其它镜像，不跑完整数据集。门 1 不用 Docker。 |
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
| 040 | 退化诊断做成真实可执行槽位：`team_state` 标志贯通 adapter/归档/账本，判定完成后才构造，且不计有效结果 | 锁承诺了归因诊断，实现却只有一次字符串匹配；真出退化时无法诚实归因。判定后构造使「不得预跑」由构造顺序保证，而不是靠纪律 | 门 2 归因 | 已采纳 |
| 041 | 账本槽位由 `60+12+3` 扩到 `+10`（每题一个诊断），$120 硬上限不变 | 槽位只是计数护栏、不是购买力；不扩就会出现「要解释退化的那次运行开不了」 | 预算 | 已采纳 |
| 042 | 模型由 `gpt-5.6-sol` 换为 `gpt-5.6-terra`（用户决定），两侧同模型不变 | 官方页同日核对：terra 2/0.2/12 是 sol 5/0.5/30 的 40%。冻结上游 v0.147.0 的 catalog 已含 terra，且 `multi_agent_version=v2`/`tool_mode`/272k 上下文/medium effort 与 sol 全同，故不动二进制、不动 catalog、不动 `instruction_sha256` | 门 1+门 2 运行配置 | 已采纳 |
| 043 | M-5 从**自己的锁**解析模型（`paid_provider_projection(model_id=...)`），宿主 `paid_eval.main_model` 保持 `sol` | 该别名是机器级全局量，翻成 terra 会改写同机所有已冻结 campaign 的 provider 身份 —— P2/B7 基线锁当场报 drift。按模型 id 反查别名可让两个冻结 campaign 在同一台机器上用不同模型，也把 M-5 的模型选择从机器配置移进任务合同 | 配置隔离 / 跨方向可比性 | 已采纳 |
| 044 | 重试退避改为从 M-5 自己的锁读（`provider_retry_backoff_seconds="2"`），宿主 `paid_eval.retry_backoff_seconds` 不动 | 门 1 硬编码 2.0、门 2 却读宿主值（本机 1.0），两门实际用不同梯子且都不在冻结合同里。宿主那一项是机器级全局量，改它会波及同机其他 campaign —— 与决策 043 同一条隔离原则 | 门 1+门 2 运行配置 | 已采纳 |
| 045 | clean smoke 另开批次 `multi-m5-clean-smoke`，上限由「三次 × 单次 run cap」机械推导（`$69.30`），并强制 < `$120` | 旧 `$40` 冒烟批次已用尽，且账本 cap 与磁盘文件绑定、不能就地扩容；沿用旧批次会把修复前后的行数混在一个账本里。上限推导而非手填，避免两个数字各自漂移 | 预算 / 证据分区 | 已采纳 |
| 046 | 明文投递做成机器判据 `member_message_delivery`，写进门 1 结果与 smoke 摘要 | 它是冒烟五项验收里唯一只靠人看抓包的一项，而它恰好是区分「成员没收到可读任务」与「模型不遵守协议」的那一项 —— cm4 的错误归因就是这么产生的 | 门 1 证据 | 已采纳 |
