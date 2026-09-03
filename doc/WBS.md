# RONDO 长程规划（WBS）

最后更新：2026-09-03 ｜ 状态：**项目当前无 active 工作包**。

方向 0、1、2、3 与跨方向的发布工程均无在办事项。最近一轮跨方向的「产品线配套补齐与逐条收口」已按
“先 Multi 收口、再 Local 收口”两阶段全部关闭：两条产品线各自完成配套补齐、独立空间门、禁用 incremental 的
全 workspace 门禁、实质代码与功能冻结、正式版发布与公开复验，随后按用户逐对象授权完成构建缓存清理。
任何新工作都须另行立项与授权。

本文件与 `doc/WBS/*.md` 是项目**当前状态与后续规划的唯一来源**。本文件只保留阶段指针、跨方向关系、
稳定工程边界和授权门；已完成成果与验收见 `doc/WBS-COMPLETED.md`，单次任务合同见 `plan/`，执行细节见
`agent_log/`，研究与审计材料只代表其形成时点。

## 1. 当前状态

上游基线冻结为 Codex CLI `v0.147.0`（`rust-v0.147.0`，commit
`be6e8eac029b183056b7e4402879f15d2c85f61b`）；机器事实源为
`mydev/codex-rs/core/upstream-source-baseline.toml`。上游升级仍是未排期待办，启动时再冻结目标版本，
不得混入普通功能任务。

项目包含两套并列产品源码：`mydev/` 与 `multidev/`。当前方向状态如下：

| 方向 | 当前状态 | 当前规划边界 |
|---|---|---|
| 0：量化测评基准 | 既有设施与首次 schema v7 正式 canary 已完成，当前无 active campaign | 保留设施；历史结果见 COMPLETED，新 campaign 须重新立项与授权 |
| 1：Harness 优化 | **正式收口；当前无 active 工作包** | 不继续新增观测或内核/热路径优化；既有实现、设施与历史结果保留。未来可由用户另行决定是否重新立项，本次收口不作永久禁止 |
| 2：本地审批模型 | **已收口，今后不再开启** | 最终结论为“保留为实验”；不改生产默认，不再规划后续工作包 |
| 3：RONDO Multi | 第一、二、四期已完成；三期工作包一/二/三已执行，工作包三形成有效训练 `NO-GO` 且无候选，**工作包四未解锁**。**当前无 active 工作包** | 产品默认 `OFF`，云端 backend 需显式选择；不读冻结测试、不训练、不改产品默认，不授予 qualification、产品价值或生产资格。详见方向 3 子 WBS |

### 产品线冻结与发布状态

两条产品线的实质代码与功能**均已冻结**，各自的最终全 workspace 门禁是其发布候选的正确性依据：

- **Multi**：`14713/14713` passed、0 failure/error/timeout/retry，另 1/1 setup passed，24 skip 不计 passed。
- **Local**：`14122/14122` passed、23 skipped，零 failure/error/timeout/retry/flaky。

两轮均在 default features、standard local Nextest、checksum-verified V8、`CARGO_INCREMENTAL=0` 的完整 workspace 上取得，
并各自通过独立验收、合入 `main` 与 exact-main 轻量 CI 复验。正式证据见 `doc/WBS-COMPLETED.md` 与对应 `agent_log/`。

**冻结口径**：这里的“冻结”是该产品线不再实质性修改代码与功能，使最终通过的全量测试结果持续适用于发布候选；
它不是全树逐字节冻结。`CHANGELOG.md`、发布后 README 固定链接以及 WBS / 完成记录仍可按既有流程更新。
任何发生在冻结后的实质性代码或功能改动都会使冻结失效，必须重新执行受影响验证并重跑最终全量门禁后才能发布。

**仓库已公开**，两条产品线各有正式版本：Local 为
[`local-v0.1.1`](https://github.com/sjc786526-coder/RONDO/releases/tag/local-v0.1.1)，
Multi 为 [`multi-v0.1.1`](https://github.com/sjc786526-coder/RONDO/releases/tag/multi-v0.1.1)
（首发 `local-v0.1.0`、`multi-v0.1.0` 保留不变）。各版本均以未认证访问复验通过，公网 `SHA256SUMS` 与本机产物逐位一致。
GitHub 仓库级 `latest` 指针随最新正式版落在 `local-v0.1.1`，它只是平台展示状态，**不代表任一产品线的版本权威**；
对外入口一律用 README 里各自的固定 tag 链接。

### 发布工程与 CI（跨方向，已完成并冻结）

发布工程能力由 Plan 103 交付，**只交付发布工程本身**，不推进任何方向的产品功能、性能或质量资格。
使用与维护文档：CI 见 [`doc/ci-pipeline.md`](ci-pipeline.md)，发布流水线见 [`doc/cd-release-pipeline.md`](cd-release-pipeline.md)。
两篇都以不变量清单开头（CD 篇按“静默失效 / 延迟间接失败 / 明确失败”三档标注后果），改动流水线前必读。

**当前能力**（已落地并实跑验证）：

- 根 `.github/workflows/ci.yml`：push 到 `main` 触发，按三类路径分流到受影响产品线，
  跑 fmt / build / test 三门禁。冷跑约 23 分钟、热跑约 12–14 分钟。
  **只跑 crate 子集**，全量门禁仍在本地（标准 runner 16 GB，本地全量需 21 GB）。
  Multi 选包含 `codex-team-state`；两条线均**不含** `codex-tui`，Local TUI 正确性继续由本地定向门禁证明。
- 根 `.github/workflows/release.yml`：`local-v*` / `multi-v*` 两条发布轨互不夹带，
  tag 经严格 SemVer 校验（拒前导零，`-rcN` 标为 prerelease）。RC **绝不占用**仓库级 `latest`
  指针（硬门禁）；正式版则接受 GitHub 的指派——平台不允许唯一的正式版退出该指针。
  产出 `x86_64-unknown-linux-musl` 的**完整产品包** + 第三方许可材料（含 Cargo 闭包与
  V8/ICU 原文）+ `SHA256SUMS`，并在独立的干净 runner 上做发布前验证。

**两处已批准的产品侧窄例外**：E-X1（打包变体新增条目）、
E-X2（`check_for_update_on_startup` 默认值改 `false`，并把 `doctor` 的上游探测门控到同一开关）。
二者均不改动 workspace 版本号、crate 名与 `[[bin]]` 名，冻结二进制身份与公平对比设施不变。

**后续发布**：新版本走同一条流水线，打 `local-v*` / `multi-v*` tag 即可。
README 的下载链接是固定 tag，发新版本时需同步更新。

### 云端资源终态

2026-09-02 实测：RunPod 账户 **0 Pod、0 网络卷**，compute 与存储费率均为 `$0/h`；最后一笔存储计费落在
2026-08-31，此后账单为 0。**本项目当前不持有任何云端资源，也没有持续费用。**

历次任务记录中由用户决定保留的网络卷 `mwemzrn33y`（Plan 082 → 087 → 090 → 094 → 099 依次使用并扩容至 100GB）
**已不存在**。因此只存在于该卷上的大型 checkpoint 与权重不再可恢复；本地保留的是各任务当时已逐对象校验回传的证据。
`doc/WBS-COMPLETED.md` 中“卷保留”一类表述均指该任务完成时点的历史事实，不是当前状态。

这不改变任何已冻结的任务终态与结论——那些结论由已回传并校验的证据支撑，不依赖卷上权重。
任何重建云资源、恢复训练或重跑历史轨迹都须另立任务并重新授权。

### 已排除的方向（减法决定）

以下是收口过程中明确决定**不做**的事项；将来改主意须另行立项：

- 不给 Local 新建 TUI 面板：Local 没有需要交互管理的持久对象，Guardian 随审批流走，一行 status 足够。
- **不在产品树 `docs/` 下新建配置文档**：两条线的 `AGENTS.md` 都禁止向 `docs/` 增加通用产品或用户文档
  （唯一例外是 app-server API 文档）。RONDO 增量配置指南只放在仓库根 `doc/rondo-config.md`。
- 不改上游 `docs/` 既有文件与 `codex-rs/config.md`：会增加与 `codex-source-code/` 的 diff 噪音，
  违反产品树保持可直接比较的自我约束。
- 不在 `/status` 单列 Publication Critic：它 default-off 且判官质量未过关，给它独立位置会误示为可用发布门。
  Multi 至多显示 `multi_agent_v2` 总开关。
- 不把 Team Lens 迁入产品树：它是 `eval/rondo_eval/team_lens/` 的离线分析工具，不随 release 包分发，维持现状。
- 不把 `codex-tui` 纳入 CI：快照测试对 16 GB runner 偏重，收益不明确。
- 不提升 `exec_command_repeat_guidance` 的 Stage：方向 1 已收口，不再引导使用。

### 方向命名口径

- 后续规划、任务与汇报统一使用“方向 1”和“方向 3”，不再使用“Local 方向”指代方向 1。
- `mydev/` 是方向 1 当前产品源码位置；`multidev/` 是方向 3 产品源码位置。目录名称不等于方向名称。
- `RONDO Local` / `rondo-local` 仅在必须区分现有产品或运行身份时使用，不代表方向 2。方向 2 专指已经收口的
  本地审批模型研究。

## 2. 下一工作包与顺序

**当前没有 active 工作包，也没有已排定的下一个工作包。** 方向 0/1/2/3 与发布工程均无在办事项；
任何新工作都须由用户另行立项，并按第 6 节重新取得授权。

已知的、仍然存在但**未解锁**的唯一路线是方向 3 的工作包四（模型资格验收与横评）。它的解锁前置是先有一个通过
开发准入门的本地候选模型；三期工作包三没有形成候选，历次诊断与工程接入也不自动解锁它。目标、边界、
宏观验收与重启方式见 [`doc/WBS/multi-agent-trusted-evidence.md`](WBS/multi-agent-trusted-evidence.md)。

其余方向的重启条件：

- 方向 0 的设施保持可用，但不自行创建新 campaign；任何真实 API、Docker 或新预算均需针对新任务重新授权。
- 方向 1 当前正式收口，不排期观测或内核/Harness 优化；未来是否重新启动由用户另行决定。
- 方向 2 永久收口，不作为方向 1 或方向 3 的前置、旁支或待恢复项目。
- 上游 Codex 基线升级继续保留为独立、不排期任务；只有用户明确启动时才进入规划。

## 3. 方向关系

- 方向 1 的既有产品源码位于 `mydev/`，当前正式收口；方向 3 在 `multidev/` 推进多智能体与 Publication Critic。
  如果方向 1 未来重新启动，两者仍不互相夹带实现。
- 方向 0 是可复用设施，不再作为解锁其他方向的总闸门；只在具体任务需要时提供相称测评。
- 方向 2 已永久收口，不参与后续路线，也不阻塞其他方向。
- 所有方向只共享排期、API 预算、Docker、构建和本地模型等全局资源约束，重型操作保持串行。

## 4. 仓库与产品线结构

### 4.1 布局

```text
RONDO/
├── mydev/        # 方向 1 产品源码（当前收口，目录名沿用现状）
├── multidev/     # 方向 3 产品源码
├── eval/         # 两套产品可复用的通用测评设施
├── scripts/      # 共享构建锁与资源看门狗入口
├── eval-data/    # 本地重资产与私有运行数据，内部按产品分命名空间
├── test-data/    # 历史测试结果和数据
├── training/     # 轻量、受跟踪的训练合同与门限内数据集
├── doc/
└── plan/
```

### 4.2 产品与分支边界

- 两套产品地位相同，但核心源码独立；公共修复和外围设施按需复用，不追求提交级长期同步。
- 单仓库、单长期 `main`；不为方向 3 维护永久产品分支。具体开发任务仍按 `AGENTS.md` 使用短期 worktree，
  除非用户明确要求直接在主工作区工作。
- 方向 1 任务原则上修改 `mydev/` 及必要共享文件；方向 3 任务原则上修改 `multidev/` 及必要共享文件。
- `eval/`、WBS 和其他共享权威文件尽量在同一时段由一个任务负责，避免并行任务互相覆盖。

### 4.3 磁盘与重型资源

- 重型 Cargo 构建与测试必须经仓库根共享 `scripts/with-build-lock.sh` 或已接入它的 `just` 配方。受支持 Unix 入口按产品把
  主工作区和 linked worktree 路由到物理仓库根的 `.codex/cargo-target/rondo-local` 或 `rondo-multi`；两产品叶子隔离，
  `CARGO_TARGET_DIR` 必须位于项目根内并受看门狗监督。
- 两个产品叶子当前**都不存在**（已在用户逐对象授权后删除，`.codex/cargo-target/` 现为空目录）。
  两者都是可重建的构建产物且体积很大（各约 240 GiB / 96 GiB 量级），下次重型构建会重新长出；
  是否再次清理仍由用户按当时的宿主容量逐对象决定。
- 日常 Cargo 默认 `jobs=2`、GNU/Linux LLD 单线程、机器级 rustc 槽为 2；要求尽量一次跑完的完整 workspace 使用产品 Justfile 的
  `test-with-codex-v8-conservative`（`jobs=1`、`CARGO_INCREMENTAL=0`、LLD 单线程）。注意“禁用 incremental”不表示清空 target 或
  进行零缓存冷构建；`just test` 等日常窄入口按设计保留 incremental，因此全量之后若再做定向复验，incremental 缓存会再次增长。
- 两套产品的重型构建、Docker、真实本地模型加载/推理仍全局串行。除具体 ExecPlan 已获得一次性授权外，
  后续重型批次不自动排队，须由用户逐批明确批准并人工决定运行时机；历史授权不转移。
- 具体磁盘、Windows `C:`、内存、swap、Docker 增量和 fail-closed 阈值以根 `AGENTS.md` 为准，不使用 WSL
  虚拟容量代替宿主容量。删除 WSL 文件不会自动缩容 `ext4.vhdx`，宿主 `C:` 容量需另行手动 compact。

### 4.4 共享外围设施

两套产品可复用构建锁与看门狗、Docker/Terminal-Bench runner、API 预算与结算、BinaryManifest、结果归档、
本地模型外围运行设施以及 fake/loopback/replay 测试，但不因此共享核心产品语义。

### 4.5 产品身份与历史资产

- `product`（`rondo-local` / `rondo-multi`）表示既有运行产品身份，`side`（`rondo` / `codex`）表示比较侧；
  两者正交，且都不替代方向 1/2/3 的规划名称。
- 方向 3 身份必须贯通源码、构建、冻结 binary、manifest、adapter/RunSpec 与结果归档；唯一布局映射为
  `eval/rondo_eval/contracts.py` 的 `product_layout()`。
- 历史结果、receipt、trace、冻结 plan 和审计材料保持原身份，只作为历史证据，不回填新字段、不冒充新任务基线。
- crate 名与二进制名沿用上游（`codex-cli` / `codex`），便于与 `codex-source-code/` 直接比较。
- 数据资产边界见 `doc/eval-data-layout.md`。

## 5. 持续工程约束

- 测试用于正确性保障，随有效代码维护，只跑受影响模块所需门禁；较大阶段收口时再运行相称的扩大门禁。
- 测评用于量化性能与行为，默认关闭、轻量、自动记录归档；fake、离线、真实 API、真实模型与 Docker 证据严格区分。
- 冻结 Codex 与 RONDO 的公平比较只使用同口径外部指标；内部探针只用于同一产品自身诊断。
- skip、未运行、无效比较和基础设施失败不得表述为通过，也不得为凑绿弱化测试、安全或审批逻辑。

### 全量门禁与发布的通用规则

以下几条来自本轮两条产品线的收口经验，作为后续同类工作的参考约束；具体容量门、构建锁与 fail-closed 阈值
仍以根 `AGENTS.md` 为准，本节不额外加严。

- **空间门的适用时机**：做发布收口，或容量预测接近告警门限时，先执行一次独立空间门。该任务默认只允许 AI 只读盘点
  项目专用构建缓存、项目占用与宿主容量，并针对明确对象给出预计可释放空间、影响、可恢复性和建议顺序；不得自行删除、
  移动、清空、裁剪、覆盖或执行 `prune`。任何实际释放动作都必须由用户针对明确对象另行明确授权，未授权时该任务
  只交付盘点结果与建议；获得授权后也只处理获批的精确对象，并记录操作前后占用。
  **本 WBS 的任何排程都不构成删除授权。** 空间充足且不涉及发布收口时，不必为此单开任务。
- **修复后必须重跑**：若全量测试发现问题，修复并完成定向复验后必须重跑同一全量门禁，直至最终发布候选通过；
  不得以修复前的结果冻结修复后的代码。
- **不并发**：两条产品线的重型构建与全量测试不得并发（重型 Cargo 全局互斥，见 4.3）。本轮还额外利用了
  “删除前一条线的构建缓存为后一条线腾容量”这一顺序，那是当时容量紧张下的具体安排，不是永久要求。
- **发布顺序**：全量通过 → 冻结实质代码与功能 → 补对应产品 `CHANGELOG.md` → 打 `local-v*` / `multi-v*` tag 走既有流水线
  → 发布复验 → 同步 README 的固定 tag 下载链接。

## 6. 授权门

以下动作每次执行前都需要针对具体任务单独授权，历史授权不自动延续：

- Docker 拉取、构建或运行；
- 按量付费真实 API 批量测评，包括任务、轮数、模型与预算上限；
- 真实本地模型加载或推理；
- 真实数据外发，包括上传项目生成的数据；
- 云 GPU 训练、上传或下载权重及其他会产生费用或外部状态的操作；
- 冻结测试集释放（方向 3 的 `publication-critic-qualification-v1` 与 v9 test 正文）；
- 产品默认启用与任何生产动作；
- 上游基线升级。

普通依赖下载、源码查询和只读网络访问可随已授权任务执行。具体资源阈值、密钥边界和操作纪律以根
`AGENTS.md` 为准。

**历次任务的一次性授权均已随各自终态关闭**，剩余预算、provider 请求配额与数据权限一律不转移；
逐任务的授权范围、实际消费与关闭记录见 `doc/WBS-COMPLETED.md`。

## 7. 子 WBS 索引

- `doc/WBS/eval-benchmark.md` —— 方向 0：现行测评设施与新任务授权边界
- `doc/WBS/teacher-harness-study.md` —— 方向 1：正式收口状态与历史归档入口
- `doc/WBS/local-approval-model.md` —— 方向 2：已永久收口
- `doc/WBS/multi-agent-trusted-evidence.md` —— 方向 3：现行产品语义、有效结论与唯一未解锁工作包
- `doc/WBS/durable-team-runtime.md` —— 方向 3 四期：正式收口状态与历史归档入口
