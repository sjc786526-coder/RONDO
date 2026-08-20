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

- [x] Multi runtime bundle 已按产品身份冻结到 `eval-data/bin/rondo-multi/<bundle>/`，manifest 完整；
      其来源提交、构建命令与二进制哈希等身份事实同时写入本分支的受跟踪文件，使分支离开 ignored 目录仍可自证。
- [x] 冻结 Codex bundle 与 Multi bundle 的身份、来源与必要伴随产物（如 code-mode host、bwrap 资源）已核验一致可用。
- [x] **真实协作工作流合同已冻结**并写入受跟踪文件：运行载体与环境、给 Root 的任务陈述、成员规模上限、
      工作流自身的完成标准、以及“协作功能确实发生”的可观测判定口径（至少覆盖 Event/Version 发布、Root 唤醒、
      route、多作者追加、证据下钻五项）。不要求人为制造孤儿成员。
- [x] **不退化运行合同已冻结**并写入受跟踪文件：`eval/tasksets/p2-b7-canary-catalog-v4.json` 的十任务、
      双方一致的任务条件、预先冻结且交错的执行顺序、Root/成员模型与推理配置、超时与请求上限、基础轮次、
      条件复跑规则、基础设施失败处理与尝试上限、价格快照来源与日期、费用预测与美元硬上限。
- [x] 完成 M-5 所需的**最小**测评接线：Multi 侧以团队能力开启的状态运行，产品身份、运行合同版本与结果归档链路贯通。
      不新建通用框架，不改写历史结果，不动 Local 的既有公平运行合同。
- [x] 在**无 API、无 Docker**条件下证明接线真的生效：至少一次 fake/loopback 级别的工作流演练，证明团队工具确实被
      注册并可被调用、投影与证据链路可观测、结果记录字段齐全；skip 或未运行不得写成通过。
- [x] 受影响模块的定向门禁通过：`multidev/` 侧受影响的 Rust 定向测试（含既有 team 套件不退化）、
      `eval/` 侧受影响的 Python 测试与 `just eval-lock`；不扩大为全 workspace 测试。
- [x] 输出**阶段 B 精确授权清单**（见 §3 硬约束 2 的条目），并在本计划“当前状态”记录，然后暂停等待授权。

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
- **门 1 当前合同**：`eval/locks/multi-m5-workflow-v6.json`；v1—v5 只留历史，不得作为正式 v6 证据。
  载体是 host `codex exec` +
  `eval/fixtures/multi-m5-collab-v1/` + `eval/templates/multi-m5/collab-workflow-instruction-v2.md`
  （sha 以 v6 锁为准），不是 TB `fix-git`。完成标准 = `TEAM_REPORT.md` 含 finding 行且七项协作谓词全真，
  包括成员精确证据链、Root 自身 completed wait 与最终 `team_update`；调用 actor、同线程 trace 完成边界及
  inspect-log revision 必须共同绑定到同一 Event，canonical publish/route 只认 `deduplicated=false`。孤儿退休
  不是必触发项。最多 6 次，Docker 不用于门 1。
- **门 2 当前合同**：`eval/locks/multi-m5-nondegradation-v6.json`；v1—v5 只留历史。十任务来自
  `eval/tasksets/p2-b7-canary-catalog-v4.json`（catalog sha `00b83e44…57ddf`），交错
  `task_major_codex_then_multi`，轻 runner，不套 v7 campaign，不计算 σ/delta。价格快照
  2026-08-18 官方页（terra）；60 个有效样本、每槽最多 5 次 infra、全批最多 40 次 infra、116 个 run 槽位，
  每 run 80 请求、HTTP retry 5、硬上限 $120。
- **Multi runtime 当前冻结身份**（ignored 产物 + 受跟踪身份）：
  `eval-data/bin/rondo-multi/0eee6dc5ee69f0eca9e1db350148c423a2b2bf67-x86_64-unknown-linux-musl-runtime-bundle/`。
  受跟踪锁 `eval/locks/multi-m5-runtime-v4.json`：source `0eee6dc5…bf67`，CLI `c64ff001…c631`、
  host `dc7a00d7…8d0f`、bwrap `77360cb7…62c4`、manifest `5fa958e0…5f31`；已 `verify-runtime`。
- **最小接线**：`features.multi_agent_v2` 仍是单条 inline TOML，只注入 Multi；另加
  `agents.default_subagent_model` / `agents.default_subagent_reasoning_effort`，并关闭
  `expose_spawn_agent_model_overrides`。Codex/Local 禁止这些项。TB adapter、loopback、归档与
  Python 合同测试已落地。根 `just eval-sync`/`eval-test`/`eval-lock` 从 worktree 经
  `git-common-dir` 解析主根 venv；新增 `just eval-multi-m5-loopback`。
- **无 API 演练**：`just eval-multi-m5-loopback` 通过；`loopback_tool_round_trip=true`，
  `counts_as_effective=false`，`evidence_kind=loopback`。证明团队工具在 `code_mode_host=true` 下已注册
  并可走 `team_publish` 往返。**不是门 1 真实通过。**
- **阶段 A 历史定向门禁**（均无 API / 无 Docker；不是当前 v6 验收数字）：
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
- 044 分支在正式门前停止。未合并、未推送。**正式两道门的 `$120` 账本仍未创建或产生任何消费**
  （`eval-data/budgets/` 无 `multi-m5-phase-b` 账本）。但"累计费用 $0"对整个任务已不成立：
  2026-08-18 在合同外、单独授权的冒烟账本上发生过真实支出，见
  `agent_log/2026-08-19-060000-plan044-m5-phase-b-fifth-review-remediation.md` 的勘误一节
  （历史产物的账目不自洽，不能当完整费用记录）。本轮另有一条隔离 clean-smoke-v5，真实计价
  `$0.273138`；Docker 与本地模型仍未执行。

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
- **门 1 证据链风险正在用 fail-closed 口径收口**：final-v2 已证明模型在 code cell 内调用工具，但外层
  `exec` 结果原先不会铸 fact，成员 Version 的 `evidence_refs` 结构上不可达；不是模型漏调工具。runtime-v3
  随后把所有纯文本 outer cell 都当证据，独立终审又证明这会让只含 team tools 的 inspect/publish cell 递归铸
  Fact，并在分页时改变 snapshot generation。当前修复改为：只有在该 cell 内完成过受支持的**非 canonical
  team-state / evidence-read-only** nested
  tool，且 outer response 是 runtime 已排空 callbacks 的 terminal 纯文本结果时，才允许铸一个 Fact；Yielded、
  team-only、混合媒体、加密与空输出均拒绝。绑定键是 harness 唯一 `output_item_id`，不使用可并发复用的模型
  `call_id`。

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

### runtime-v3 冻结及终审否决（2026-08-19）

- 产品修复提交 `802238bf45f9b877bef1206454216ce364b5d6c7`。Rust 定向门禁 8/8：正向覆盖真实
  `CustomToolCallOutput + ContentItems(InputText...)`，集成覆盖外层 code cell 只生成一个 fact、成员发布带
  `evidence_refs` 且 `team_evidence` 可读；加密与混合媒体反向回归继续 fail-closed。
- 新测量树 `.claude/worktrees/044-m5-multi-bundle-measurement-v3` detached 于该提交。legacy musl 与
  CLI+host 两次构建都走共享 build-lock、`CARGO_BUILD_JOBS=2`，分别 37m33s / 31m30s，均
  `status=0 stop=none cleanup=none`。`multi-m5-runtime-v3` 已冻结并验证：CLI `d73c1ada…6355`、host
  `bcbca36f…3c55`、bwrap `77360cb7…2c4c`、manifest `73d7f9cf…e8af`。
- 当时的离线门禁为 M-5/trace/terminal 164/164、依赖锁、`ready=true` 与 loopback；rehearsal 表面七谓词
  全真、明文且无 Direct shell。**独立终审已否决该 rehearsal 和 runtime-v3 的 ready 结论**：首次 dump 返回
  `next_cursor` 后，outer inspect cell 自己铸 Fact 并推进 `observe_generation`，第二页实际以 stale cursor 失败；
  collector 又静默跳过 failed inspect，故第一页足以假绿。runtime-v3、workflow/nondegradation v4 只保留为
  被否决历史，不得充当后续 smoke 或正式门证据。
- 用户把本轮准备性真实 API 授权上调为 **1000 USD**，但各入口自己的更低硬上限继续生效；正式门 1/门 2
  和 `$120` 账本明确禁止启动。第一次 `clean-smoke-v3` 在 provider 收到请求前被开发沙箱网络策略拦截，留下
  1 条未结算的 `$2.22` 预留与请求 capture，无归档、不可当真实消费或产品证据。该历史不删除、不复用；
  replacement `clean-smoke-v4` 未启动；因其合同已绑定被否决的 runtime-v3，后续也不得启动。runtime-v4
  验证通过后另建隔离的 clean-smoke-v5（1 次、上限 `$23.10`、独立 ledger/archive）。

### runtime-v4 与门前收口（2026-08-20）

- 产品修复提交 `0eee6dc5ee69f0eca9e1db350148c423a2b2bf67`；共享 build-lock 定向 Rust 146/146，
  wrapper/final rc=0、无 stop/cleanup。measurement worktree detached clean 于同一提交。
- `multi-m5-runtime-v4` 四项实物摘要：CLI `c64ff001…c631`、host `dc7a00d7…8d0f`、bwrap
  `77360cb7…2c4c`、manifest `5fa958e0…5f31`；`verify-runtime` 通过。`b078e28` 冻结
  workflow/nondegradation v5，并将 clean smoke 切为独立 v5 身份。
- `just eval-lock`、M-5 Python 定向 136/136、ready=true、loopback 通过。rehearsal 0 Direct、20/20
  dispatch completed、dump 7 页/log 2 页（`limit=3`，均到 null）、明文 9/加密与未知 0、七谓词全真；
  成员自身 exec Fact 被 Version 引用并由 `team_evidence` 读回。独立付费前终审为 GO。
- clean-smoke-v5 仅运行一次 `m5-g1-smoke-finalv5`：20 请求全部 usage-priced/settled，计价与 charged
  `$0.273138`，`conservative_exposure_usd=0`；outcome=completed、零 taint、明文 16/加密与未知 0、
  七谓词全真。真实 trace 18/18 dispatch 均为 code cell、0 Direct、全部 completed；dump 25 条与 log 7 条
  均在返回 null 的完整页收齐，成员 `fct-2 → ver-1.1 → team_evidence observation` 成链。
- 独立后审复核 ledger/archive/raw trace/正式资产隔离后通过。正式归档 SHA-256 仍为
  `9da1be52…f884`（26 行）；`multi-m5-phase-b` 账本和锁不存在。

### v6 正式付费前整改（2026-08-20）

- 后续独立审查否决了 v5 的“门前就绪”结论：workflow-v5 没有机械要求成员完成 `team_evidence` 和二次
  publish，测试与正式 Gate 1 共用 capture identity，Gate 2 在 provider 完整冻结前会 claim run，正式批次也
  没有可恢复的中断语义。审查报告作为形成时点证据保留在
  `agent_log/2026-08-20-110000-plan044-m5-paid-readiness-independent-review.md`。
- v5 及其历史 rehearsal/smoke 不改写。新冻结 `multi-m5-workflow-v6` / `multi-m5-nondegradation-v6`，继续复用
  未变化的 `multi-m5-runtime-v4`。门 1 最多 6 次；门 2 每槽最多 5 次 infra、全批最多 40 次；有效样本 60、
  每 run 80 个逻辑请求、provider 每请求最多 5 次 HTTP 尝试和 `$120` 硬上限不变；共享 run 槽位为
  `60 + 40 + 6 + 10 = 116`。
- Gate 1 只在同一成员按“首次 publish → Root publish → route → `team_evidence` 自身 exec Fact → 不同 Version
  的二次 publish → Root `team_update`”完成时判证据链成立。首次 Version 必须精确引用该 Fact；计入协议的
  publish/route 必须明确 `deduplicated=false`。Root wait、publish、route、update 与成员调用分别绑定 manifest
  actor；canonical mutation 的跨线程提交顺序由完整 inspect-log revision 证明，跨线程 wrapper end 不作为提交
  时钟；同 actor 仍用 end/start，wait 与首次 publish 另用两端点证明区间重叠并要求精确 wake log，route start
  必须先于 evidence start。整条 trace 必须零 Direct，成员投递必须仅为 plaintext。
  测试 capture、v6 rehearsal、v6 正式批次分别使用独立 namespace，正式 capture 已有任何产物即 fail-closed。
- 正式 resume 按 batch/workflow/nondegradation/runtime/provider receipt 核身份：完整归档行按原分类跳过；
  零请求、零消费、无停止/taint/冲突产物的 pristine run 可原 id 重领；精确白名单内、属于本 run 且仍在 Harbor
  启动前的零请求产物追加一次 `abandoned=true` infra 后进入下一 attempt；已请求未归档的 run 保守结算后也只
  追加一次 abandoned infra。已持久化的 budget/capacity stop 必须一次归档为 `budget_stopped` 并停止，不能伪装
  成可重试 infra；未知产物、symlink、exact trial dir 或 exact-label Docker/Compose 残留一律 fail-closed，等待
  受监督的精确清理，不自动删除。未来、重复、非连续或其它冲突状态同样 fail-closed。Gate 2 每个
  attempt 的归档在下一 run id 被 claim 前立即 fsync，避免进程退出留下两个未归档 run。正常模型失败仍是
  `agent_failed` 产品结果，不能换成 infra。
- 正式入口在读取密钥、创建 receipt/ledger 或 claim 前完成 provider 冻结校验；Gate 2 正式入口还要求同一 v6
  archive 中已有 Gate 1 pass。点估计 `$10.40`、最坏调度形状预测 `$67.80`、硬上限 `$120`，endpoint 仍为
  `https://www.cctq.ai/v1`。
- 离线验收：M-5 Python 定向 183/183、Docker resume 精确探针单元测试 29/29、`just eval-lock`、ready、loopback
  均通过。append-only `m5-g1-rehearsal-v6-r3` 为 20/20 code-cell dispatch、0 Direct、0 failed；dump 7 页/log
  2 页到 null，七谓词全真，明文 9/加密与未知 0，成员自己的 exec Fact 可由 `team_evidence` 读回，并完成 Root
  update。正式 v6 archive/ledger/identity receipt 均不存在。

### 本任务剩余步骤

- v6 门前设施、准备性验证、文档与独立复核均已完成。经后续明确授权，正式 Gate 1 已执行并终止：
  a1..a6 均因开发工具 sandbox 阻断本机 relay 而归档为 `infra_failed / upstream_unavailable`，未形成产品结论。
- 按“Gate 1 未通过即停止”的授权边界，Gate 2 与 Docker 未启动。现有 v6 正式 attempt 已耗尽；本任务不重跑、
  不改写失败资产，也不把 clean smoke 或设施失败表述为正式 Gate 1 / M-5 通过。
- 后续授权允许纯执行环境修复使用独立 campaign generation，而不升级三把行为/产品锁。v6-c2 零费用门禁已完成；
  下一任务内动作是在 clean harness commit 上从批准的 sandbox 外边界启动 c2 Gate 1，并仅在通过后自动进入 Gate 2。

### 阻塞项

- c1 的 6 个正式 attempt 已全部持久化，不能原批次重领。开发工具 sandbox 会把解析为 `127.0.0.1` 的 CCTQ
  relay 当作 local/private address 阻断，因此 c2 正式进程必须在已验证的 sandbox 外网络边界运行。
- `multi-m5-v6-c2` 已取得独立正式资产、版本化授权口令与 c2 cap `$106.68`；用户已授权零费用验证通过后自动
  启动 c2 Gate 1，并仅在同一 v6 pass 后继续 Gate 2。当前没有其它已知门前阻断。
- `.env.local` 已静默确认存在、为普通文件、权限 `0600` 且所需变量非空；从未打开、搜索或打印其内容。

### 当前验收状态

- **正式 Gate 1：未通过。** 6/6 均为同因 infra，provider 可计价 `$0`，账本保守暴露 `$13.32`；没有产品失败
  或成功样本。Gate 2 未启动，M-5 未通过。终态见
  `agent_log/2026-08-20-180000-plan044-m5-v6-formal-gate1-infra-stop.md`。
- **v6-c2 执行环境整改：通过零费用门禁。** 三把 v6 锁摘要未变；c1 三资产摘要/语义、跨代预算、clean harness、
  predeparture、Gate 2 前置 prefix/ledger 顺序均机械验证。M-5 193 项、eval-lock、ready、loopback 已验证；
  sandbox 内 connectivity rc78/零资产，sandbox 外无密钥 HTTP 301 通过。正式 c2 尚未启动。
- 规划现场核对、worktree 创建与 ExecPlan：已完成。
- **阶段 A：两轮独立验收均不通过，第二轮缺口已由审查者直接修复。** 冻结 bundle、两份运行合同、
  接线与无 API loopback 核验通过；第一轮的门 1 谓词缺陷（Root 独角戏误判、未验 Root 唤醒）已整改并经复验确认；
  第二轮发现证据采集不绑定工具身份（`exec_command` 回显即可伪造门 1 通过），已按下述修复。
  在阶段 B 真实运行前，仍**不得**表述为 M-5 / 门 1 通过或未见退化。
- **门 1 证据绑定（审查者修复，2026-08-17）**：dump/log 只采纳 `team_inspect` 输出，唤醒信号只采纳
  `wait_agent` 输出；其它工具产出的"团队形状"负载记入 `unattributed` 并在判定中忽略、同时通过
  `CollaborationVerdict.ignored_evidence` 暴露，便于区分"模型伪造"与"wire 形状变了"。
  指令模板补充 `next_cursor` 续页要求，并重算 `instruction_sha256`。产品硬上限仍为 50，但省略 `limit`
  的实际默认页长是 20，响应现报告这个有效值；门前彩排另显式用 `limit=3` 强制覆盖续页分支。
- **~~wire 形状已用冻结二进制实测确认~~（该结论已于第五轮作废，保留原文以存历史）**：当时用直接注入
  function_call 的方式验证团队工具可执行，结论本身没错，但**那不是真实模型的调用方式**。
  `code_mode_only` 模型只发 `custom_tool_call(name=exec)`，团队工具全在 JS 里调，顶层 function_call 数为 0，
  因此 v1 的 `evidence_source` 在真实配置下不可能成立。现已改为 rollout-trace 口径并冻结 workflow v2。
- loopback 证明的是团队工具注册、一次 `team_publish` 往返与归档字段；**没有**证明投影进入后续采样
  或证据下钻。那两件事仍由阶段 B 门 1 真实运行判定。
- 阶段 B：runtime-v4 产品身份保持不变；v5 的 readiness 假设已由独立审查否决并以两把 v6 锁、严格协议判据、
  capture 隔离、provider 前置冻结和幂等 resume 收口。13:00 独立验收发现的协议时序、终止预算恢复和首请求前
  自有产物三组缺口，以及 15:00 审查发现的 deduplicated 假绿/跨线程 wrapper 假阴均已闭合；v6 离线门禁与
  append-only v6-r3 rehearsal 已通过。历史唯一
  clean-smoke-v5 仍只证明当时的非正式真实链路。本轮未新增真实 API 消费。正式门 1/门 2 未启动，v6 `$120`
  正式 archive/ledger/identity receipt 均不存在。
  **不得表述为 M-5 通过、门 1 通过或未见退化。**

### 阶段 B 精确授权清单

下表仍是未来正式门的冻结清单。本轮只获授权完成门前准备与验证性 smoke，且明确停在正式大规模付费测评前；
因此不得用本轮 1000 USD 的总授权替代下表的正式启动动作。

| 项 | 冻结值 |
|---|---|
| API provider | `rondo.local.toml` 的 `paid_eval.active_provider = "relay"`（CCTQ Responses；`api_key_env = OPENAI_API_KEY`）。不改官方入口，不把密钥写入文档或提示词。 |
| Root / 成员模型 | `gpt-5.6-terra` + `medium`（两侧相同）。由 M-5 两把锁自行钉死，不继承宿主 `paid_eval.main_model`（仍为 `sol`） |
| 合同身份 | `multi-m5-workflow-v6` → `multi-m5-runtime-v4` → `multi-m5-nondegradation-v6`；行为合同批次身份仍为 `multi-m5-phase-b-v6`，纯执行代次为独立 `multi-m5-v6-c2` / `multi-m5-phase-b-v6-c2`；v5 与 c1 均不原地修改 |
| 门 1 | host `codex exec` 协作 fixture，无 Docker；最多 6 次尝试、单次 1800s |
| 门 2 | v4 catalog 十任务；`task_major_codex_then_multi`；条件复跑仅当「Codex 完成、Multi 未完成」时双方各加两次 |
| 最大有效运行 | 60（基础 20 + 条件最多 40） |
| 退化诊断 | 仅在某题判为稳定单向退化后触发；每题最多 1 次、Multi 侧、V2 开 + team_state 关；不计有效结果、不改判定；与两道门共享同一 $120 与全部停止线 |
| 基础设施 | 每槽最多 5 次 infra 尝试；infra 总上限 40；infra 不计有效结果；共享 run 槽位 116 |
| 每 run 请求上限 | 80 |
| 价格快照 | 2026-08-18 官方页：input $2 / cached $0.20 / output $12 per 1M；长上下文 272k input×2 output×1.5；cache_write 1.25。同日核对 sol 仍为 5/0.5/30，故 terra 为其 40% |
| 费用 | 点估计 `$10.40`；最坏调度形状预测 `$67.80`（不是合法消费上限）；**跨代硬上限 `$120` 不变**。c1 保守暴露 `$13.32`，c2 账本批次 `multi-m5-phase-b-v6-c2` 的 cap 为 `$106.68` |
| 恢复 | 完整归档跳过；pristine 零请求 run 安全重领；精确 pre-Harbor 自有产物与已请求未归档各只追加一次 abandoned infra；终止 budget/capacity stop 归档后停止；未知、symlink、Harbor-started 或 exact Docker 残留 fail-closed |
| Docker | **只为门 2**。十个 digest 钉死镜像（见 `eval/locks/multi-m5-nondegradation-v6.json` 的 `docker_images`）。不拉其它镜像，不跑完整数据集。门 1 不用 Docker。 |
| 外发边界 | 任务输入、工作区内容与模型可见工具结果进入 Responses；密钥、`.env.local`、个人配置不进提示词或结果文件 |
| 预计时间 | 门 1：数十分钟级，打满 6 次可达数小时。门 2：无条件复跑时数小时到十余小时；若多题触发复跑或打满 infra，日历时间可到一天以上。全局串行，与重型 Cargo / 本地模型互斥。 |
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
| 018 | `root_resolved` 只认成员作者 Version；早期 `root_woken` 接受 inspect log 或 wait 原文 | ExecPlan 五项能力含 Root 唤醒；该早期口径后来仍可由成员 wait 冒充 Root | 门 1 判据 | 由 058/063 取代 |
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
| 047 | code-mode outer `exec/wait` 只有在同一 cell 完成过受支持的非 canonical team-state / evidence-read-only nested tool、结果为非空全 `InputText`，且该 response 为 terminal 时才铸一个 Fact；Yielded、纯 team-state/evidence-read、混合、加密、空输出拒绝。spawn/wait/send_message 属支持的协作通信工具，不在 canonical team-state 排除集 | runtime-v3 的“所有纯文本 outer cell”会让 publish/evidence/inspect 自身递归产证据；Yielded 的远端快照与 handler seal 之间还允许 nested completion 竞态。terminal 前 runtime 已排空 callbacks，是当前可证明的最小安全边界 | Multi 证据链 | 已采纳，取代原宽口径 |
| 048 | 证据链修复用新测量树与 `multi-m5-runtime-v3` 冻结，不覆盖 runtime-v2 | runtime-v2 的源码早于 `evidence.rs` 修复，复用其字节会让合同引用与真实产品不一致；旧运行仍须保持可追溯 | binary freeze / 合同身份 | 已采纳 |
| 049 | 开发沙箱在 provider 前拦截后，保留 clean-smoke-v3 的未结算 `$2.22` 预留与 capture，replacement 改用独立 clean-smoke-v4 | v3 已写入一次性账本与 capture，删除或复用会抹掉失败边界并破坏身份隔离；v4 仍只有 1 次、`$23.10` 硬上限 | 预算 / 证据分区 | 已采纳 |
| 050 | 本轮准备性真实 API 总授权提升到 `$1000`，但不得启动正式门 1/门 2 或创建 `$120` 账本；入口的更低硬上限不放宽 | 用户要求自主完成所有门前铺垫并停在大规模付费测评前。总授权是允许范围，不是消费目标，也不替代合同内 stop line | 执行授权 / 停止边界 | 已采纳 |
| 051 | runtime-v3 与 workflow/nondegradation v4 保留为终审失败历史；后继使用 runtime-v4、两把 v5 锁与 clean-smoke-v5 | runtime-v3 的第二页 inspect 实际 stale-cursor 失败，而 collector 静默跳过，形成假绿；旧身份不得在修复后升级冒充 | binary freeze / 证据分区 | 已采纳 |
| 052 | collector 必须拒绝 failed required inspect，且 dump/log 必须按返回 continuation 续页到 null 并覆盖 `total_entries`；fresh cursorless/offset-0 page set 可接受新总数 | 第一页谓词已足够时静默忽略第二页失败会假通过；反过来，不区分 continuation 与 fresh snapshot 又会误杀团队状态变化后的合法最终读取 | 门 1 判据 | 已采纳 |
| 053 | rehearsal 的 dump/log 初始页与续页固定显式 `limit=3`，且两者都必须至少两页并走到 null；页数写入结果/归档 | 修掉 team-only 假 Fact 后自然状态可能不超过默认 20 条，若仍依赖自然体量，彩排会重新退化为未执行 continuation 分支的假准备 | 门 1 彩排 | 已采纳 |
| 054 | code-mode recorder 的响应边界分成 Yielded / Terminal / Unavailable；MissingCell、首响应错误与不可转换响应一律不铸证并清理，wait 内部错误只为此前已知 live cell 保留重试状态 | MissingCell 没有 terminal callback-drain 证明，不能把泛化错误文本当 provenance；错误路径若留下任意未知 cell 又会逐步耗尽 256 项上限 | Multi 证据生命周期 | 已采纳 |
| 055 | v5 保持历史不可变；正式门改用 workflow-v6 / nondegradation-v6，继续复用未变化的 runtime-v4 与冻结字节 | v5 已承载 rehearsal/smoke，原地修改会让历史结果冒充新合同；本轮没有产品源码变化，无需重冻 runtime | 合同身份 | 已采纳 |
| 056 | Gate 1 最多 6 次；Gate 2 每槽最多 5 次 infra、全批最多 40 次；共享槽位 116；60 effective、80 requests/run、5 HTTP attempts 与 `$120` 不变 | 把有效样本与设施恢复机会分开；按最坏调度形状预测为 `$67.80`，仍由累计 reservation/settlement 的 `$120` 硬停止兜底 | 调度 / 预算 | 已采纳 |
| 057 | 正式 resume 以 batch + 两把合同锁 + runtime + provider receipt 绑定；完整归档跳过，pristine 零请求 run 原 id 重领，已请求未归档只追加一次 abandoned infra 后转下一 attempt，未来/重复/冲突状态拒绝 | 固定 run id 的 one-shot 入口无法承受长批次进程退出；恢复必须幂等且不能把产品失败改标 infra | 恢复语义 | 已采纳 |
| 058 | Gate 1 机械要求同成员完成首次 publish → Root publish → route → 自身 exec Fact 的 team_evidence → 二次 publish，Root 唤醒只认 completed wait_agent TeamActivity | v5 只从 dump 的 VersionFact 推断 evidence，缺调用、少一次成员 Version 或仅 inspect signal 都可假通过 | 门 1 判据 | 已采纳 |
| 063 | Gate 1 进一步要求首个成员 Version 精确引用被下钻 Fact、wait 来自 rollout manifest 的 Root thread、整条 trace 零 Direct，且 Root→member 投递仅 plaintext；Gate 1/2 共享完整 Gate 1 archive 前缀验证并拒绝 symlink 归档 | 独立终审构造出成员 wait、第二 Version 借 Fact、Direct dispatch、乱序 resume 与 broken symlink 等假绿/先消费后失败边界 | 门 1 / resume | 已采纳 |
| 064 | Gate 1 以 trace start/end + inspect-log revision 绑定 Root wait/publish/route/update、成员 evidence 与不同的二次 Version；恢复先保留 terminal budget stop，精确 pre-Harbor 自有产物可一次 abandoned，Harbor-started / exact Docker 残留保持 fail-closed | 13:00 独立验收构造出晚 wait、错误 actor、复用 Version、终止 stop 被重试及首请求前自有产物死路；自动继续带活动 Docker 的 run 无法证明安全，必须留给后继受监督精确清理 | 门 1 / resume / Docker 边界 | 已采纳 |
| 065 | 协议中的 publish/route 只认 `deduplicated=false`；跨线程 canonical 提交顺序只认 inspect-log revision，wrapper end 不作跨线程提交时钟；Root wait 以调用区间重叠 + 精确 wake log 绑定首次成员 publish，route start 先于 evidence start；批量 update 只要求唯一成员 resolve 匹配 | 15:00 审查证明幂等重试可冒充 evidence 后的新 Version，而 store 已提交后 wrapper 尚未结束是合法并发；继续使用跨线程 ToolCallEnded 判断提交先后会假阴并无故耗尽 6 次尝试 | 门 1 判据 | 已采纳 |
| 066 | 纯 sandbox / 启动边界修复不改 workflow-v6、runtime-v4、nondegradation-v6；另用 append-only `multi-m5-v6-c2` campaign generation 隔离 receipt/ledger/archive/capture/run-id | c1 没有模型观察，失败来自开发工具网络边界；为执行设施问题重冻产品或行为合同既无证据收益，又会让历史身份混线 | 执行代次 / 身份 | 已采纳 |
| 067 | 用户确认 c1 中转站实际账单 `$0`，但本地仍保留 `$13.32` conservative exposure；c2 cap 固定 `$106.68`，两代机械相加等于 `$120` | 外部账单事实不等于可回写已落账本；保留 fail-closed 暴露可避免不确定结算被重复消费，同时仍容纳 `$67.80` 最坏调度形状 | 跨代预算 | 已采纳 |
| 068 | 同一正式进程在 secret、receipt、ledger、claim、capture、Docker 前执行一次无密钥 direct GET；禁 body/auth/proxy/redirect，网络失败零正式状态、零 attempt；正式 identity 绑定 clean commit，Gate 2 还须先证明 c2 Gate 1 pass 与既有 ledger | c1 证明启动进程的网络边界本身会令全部六次失效；把 preflight 放到 receipt 后会留下假正式资产，把 Gate 2 prefix 校验放到 Docker 后会先产生外部状态 | predeparture / 正式入口 | 已采纳 |
| 059 | 测试必须显式传入 eval-data/tmp 下的隔离 capture root；v6 rehearsal、正式 Gate 1 与历史 v5 各用独立 identity，正式非空 capture 一律拒绝 | `persist=false` 旧实现仍会覆盖 canonical raw 并向 metadata 追加测试 observation | 证据分区 | 已采纳 |
| 060 | 完整 provider frozen preflight 位于 secret、正式 identity receipt、ledger open 与 claim_run 之前，并纳入 ready | 只在 Gate 2 executor 内校验会在零 API 时仍消耗第一个正式 run id | 付费入口 | 已采纳 |
| 061 | Gate 2 每个 attempt 形成分类后立即 fsync 归档，再允许 claim 下一 attempt | 若把同槽多次 infra 缓存在内存，下一 attempt 请求中断会留下两个未归档 run，无法按单一前缀恢复 | 恢复持久性 | 已采纳 |
| 062 | 两门的判定语义仍相互独立，但正式 Gate 2 入口要求同一 v6 archive 已有 Gate 1 pass | 避免在协议门已知未通过时启动更大的付费批次；该执行顺序不让 Gate 1 结果替代 Gate 2 判据 | 正式执行顺序 | 已采纳，收紧决策 037 的流程边界 |
