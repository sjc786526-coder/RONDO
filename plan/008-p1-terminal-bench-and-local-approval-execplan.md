# P1 执行计划：Terminal-Bench 最小真实链路与本地静态审批前置设施

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

对应 WBS：`doc/WBS.md` P1、`doc/WBS/eval-benchmark.md` E-B1～B3、
`doc/WBS/local-approval-model.md` L1 与 L2 搭建。Plan 003 的 B1～B3 约束继续有效；本计划以当前
`main` 和 WBS 为事实源，并取代 Plan 003 中已经过期的 P0/watchdog 阻塞状态。

## 1. 目标

### 最终目标

在一个开发会话内，用一套轻量、可测试、可归档的共享设施并行推进两条 P1 路线：

1. 冻结 Terminal-Bench 2.1 的实际版本、接口与任务镜像，以同一 runner 和运行规范接入冻结 Codex
   CLI `v0.147.0` 与 RONDO，先通过 no-API 门禁，再在授权预算内完成 1～2 个任务的最小真实 API 链路。
2. 完成 `E_final` Standard/Lite 的无工具静态审批协议（L1），并交付 llama.cpp server 配置、严格配置/
   密钥加载、client、doctor、fake server、结构化输出和启动入口（L2 前置设施）。本次没有模型权重，
   因而不做真实本地推理，也不宣称 L2 最终验收完成。

### 完成/验收标准

- 新建共享 `eval/` 设施，冻结版本化的 `RunSpec`、`PreparedRun`、`RunOutcome`、`ArtifactWriter`、
  `PolicyIdentity`、静态审批输入/输出和 `runs.jsonl` schema；两个方向不重复实现配置、解析和归档。
- B1 以官方发行物/文档和本机实测冻结 Terminal-Bench 精确包名、版本、依赖锁、adapter API、一个
  官方示例任务及其 image digest；不得保留浮动 `2.1.x` 或猜测接口。
- B2 只有一个 runner 和两个薄 adapter；`RunSpec` 是 Git common root `rondo.local.toml` 与受跟踪
  task/runner 配置的解析后冻结投影，不是第二个手工配置源。任务、镜像、模型、provider/base_url、
  Guardian、审批/沙箱、websocket、超时、retry 与预算缺失或两侧不一致时 fail-closed。
- 冻结 Codex 只从只读 `codex-source-code/` 复制到 ignored scratch，并仅对 135 个 workspace lock 条目做
  `0.0.0 -> 0.147.0` 机械规范化；两侧二进制各构建一次，记录来源、工具链、命令和 SHA-256，run 不隐式编译。
- adapter、配置、Standard/Lite 解析、PolicyIdentity、归档、预算、secret redaction、fake server 和 L2
  client/doctor/launcher 的 no-API/本地测试通过；不另建重型测试框架。
- L1 把 Standard/Lite `E_final` 解析成同一版本化逻辑 payload；出站无顶层 `tools`、无 Lite
  `additional_tools`、无 warehouse-only `executed_tool_calls`、无 provider-private
  `encrypted_function_args`，同时必须保留有意义的 approval/retry reason。Luna/Sol/Local static 组获得
  的规范化 JSON 字节完全一致，并返回结构化 `allow|deny + reason/rationale + risk tags`。
- `PolicyIdentity` 只基于明确提取的实际 policy UTF-8 字节计算 SHA-256，不 trim、不做 Unicode
  normalization；形态冲突、候选不唯一或缺失时标 `unknown` 并禁止跨 policy 聚合。
- 云端和本地模型的 provider、base URL、model、effort 与请求参数都只从 Git common root 的
  `rondo.local.toml` 读取，只从同根 `.env.local` 严格解析并 allowlist 注入所需变量；不得 source shell，
  不得向输出、日志、命令行或工件泄露 Key。
- 冻结一个项目局部 llama.cpp server 运行时及 SHA-256，doctor 能区分配置错误、缺模型、服务未启动和
  endpoint/schema 错误；fake server 能覆盖 `/v1/responses` 结构化响应。无权重时终态明确为
  `infrastructure_ready_model_missing`，真实推理、显存、上下文预算和延迟均标未运行。
- B3 最多 `2 task × 2 side × 1 round = 4 run`；先单任务双侧，健康且预算可控才进入第二任务。
  主模型和 Guardian 均为 `gpt-5.6-luna`，Guardian effort 为 `low`，真实 API 按量付费总硬上限
  20 USD。若无法在启动前可靠约束剩余预算则停止；401/403/429 不循环重试。
- M1 只有在同一 task 的 Codex/RONDO 两侧都得到 `completed` 且结果可归档时才通过；任一侧只有
  `infra_failed`、预算因价格/usage 不可可靠约束而零调用，或没有真实 API 证据时，B3/M1 均保持未通过。
- 每条 run 原子写 `eval-data/runs/<run_id>/`，再以锁保护追加 `eval/results/runs.jsonl`；终态和退出码
  区分 `completed|agent_failed|infra_failed|budget_stopped|cancelled`，并诚实记录 Docker/fake/API/
  未运行证据。`git_dirty=true` 的结果不得作为里程碑证据。
- L1 malformed/歧义 evidence 返回 65，非法结构化输出返回 66；L2/runner 配置错误返回 64，服务不可达
  返回 69，内部/基础设施错误返回 70，预算停止返回 75，模型缺失返回 78；只有合规成功返回 0。
- 完成后只运行受影响模块的必要门禁，审查意外产物与所有 worktree；更新权威 WBS、完成历史和精炼
  `agent_log`，提交开发分支，合并并推送 `main`，再核验 `main == origin/main`。

## 2. 范围

### 允许修改

- 新建顶层 `eval/`：共享合同、配置 loader、证据解析、静态审批协议、归档、Terminal-Bench runner/
  adapters、L2 client/doctor/fake server/launcher、轻量 fixtures 与测试。
- `mydev/justfile` 或根级轻量入口：增加 doctor/build/smoke/run/local-approval 命令；任何 Cargo、Docker、
  编译、链接或其他重型入口必须进入全仓共享看门狗锁。
- 必要的 Docker 专用监督脚本：容器资源、生命周期、存储与宿主空间门禁；只管理本任务明确创建并标记的对象。
- Terminal-Bench 与 llama.cpp 的项目局部精确版本/lock/checksum/安装清单；缓存、二进制和大产物保持 ignored。
- `.gitignore`：仅补充实测产生的本地缓存、scratch、工具和原始产物路径。
- `doc/WBS.md`、相关 `doc/WBS/*.md`、`doc/eval-data-layout.md`、`doc/development-environment.md`：仅同步
  当前事实和阶段边界；完成证据写 `doc/WBS-COMPLETED.md`。
- `agent_log/`：一份精炼实施与验收日志；本计划的“当前状态”和关键决策持续更新。

### 不允许修改

- `codex-source-code/` 与 `codex-doc/` 的内容和状态；`reference-agent-harness/` 只读参考，不在其中开发。
- RONDO/Codex 核心 agent 行为、Guardian policy、审批/沙箱安全语义、Terminal-Bench task/verifier。
- L2a provider 覆盖、L3/L4、权重下载、真实本地推理、训练、正式 canary、离线回放和方向 1 优化。
- 宿主 Docker Desktop、DNS/Clash、代理、GPU 驱动、系统服务、全局工具链或项目外仓库配置。
- 来源不明的既有镜像、容器、网络、卷、缓存、worktree 修改、未跟踪日志或历史测评资产。
- 发布、PR、CI、上传、云 GPU、训练、批量 API 测评或超过 20 USD 的真实 API 调用。

### 不允许读取/查看

- `.env.local` 的 Key 明文；只允许静默检查文件/权限和由严格数据 parser 在目标子进程内读取所需非空变量。
- 项目外个人文件、个人配置、真实会话记录及其他仓库。
- P2 未来隐藏集的任务正文、verifier、单任务日志和单任务结果。
- 非本任务所需的其他 worktree 未跟踪内容。

## 3. 硬约束

1. **授权边界**：用户已授权项目内编辑/测试/依赖、Docker、项目局部 llama.cpp 运行时下载、两侧受控构建、
   最多四次 Luna 真实 API run 和总计 20 USD 按量付费；任何权重下载、真实本地推理、数据另行外发、
   L2a/L3/L4/训练/canary 或超预算属于意外扩展，必须停止并重新确认。
2. **重型任务全仓串行**：Cargo、编译、链接、Docker 和其他重型任务必须共享
   `mydev/scripts/with-build-lock.sh` 的同一 flock；任何时刻只能一项，主工作区/worktree/容器/本地模型互斥。
3. **看门狗 fail-closed**：拿不到 flock、systemd cgroup、资源计数器、Docker 实际数据盘计数或容器限制时
   不启动。Cargo target 位于 RONDO 根内；不得直接 Cargo 或绕过并发/内存/磁盘上限。
4. **Docker 双重监督**：CLI 进入共享锁；容器另设明确 memory/swap/pids/wall timeout、前台生命周期和
   唯一 label/name。pull/build/run 从启动前到退出后必须周期采样 `docker system df`、本任务对象大小与
   Docker Desktop 实际数据盘宿主剩余空间；计数不可读即停止。相对本次基线新增 40GB 实时告警、60GB
   实时停止，宿主实际剩余低于 80GiB 立即停止。只清理本任务对象。
5. **构建空间有界**：开工先清理明确可再生的旧中间产物；两侧按“构建一个、固化二进制、清理 target、
   再构建另一个”串行，避免历史约 126GB 的两个 target 共存。任务结束再次清理中间产物。
6. **秘密最小化**：`.env.local` 必须是主根普通文件、0600；严格 `KEY=VALUE` 数据解析、拒绝 shell 语法/
   重复项/未知使用，不打印内容；只向目标 API 子进程注入 `OPENAI_API_KEY`。`rondo.local.toml` 不得含 Key。
7. **公平条件**：两侧同任务/digest/顺序/网络/timeout/retry，`supports_websockets=false`、
   `approvals_reviewer=auto_review`、`approval_policy=on-request`、`sandbox_mode=workspace-write`，主模型和
   `sandbox_workspace_write.network_access=true`，主模型和 Guardian 为 Luna，Guardian effort low；差异必须
   被机器拒绝。容器只持预算代理的短生命周期下游 token，真实上游 key 不进入容器。RONDO 用 S1 显式覆盖；冻结 Codex 没有
   该配置面，因此必须由 runner 的共享、去敏 loopback metadata probe 观测实际 Guardian 出站请求中的
   model/effort 并匹配后才算合规，不能用 `RunSpec` 期望值冒充实际生效证据。
8. **预算可阻断**：20 USD 是总硬上限而非目标消费；费用按官方 API 直接按量计费口径。无法取得可靠单价、
   usage 或单次最坏情况上界时不得启动下一 run；设施探针失败不自动扩大 retry，已花费与剩余额度必须留档。
9. **真实/fake 分层**：Python 单测、fake HTTP、no-API adapter、Docker task smoke、真实 API、真实本地模型
   分开记录；skip/未运行/网络失败/容器失败不算通过，`infra_failed` 不算 agent 成败。
10. **L1 无工具且逐字节公平**：只比较 provider-neutral canonical payload；URL/header/auth 不在逻辑比较内。
    原 Guardian policy 与其 hash 保持原样，另附静态“仅据现有证据、不得取证”约束，不修改 policy 冒充同一身份；
    provider-private `encrypted_function_args` 必须剔除，approval/retry reason 必须保留并有双形态回归。
11. **L2 停止线**：不下载权重、不启动真实推理、不量显存/上下文/首 token/总耗时；配置、runtime、client、
    doctor、fake、结构化输出和 launcher 可交付，但 WBS 的真实 L2 验收保持待模型接入。
12. **原子与脱敏**：run staging 无覆盖 rename，JSONL 使用 append lock，终态前做敏感键/header/URL 扫描；
    原始 `E_final`/日志按私有会话数据留在 ignored `eval-data/`，权限收紧，不提交、不外发给静态云模型。
13. **保护既有状态**：不回退、覆盖、stash、删除来源不明修改；保留
    `0809-remaining-test-failures` 的未跟踪日志。手工编辑用 `apply_patch`，搜索优先 `rg`。
14. **不凑绿**：不得放宽安全、审批、task verifier、超时、资源阈值或删除失败详情来换取通过。

## 4. 软性建议

1. 串行前置顺序：清理可再生旧产物 → 建 worktree/计划 → 冻结共享 schema → B1 官方勘察与 Docker
   监督落地。共享合同稳定后，B2 runner 与 L1/L2 轻量代码可由子智能体并行实现。
2. 顶层 `eval/` 采用 Python 3 标准库优先的轻量包，避免向 `codex-core` 塞新概念或新增重型 Rust crate；
   必需依赖用 uv 精确锁定。`mydev/` 只放稳定 just/看门狗入口。
3. `PolicyIdentity v1` 对 exact policy bytes 哈希；`StaticApprovalPayload v1` 只含 schema version、policy、
   清理后的 task input 与冻结的 static output schema；canonical JSON 使用 UTF-8、排序键和紧凑 separators。
4. `ArtifactWriter` 独占 staging/rename/secret scan/JSONL lock；adapter 只返回结构化 outcome 与 artifact refs。
5. B1 先用 no-op/fake adapter 验证一个低资源官方示例任务容器；确认 digest 和 container 限额后才进入双侧构建。
6. L2 优先取官方项目局部预构建 llama.cpp server 并固定版本/SHA；无匹配发行物时才考虑受看门狗的源码构建。
7. 实现和 no-API 验收先提交；再从该 clean commit 创建 detached measurement worktree，固定二进制、
   `RunSpec` 和 source commit。真实 run 均在 clean measurement worktree 执行，结果索引写开发 worktree，
   避免首条 `runs.jsonl` 使后续 run 的 `git_dirty` 失真。
8. B3 串行顺序：任务 1 RONDO 设施探针 → 同任务 Codex（或按公平性需要冻结顺序并记录）→ 两侧健康且
   剩余预算足够才考虑任务 2；任何一侧基础设施失败都保留可恢复现场并停止扩展。
9. 轻量代码完成后先定向测试和 no-API smoke；只在共享 Rust crate 被改时按 `mydev/AGENTS.md` 扩大相应
   Nextest/fix/fmt 门禁，不默认重跑完整 workspace。
10. 后续宏观路线保持 WBS：P2 再做 B4～B7、E-A、L2 真实验收、L2a/L3/L4；P3 才进入数据合成与训练。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-09：用户一次授权 Docker、项目局部依赖、受监督构建、清理、必要测试、合并/推送，以及最多
  四次 Luna 真实 API run；按官方 API 按量付费总硬上限由 10 USD 提高到 20 USD。
- 凭据门禁确认复用主仓库 `.env.local` 中现有 `OPENAI_API_KEY`；未读取或输出明文。
- `main` 与 `origin/main` 对齐于 `4df098c`，V8 资产门禁已合入；主工作区干净。
- 已由看门狗清理 V8 worktree 的 Cargo target，并清理两个 Python cache；全仓未发现其他 target。
- 已落地共享 `eval/` 合同、严格配置/密钥 loader、Standard/Lite `E_final`/`PolicyIdentity`、无工具
  static payload、归档骨架和持久预算账本；独立审查确认 crash consistency、合法 ToolSearch evidence、
  pair/batch 门禁和最小逐 run 指标仍需收口，不能把骨架表述为完整验收。
- Harbor 冻结为 `0.20.0`/commit `459ff6e`，TB2.1 冻结为 commit `ffccbe0`，`fix-git` task archive
  与 linux/amd64 镜像均已按 SHA-256 实测；真实 checkout 的 materialize/digest/overlay 前置校验通过。
- Docker Desktop daemon/数据盘计数已接入；受监督拉取 `fix-git` 和 Ubuntu 精确 digest，官方
  hello-world oracle no-API Docker 验收为 1/1 completed、reward 1.0、0 error，全程无存储告警。
- 统一 runner、双上传式 adapter 和生产 Harbor backend 已接线；禁止 npm/latest 和 Harbor 内置危险
  bypass，Harbor 全生命周期由共享锁、cgroup 与 Docker 5 秒采样共同监督。
- 官方 Luna Standard 单价已冻结，持久代理按请求预留、usage 结算并强制 20 USD batch、5 USD/run、
  最多 4 run；容器到宿主 127.0.0.1 代理的 Docker Desktop bridge 已用 no-API TCP 实测。
- llama.cpp 冻结为 b10333/commit `0865990` 的官方 CPU x64 asset，下载/安装文件及 `llama-server` SHA
  已核对；无模型 doctor 在看门狗下返回 `infrastructure_ready_model_missing`/78，未加载或推理模型。
- L1 与 L2 client/doctor/fake/launcher 已落地；L2 结构化输出仍明确标为 b10333 pin-specific、待模型实测。
- 独立计划审查发现原编号与 V8 Plan 007 冲突，已改为 Plan 008；同时补齐配置唯一来源、evidence transport
  字段、clean measurement worktree、Docker 持续采样、退出码和冻结 Codex 实际 Guardian 条件证明。
- clean 实现提交 `cb652e1` 已用于 detached measurement worktree。两侧 GNU release 均在看门狗内成功构建、
  冻结后清理，但目标 `fix-git` Debian 镜像缺少宿主 glibc 2.38/2.39，故改用同一 Rust 1.95 的
  `x86_64-unknown-linux-musl` 静态目标；RONDO/Codex musl 构建分别在 16m21s/16m26s 完成，swap 峰值均为 0。
- 两侧 musl 二进制均通过无 `INTERP`/`NEEDED` 的 ELF 门禁，并在固定 `fix-git` 镜像内以只读挂载、
  `--network none` 执行 `--version` 成功；Docker 总占用前后均为 18.128GB，无告警或残留容器。
- 三次 Codex B3 尝试均在 API 前 fail-closed 并归档，实际费用保持 0 USD：先后暴露 Harbor ExecResult
  optional stream、GNU/glibc 可移植性、以及 v0.147 禁止覆盖内置 `model_providers.openai`。前两项已由
  真实重跑验证越过；第三项已改为隔离的 `rondo_eval_openai` Responses provider，25 项定向回归通过。
- RONDO companion 的前两次受监督构建均保留失败 summary：第一次证明 helper 的独立依赖图没有继承
  `codex-core` 的 vendored OpenSSL feature；同次选择 core 后越过该点，但又证明原 V8 gate 按 GNU rustc
  host 选择的归档不能链接 musl。两次均为构建错误、非资源停止，swap 峰值为 0。
- 独立审查的本阶段缺口已收口：pair/Harbor identity、公平拓扑、Docker 有效态、watchdog proof、
  Compose 资源清理、结果交叉约束、crash-consistent 归档、L1 ToolSearch/sink、L2 完整 runtime
  closure/redirect/model identity 均进入生产门禁与回归。runner-host 五键 metrics 已接线，但不含 daemon
  容器进程；容器 CPU/峰值内存明确延期到 paid B3 启用前完成。
- 固定镜像的 default/custom seccomp 反事实证明 builtin profile 是 nested user namespace 阻断原因；
  受跟踪最小 profile 下 RONDO→Codex no-API 配对 v3 两侧通过，未使用 privileged、`SYS_ADMIN` 或
  `seccomp=unconfined`。轻量门禁为 237/237，`uv lock --check` 为 85 packages。

### 当前工作

- F-01～F-16 的 B2/当前阶段整改、定向 Docker 诊断与双侧 no-API 配对均已完成；F-16 的容器性能
  指标按决策 029 延期为 paid B3 启用门禁。正在同步权威文档、清理本批工作目录并进行独立终审。
  实现仍位于 `0810-plan008-review-remediation` 独立 worktree。
- 受跟踪 pair lock 当前为 `p1-fix-git-pair-v3`；RONDO 槽位 1 与 Codex 槽位 2 均 completed，旧 v1/v2
  诊断账本保留失败终态，不复用或删除。

### 后续计划

- 本批只剩最终必要门禁、独立终审、详细日志、合并与推送。
- 若后续重开 B3，必须冻结新的 paid pair/batch manifest、任务轮次与预算并重新取得批量真实 API 测评授权；
  当前生产 paid mode 保持 hard-disabled。

### 阻塞项

- 本地模型权重不存在且本次禁止下载；L2 真实推理验收必然保持未运行。
- 本批没有真实 API 授权下的新公平 paid pair，因此 B3/M1 不运行；这不再阻塞已完成的 B2 no-API。

### 当前验收状态

- B1 的版本/task/image 资料冻结、Docker hello-world oracle、两侧静态 musl bundle 与目标镜像
  `--version` 探针保留为真实通过项；B2 公平/身份/有效隔离/归档与双侧 no-API 已验收。
- L1 协议、合法 ToolSearch evidence、最终 sink 与三组 consumer 协议逐字节 fixture 已验收；不宣称三套
  生产调用端均已实现。L2 是完整闭包已冻结、
  redirect/endpoint/model identity 已收口的无权重前置设施，真实结构化推理仍待模型。
- 三次旧诊断已迁移为 `infra_failed` 永久记录，预算槽不可复用；本批真实 API 调用 0 次、费用 0 USD。
  B3/M1 未运行，不能由 no-API completed 或 reward 0 结果代替。
- L2 真实模型、L2a、L3/L4、训练和正式 canary 均未运行且不在本计划完成条件内。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 新建 Plan 008，引用但不直接改写 Plan 003 | Plan 007 已被 V8 使用；本次又增加 L1/L2 | 计划与阶段边界 | 已采纳 |
| 002 | 先冻结顶层共享 eval 合同，再并行两条路线 | 避免重复配置、解析、policy identity 与归档 | 架构 | 已采纳 |
| 003 | eval 设施优先使用轻量 Python 标准库 | 降低 Rust 编译与 `codex-core` 膨胀，适合 runner/fake/doctor | 实现 | 已采纳 |
| 004 | Docker 在共享 cgroup 锁外再加容器/存储专项监督 | Docker daemon/容器不属于调用端 user cgroup | 资源安全 | 已采纳 |
| 005 | 真实 API 最多四 run、20 USD 总硬上限 | 用户明确授权；先证明链路，避免扩大成 canary | B3 | 已采纳 |
| 006 | 冻结项目局部 llama.cpp server，但不下载权重 | 达到代码/运行时只待模型接入，同时遵守无真实推理边界 | L2 | 已采纳 |
| 007 | 两侧二进制逐个构建并清理中间 target | 历史单 target 约 126GB，避免双 target 叠加 | 构建 | 已采纳 |
| 008 | 真实测量使用 clean detached worktree，结果索引写开发 worktree | 保持所有 run 的 source dirty 判定与 commit 相同 | B3 归档 | 已采纳 |
| 009 | 冻结 Codex 的 Guardian 条件由去敏 metadata probe 实测 | 上游没有 S1 配置面，期望配置不能证明实际请求 | 公平性 | 已采纳 |
| 010 | 付费链路只允许经宿主 loopback 预算代理 | key 留在宿主；容器拿临时 token，代理按 usage 结算并可停机 | B3/秘密/预算 | 已采纳 |
| 011 | 官方 provider 身份与 ephemeral Docker transport 分离 | `rondo.local.toml` 仍是云参数唯一源，bridge URL 只是运行设施 | 配置/公平性 | 已采纳 |
| 012 | Codex 不注入 RONDO 专属 auto_review 字段 | 上游 strict config 不支持；由实际出站 Guardian payload 证明 Luna+low | 基线兼容 | 已采纳 |
| 013 | 双侧二进制改为静态 musl，并保留 GNU 失败归档 | 目标任务镜像为 glibc 2.36，宿主 GNU 二进制需要 2.38/2.39 | B2/B3 可移植性 | 已采纳 |
| 014 | 用自定义 `rondo_eval_openai` provider 投影 loopback transport | v0.147 禁止覆盖内置 `openai`；仍需禁 WebSocket、零重试并复用 OpenAI auth | B2/B3 transport | 已采纳 |
| 015 | 两侧启用并冻结同源 `codex-code-mode-host` companion | Luna 为 `code_mode_only`；关闭 host 会在首次 API 前拒绝执行，单 CLI manifest 不能形成真实工具链 | B2/B3 二进制公平性 | 已采纳 |
| 016 | 容器内 workspace-write 显式允许网络，不授予 Docker 特权 capability | 默认 bubblewrap 网络命名空间在 Docker Desktop 内不能初始化；文件系统沙箱仍保留，真实 key 仅在宿主预算代理 | B2/B3 sandbox | 已采纳 |
| 017 | runtime bundle 按上游布局内置同源 `codex-resources/bwrap` | 任务镜像不应 apt/PATH 注入浮动 sandbox；冻结包必须自包含 v0.147 Linux 运行资源 | B2/B3 二进制公平性 | 已采纳 |
| 018 | 复用官方 v0.147.0 musl bwrap 资产并验证两侧源码 tree identity | 自建链路会额外冻结 Linux UAPI/C 依赖；两侧源码逐树相同，官方同版本资产更小且可直接验签 | B2/B3 构建与供应链 | 已采纳 |
| 019 | Terminal-Bench 主 service 和 agent 固定为 1000:1000 | 让内层 bwrap 使用非特权 user namespace；不授予 Docker 特权 capability 或关闭 seccomp | B2/B3 sandbox | 已采纳 |
| 020 | 默认 seccomp 下 nested namespace 仍失败后停止 B3 | 安全边界只能经新的精确授权改变；计划禁止为凑绿弱化隔离 | B3/M1 | 已采纳 |
| 021 | run-id 在外部执行前同时 claim 归档与预算槽，claim 后异常也发布分类失败记录 | 禁止复用 run 绕过四次上限，避免已计费请求没有结果索引 | B3 预算/归档 | 已采纳 |
| 022 | API 前设施诊断不进入正式结果库 | 三次尝试没有模型请求，旧归因与新 parser/allowlist 不一致；预算账本仍保留不可复用历史 | B3 数据 | 已采纳 |
| 023 | 独立审查 F-01～F-16 作为本批修复与重新验收清单 | 原实现存在公平、有效态、崩溃一致性和能力口径缺口；已完成异议复核 | Plan 008 收口 | 已采纳 |
| 024 | namespace/seccomp 只做固定容器的最小定向诊断 | 用户明确授权；需要区分 seccomp、userns/capability 与 daemon 行为，仍禁止特权化绕过 | B2 Docker | 已采纳 |
| 025 | no-API 与 paid 共用受跟踪 pair identity/preflight，paid 默认禁用 | 把两侧 bundle、Harbor closure、公平字段与执行顺序变为启动前机器门禁 | B2/B3 | 已采纳 |
| 026 | 归档改为 journal v2 + 完整 index 原子 replace | partial write/进程死亡后仍能按 pre/post identity 恢复，拒绝工件篡改 | 结果归档 | 已采纳 |
| 027 | 以 Moby v0.2.3 为基线，只为 non-CAP_SYS_ADMIN bwrap 增加最小 syscall delta | 定向反事实确认 builtin seccomp 阻断，同时保持 non-root/cap-drop/NNP | B2 Docker | 已采纳 |
| 028 | Compose provider secret 使用 0600 私有 staging 文件而非 Harbor environment | daemon 能核对 exact RO mount，bearer 不进入 Harbor env/argv，执行后清空 | B2/B3 秘密 | 已采纳 |
| 029 | runner-host rusage 仅作设施诊断，paid B3 前补容器 CPU/峰值内存 | Docker 进程由 daemon 管理，self+children 不覆盖 agent，不能把局部 RSS 冒充跨侧性能 | B3 metrics | 已采纳 |
