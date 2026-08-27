# Plan 093：RONDO Multi 干净全 Workspace 基准与共享构建现场收口 ExecPlan

> 本计划是 Plan 093 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改；完成标准只更新勾选状态，不改写口径。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；范围内普通实现、编译、测试、fixture、环境适配和审查问题允许自主修复与重跑。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

为当前 `main@93685f576779b21e0c021a09d990c49d4a84fa2d` 上的 RONDO Multi 建立新的正式 Linux 本地全 workspace
测试基准，同时完成旧重型构建现场释放、跨 linked worktree 的产品级共享 Cargo target、永久存储门限更新和全量暴露问题的有界修复。

长期共享 target 根为主物理仓库
`/home/sjc/desktop/RONDO/.codex/cargo-target/`，产品叶子固定为 `rondo-multi` 与 `rondo-local`；本任务只创建、使用并保留
`rondo-multi`，不创建或加热 `rondo-local`。共享内容仅是可再生构建缓存，不改变调用 checkout 的源码、cwd、Git identity、writer
binding，也不替代既有 binary freeze/manifest 身份。

任务的技术实现与正式测试完成后，执行者只提交 093 分支并交由计划制定者独立验收。只有用户另行批准且实际完成主线集成、推送、093
分支归档和 worktree 释放后，才记录终态：

`COMPLETED / ACCEPTED / INTEGRATED / PUSHED / MULTIDEV_FULL_WORKSPACE_BASELINE_PASS`

### 完成/验收标准

- [ ] **旧现场安全释放**：069/087/089/091/092 worktree 在释放前均为 clean，任务提交与应有 tracked plan/log/完成记录均可从
      当前 `main` 定位；069、091 分支按惯例归档为 `zz-done/*`，既有归档分支保持，所有历史分支和提交均保留。
- [ ] **旧 target 精确删除**：
      `/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target`
      已在确认非符号链接、069 clean、无使用者后，持续持有 canonical 构建锁完成删除与紧邻复核；没有用重命名或搬运冒充冷基准。
- [ ] **并行现场保持隔离**：Plan 090 的路径、分支、tracked/untracked/ignored 资产未被本任务读取内容、改写、整理或删除；状态级快照允许其
      自身执行者继续推进，不要求它在任务期间静止。
- [ ] **共享 target 合同成立**：主工作区和任意 RONDO Multi linked worktree 的受支持 Unix 正式重型 Cargo 入口默认解析到同一个物理
      `rondo-multi` target；RONDO Local 的默认映射是独立 `rondo-local` 叶子但本任务不创建它。产品叶子不混用，worktree 内不再生成大型
      `codex-rs/target`；显式专用 target 仍须由未来具体任务单独授权。
- [ ] **永久资源门准确**：watchdog 默认项目线为十进制
      `270000000000 / 285000000000 / 290000000000` bytes，永久 Windows `C:` 停止线仍为 `50000000000` bytes；脚本说明、
      `AGENTS.md`、`CLAUDE.md`、`doc/development-environment.md` 和相称轻量回归一致。每轮 summary 能明确记录实际 warn/stop/max 与
      Windows `C:` 停止线。
- [ ] **路由与门限回归通过**：纯测试/fake 验证主工作区与 linked worktree 的同产品 target 一致、两产品叶子隔离、错误门限顺序拒绝、
      项目根外 target 拒绝、必要资源计数器不可读继续 fail-closed；测试不创建或加热 `rondo-local`。
- [ ] **冷全量完整结束**：新 `rondo-multi` target 从空目录开始，候选实现绑定 clean exact commit，以 checksum-verified V8 入口在
      `multidev/codex-rs` 完成 Linux、default features、standard local Nextest 的完整 workspace 枚举与执行；不使用
      `--all-features`，不全跑 `#[ignore]`。
- [ ] **最终 HEAD 全量通过**：若冷全量后发生修复，最终实现与配置冻结后在 clean exact HEAD 上再次完成同口径全 workspace；最终正式轮
      为零 terminal failure、零 error、零 timeout。若冷轮已经对应最终代码且全绿，可由同一轮同时满足冷轮与最终轮。
- [ ] **失败、retry、skip 诚实闭合**：范围内稳定复现问题已修复；每项 retry 记录测试名、首次现象与最终状态，并按性质完成定点复核或
      finding 处理；skip 按类别和数量记录且不计 passed，新增 skip 有解释。Plan 091 prompt-edit 与 Plan 092 Durable Session TUI 保护项
      在最终全量中通过。
- [ ] **正式证据稳定保留**：Plan 093 自身各次完整 workspace 原始 run 直接保存在主物理仓库
      `test-data/_retained-test-evidence/plan093-clean-full-workspace-baseline/runs/`，至少保留 JUnit、`summary.env`、`metrics.csv`、实际
      Nextest 配置和足以还原 V8/命令结果的运行输出或简明记录；另以一个轻量 manifest/摘要记录 exact commit、Cargo.lock SHA-256、
      工具链、V8 identity、命令、测试计数、耗时、retry/skip、资源峰值及 JUnit SHA-256。无需建设新的审计或可信体系。
- [ ] **仓库收口干净**：无 `.snap.new`、锁文件漂移或未解释生成物；tracked 文档职责正确，独立审查无未关闭高、中等级 correctness
      finding；新共享 target 与 Plan 093 正式证据均保留，不做成功后清理。
- [ ] **Git 停止点正确**：执行者完成实现、验证、动态 Plan 和精炼 `agent_log` 后只提交 093 分支并保持 worktree clean，交由计划制定者
      独立验收，不自行合并或推送；验收通过后再在同一 093 分支补充 `doc/WBS-COMPLETED.md` 与验收收口提交。未获后续集成授权时只记录
      `COMPLETED / ACCEPTED / MAIN_INTEGRATION_PENDING / NOT_PUSHED`；集成授权完成后才归档并释放 093，使 `git worktree list` 只剩
      主工作区与仍在开发的 090。

## 2. 范围

### 允许修改

- `scripts/with-build-lock.sh`、职责相关的既有 helper、根/`mydev`/`multidev` 正式重型 Cargo 入口及其轻量测试，用于共享 target 默认解析、
  永久门限和运行证据完善。若强行复用会造成耦合或语义扭曲，可新增一个职责清楚的窄 helper，但不得重复建设第二套构建监督体系。
- `multidev/` 中由本任务全量稳定暴露、且符合第 3 节边界的产品代码、fixture、snapshot、生成物、测试辅助设施及直接回归测试。
- `AGENTS.md`、`CLAUDE.md`、`doc/development-environment.md`；本 Plan 的动态状态和关键决策；一份精炼实施日志；验收通过后向
  `doc/WBS-COMPLETED.md` 添加准确完成记录。不修改顶层或子 WBS。
- 创建、使用、归档和释放 093 worktree；归档并释放已完成的 069/087/089/091/092 worktree；保留其历史分支与提交。
- 普通依赖下载、checksum-verified V8 工件读取、task-owned `/tmp`、测试 `TempDir` 及 093 worktree 内普通 ignored 调试输出。

### 不允许修改

- Plan 090 的任何 tracked/untracked/ignored 资产，或其它来源不明的修改、缓存、worktree、分支与提交。
- `mydev/` 产品语义、冻结 Codex CLI `v0.147.0` 基线、`codex-source-code/`、对外协议、已完成多智能体第四期合同，或正在推进的
  Publication Critic 三期路线和状态。
- 为凑绿而删除测试、弱化断言、全局扩大 timeout、增加宽泛 skip/ignore，或把当前 Linux 应执行测试改成依赖缺失型跳过。
- Bazel、Docker、eval、训练、真实 API/模型、云端任务、原生 Windows/macOS 测试、CI/PR、发布、上传、付费和其它外部状态变更。
- Cargo registry、V8 工件、`deps`、release 工件、模型、Docker 数据、来源不明资产，或本任务未精确授权的 target/worktree 删除。
- 顶层/子 WBS、README、历史 plan/log/audit/research 内容；历史记录只读，不为当前结论改写。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/凭据、项目外个人文件或私有数据。
- Plan 090 的未提交内容、diff 或 ignored 资产正文；只允许 status/HEAD/worktree path 等保护性元数据检查。
- 091/092 worktree 中已决定不迁移的 ignored watchdog/JUnit 内容；释放前只核对 clean、tracked 成果与 main 包含关系。

### Git-ignored 与主物理工作区边界

所有 tracked 编辑只在
`/home/sjc/desktop/RONDO/.claude/worktrees/093-clean-full-workspace-baseline/` 完成并提交。以下资产被根 `.gitignore`
覆盖，又必须跨 093 worktree 生命周期保留，因此需要按本计划授权直接写主物理工作区，并在交付时单独汇报；它们不会出现在 093 的
tracked diff 中：

- `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi/`：本任务唯一创建和加热的共享 Cargo target。
- `/home/sjc/desktop/RONDO/test-data/_retained-test-evidence/plan093-clean-full-workspace-baseline/runs/`：仅保存 Plan 093 自身完整 workspace
  原始 run 与轻量结果记录。

此外，精确删除旧 069 ignored target、归档/释放已完成 worktree 属 common Git/跨 worktree 操作，也应从主物理工作区或等价受控上下文
执行并单独记录。Plan 091/092 ignored 原始测试文件不迁移、不复制；其 tracked 代码、测试、Plan 和日志已进入 main 后，ignored 文件可随
旧 worktree 一并释放。

若实现意外要求写入其它主工作区 ignored 路径，必须先报告准确路径、用途、预计体积和保留/清理责任并取得授权；普通 task-owned
`/tmp`/`TempDir` 不属于该扩围。

## 3. 硬约束

以下约束只冻结必要的产品、资源、安全、正式结果和 Git 停止点，不固定 resolver/helper 布局、具体代码结构、逐测试矩阵或调试轮数。

1. **工作树与并行隔离**：tracked 实现只在 093 worktree 开展；未知修改全部保留。Plan 090 只做状态级保护检查，允许其 owner 并行推进，
   本任务不得读取内容或假设其 HEAD/状态静止。执行者结束时只提交 093 分支；merge/push/归档并释放 093 等待用户另行批准。
2. **完成现场释放**：只释放已 clean、且 tracked 任务成果已进入 main 的 069/087/089/091/092。归档动作只重命名尚未归档的本地任务
   分支，不删除分支、提交或历史；不得使用 force 掩盖不确定状态。091/092 ignored 原始 run 无需迁移。
3. **删除先于新重型构建**：在删除 069 target 前不得启动新的普通重型 Cargo 构建/测试。删除仅针对第 1 节 exact directory，并且必须
   同时满足：路径存在且不是 symlink、069 clean、090 未使用该 target、无 Cargo/rustc/nextest 或 active RONDO heavy scope。删除者必须
   取得并持续持有 canonical lock，直至精确删除和紧邻占用复核完成；无法证明任一条件时停止删除，不触碰现场。
4. **产品级共享 target**：受支持 Unix 重型入口的默认 target 由物理 Git common root 与产品 identity 稳定解析，不能依赖调用 worktree
   的绝对路径或 cwd 偶然性；Multi 与 Local 分别映射 `rondo-multi` / `rondo-local`，当前只允许创建 Multi。项目根外 target 和无法解析
   common root 的情况继续 fail-closed；共享 cache 不改变源码、运行 identity 或 freeze/manifest 合同。
5. **永久门与临时例外分离**：仓库永久默认只能是项目 `270000000000 < 285000000000 < 290000000000` bytes 与 Windows `C:`
   `50000000000` bytes。本任务重型命令可且只可以进程级覆盖 `RONDO_BUILD_WINDOWS_C_FREE_STOP_BYTES=30000000000`；30GB 不得写入
   脚本、Justfile、文档默认或长期配置，达到该线立即停止且不得再次降低。实际生效四线必须进入每轮 summary。
6. **正式全量口径**：完整 workspace 只在 `multidev/codex-rs`、Linux、default features、standard local profile 下，经仓库
   checksum-verified V8 入口执行 `just test-with-codex-v8 --locked`；保持既有 `--no-fail-fast` 和资源并发上限。loopback fake 服务与 browser
   opener 隔离只用任务命令/进程级 `NO_PROXY` 和 stub，不修改系统默认浏览器、全局代理或产品行为。
7. **先调通再冻结正式轮**：共享路由、永久门和轻量回归先稳定并形成候选提交，再从空 `rondo-multi` target 开始冷全量。遇到范围内问题
   保留已验证构建进度，从首个未通处修复并做聚焦复核；最终代码和配置冻结后，从 clean exact HEAD 完整运行一轮作为正式结果。
8. **冷重建判据**：冷轮后普通源码、fixture 或 snapshot 修复不要求浪费性清空 target，最终增量全量即可；若修改 `Cargo.lock`、features、
   build script、依赖图、构建拓扑、canonical target 路由，冷编译没有完整结束，或有证据怀疑缓存影响结果，则最终轮前重新建立空 target。
9. **允许修复与重跑但不凑绿**：当前 main 稳定复现的产品 bug、陈旧 fixture/snapshot/生成物、窄非 hermetic 测试问题、共享 target/看门狗
   引入问题，以及不改变既有合同的小中型跨 crate 兼容问题可自主修复、定点验证和继续全量，不设机械失败次数上限。需要改变对外协议、
   四期权限/生命周期合同、上游基线、V8 ABI 或大规模依赖迁移时停止扩围并报告。
10. **结果判定诚实**：最终正式全量必须零 failure/error/timeout。确定性产品 retry 即使最终通过也作为 finding 处理；明确 teardown、端口、
    调度波动可在新进程定点稳定复核后接受。skip/未运行/基础设施阻断不计 passed；V8、资源门或宿主设施阻断只能记 blocked/未运行。
11. **资源与清理边界**：所有重型 Cargo 批次经 canonical lock/watchdog 全局串行，不与 Docker、真实模型或其它重型任务并发；必要资源事实
    不可读即 fail-closed。调试期资源不足时，仅在证明无人使用后最小清理新 `rondo-multi` target 中可再生的 `debug/incremental`；不得清理
    `deps`、release、registry、V8 或其它资产。达到 285GB/290GB 或本任务 `C:` 30GB 线立即停止；正式成功后不清理新 target 或证据。
12. **外部、文档与验收边界**：只允许 deterministic/fake/offline 测试、普通依赖下载和只读 V8/源码查询；不接触秘密或未授权外部状态。
    只更新职责内 tracked 文档，不改 WBS 路线。最终由计划制定者独立审查 correctness、范围、原始 JUnit/summary、资源、生成物和 Git
    停止点；未实际集成/推送时不得记录 `INTEGRATED`、`PUSHED` 或最终 PASS 标识。

### 审查者跨会话队列（以下内容逐字照录用户要求，执行者必须原样遵循）

联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a04122-ac9d-7973-a4a7-37a504e45b69 替换。
XXX用你需要发送/询问的消息内容嵌入代替，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）你发送完队列消息之后，停止会话，不用维持等待或者轮询！审查者的消息会自动唤醒你的。审查者会以相同方式通知你，你后续如果仍然需要沟通，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。注意不要重复提交相同的消息给审查者，另外这个消息队列本身是queue的形式，因此会在接收者空闲时才会接收到，所以不要重复发送。有问题时可以使用 codex queue --help。而且你问完问题建议主动停止会话，不然你收不到审查者的消息。

需要申请额外授权/计划外的变数/不确定的东西需要请示的时候，使用codex queue联系审查者，以此作为批示。

执行者完成最终任务之后，应该使用 Codex 的跨会话队列通知审查者，告诉他如下内容：执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID替换。
XXX用以下内容代替：
“执行者完成了，请你验收审查。不过不要无限扩大不必要的设施与审计校验等，不重跑太重的测试，主要关注正确性和功能性，以及之前遗漏未发现的东西或者局部修复导致的全局回归。如果他还提到需要我确认/决策的东西，请你也直接帮我做出你认为最合理的决策，都写在agent_log的审查报告里面。最后在输出的时候输出精炼的验收摘要，报告路径，替我做出的决策（如有），以及目前项目的状态：验收通过/不通过（关注做的对不对）+任务目标完成/失败（关注是否实现预期）
+<执行者的完成汇报>”
其中
<执行者的完成汇报>就是执行者本来TUI汇报输出给用户看的内容，直接一模一样复制替换进去即可。注意使用单引号包裹完整消息，并确保内容中的单引号安全处理，避免 shell 解析异常。
（重要）执行者你发送完队列消息之后，停止会话即可，不用维持等待或者轮询！审查者的消息会自动唤醒你的。后续审查者会以相同方式通知你，可能让你修复问题，你执行完之后，再次使用：
 codex queue --thread UUID --message 'XXX'
的方式，反馈给审查者即可，内容和填充规则和之前一致。如果验收通过，他不会再通知你。注意严格遵循完成所有变动之后再提交，不要重复提交相同的实现给审查者。

执行者给审查者发送消息的时候，必须主动表明身份。

## 4. 软性建议

以下建议用于帮助执行者收敛，不是固定路线。执行者可依据 live code、实际资源和更干净的设计选择等强或更优方案，并把重要偏离记入关键
决策记录。

- 先对现有 root/product Justfile、watchdog 和测试做窄 census，再决定在既有入口设置 canonical target，还是提取一个很小的产品 target
  resolver。职责契合时复用现有 common-root 解析；若散落拼接会持续漂移，可新建一个单一窄 helper，不必预建通用构建平台。
- 共享 target 的轻量回归优先验证行为而非实现细节：同一 Multi 主/linked checkout 解析相等，Local 解析到不同但不创建的叶子，外部路径
  和错误门限被拒绝。无需为每个 Just recipe 复制一套同构测试。
- 旧 worktree 释放可按“状态/main 包含关系确认 → 取得锁并精确删除 069 target → 归档/移除已完成 worktree → 复核 main/090/093”编排；
  具体安全删除方法由执行者选择，但目标必须精确且不可用 force 掩盖异常。
- 调试期只跑受影响 helper/入口/fixture 的必要门禁。候选提交 clean 后再启动冷 workspace；冷轮暴露问题时，保存已生成 target 与完整 run
  证据，聚焦修复后继续，不因一个可窄修问题报废整个构建进度。
- Plan 093 的每次完整 workspace 可使用 `cold-*`、`final-*` 等清楚的 runs 子目录，并用简单文本/env manifest 加现有 JUnit/watchdog 文件
  完成记录；不需要数据库、签名、证据图或新的 schema。命令输出的保留方式可由执行者选择，但必须保留真实退出码和 V8 identity。
- 文档只更新当前默认与共享 target 事实；历史实测数字继续作为历史，不机械改写。`doc/WBS-COMPLETED.md` 和日志保持精炼，不复制本计划。
- 可使用少量子智能体做入口 census、失败分类或最终只读审查；共享实现、破坏性现场操作和提交由单一执行者负责，避免并行编辑冲突。

### 建议阶段与退出条件

**A. 旧现场释放**

- 保护性复核 main/090/093，确认五个已完成 worktree clean 且提交在 main；在 canonical lock 下精确删除 069 target，再归档并释放完成现场。
- 退出条件：项目占用已明显下降，旧 target 和完成 worktree 不再存在，main/090/093 无本任务造成的异常变化。

**B. 共享 target 与永久门**

- 完成默认路由、270/285/290GB + C50、summary 观测字段和轻量回归，更新当前维护文档。
- 退出条件：主/linked Multi 一致、Local 隔离、fail-closed 回归通过；主物理 `rondo-multi` 仍为空，未创建 `rondo-local`。

**C. 冷 workspace 调通**

- 提交 clean 候选，冻结 exact identity；使用临时 C30 命令授权、loopback 代理隔离和 browser stub 启动第一次完整 workspace，证据直接落主物理
  retained runs。
- 退出条件：完整枚举和执行结束，或保留足以继续诊断的真实 failure/blocked 证据；不得把中断或基础设施失败记为通过。

**D. 有界修复与最终正式轮**

- 对有效失败做聚焦复现和相称修复；打通后冻结最终 HEAD，按冷重建判据决定 warm 或重新空 target，再运行完整 workspace。
- 退出条件：最终零 failure/error/timeout，retry/skip、两项历史保护、资源和 JUnit 均闭合。

**E. 收口、交审与验收记录**

- 检查 diff、锁文件、snapshot、主物理 ignored 资产、worktree/branch 和 Plan 090 隔离；更新动态 Plan 与精炼实施日志，提交 093 分支并
  交由计划制定者验收。验收 finding 在同一分支修复、复验并提交；验收通过后再补完成记录与验收收口提交。
- 退出条件：093 clean，主物理共享 target/正式证据保留，独立验收与完成记录闭合；全程不合并、不推送。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-26：确认主工作区 clean，`main` 与 `origin/main` 一致指向
  `93685f576779b21e0c021a09d990c49d4a84fa2d`；从该提交创建
  `.claude/worktrees/093-clean-full-workspace-baseline` / `worktree-093-clean-full-workspace-baseline`。
- 2026-08-26：完整读取根与 `multidev` 规则、README、当前 WBS、计划模板、Plan 061/072/091/092、相关实施/验收日志、
  `doc/development-environment.md` 及当前 watchdog/Just/V8/测试入口。
- 2026-08-26：069/087/089/091/092 worktree 均为 tracked/untracked clean，其分支 HEAD 均已进入 main；087/089/092 已归档，069/091
  尚未归档。091/092 ignored 原始 run 按用户最新决定不迁移，后续可随 clean worktree 释放。
- 2026-08-26：Plan 090 保护性快照为 `HEAD@87d3fe3127c736a25ab13489f6f0c7cf1a7bd140`、tracked/untracked clean；其 ignored
  资产只确认存在于保护范围，未读取或枚举内容。
- 2026-08-26：只读资源复核为项目根 `272558829568` bytes、069 target `212729303040` bytes、Windows `C:` 可用
  `42409586688` bytes。当前永久脚本仍是 240/255/260GB + C50，故删除 069 target 前不得启动普通重型构建。
- 2026-08-26：确认两个长期保留位置均受根 `.gitignore` 覆盖，必须直接写主物理工作区；本规划没有创建共享 target、写 retained runs、
  删除任何旧 target/worktree，或运行任何 Cargo/Docker/模型/API 任务。
- 2026-08-26：用户指定 Plan 093 执行者与审查者的跨会话队列合同；额外授权请示、完成交审和整改反馈统一发送到审查会话
  `01a04122-ac9d-7973-a4a7-37a504e45b69`，发送后停止且不轮询。
- 2026-08-26：在宿主上下文持续持有 canonical 构建锁，复核 069 clean、HEAD 已进入 main、exact target 为非 symlink、
  无 Cargo/Nextest/active heavy scope 或路径使用者后，精确删除 069 target `212729303040` bytes；项目占用从
  `272558923776` 降至 `59829633024` bytes，删除后紧邻复核无 active scope。
- 2026-08-26：069/091 分支已无 force 地归档为 `zz-done/*`；069/087/089/091/092 均在逐个 clean 与 main 包含复核后
  释放，历史分支与提交保留。当前 `git worktree list` 只剩 main、并行 090 与本任务 093。
- 2026-08-26：共享 watchdog 已用显式产品 identity 把受支持 Unix 正式重型入口默认路由到物理 common root 下的产品叶子，
  永久默认更新为 270/285/290GB + C50，并在全部已创建 summary 形态统一记录产品、target 与四条实际资源线。两产品
  helper/Just/V8 轻量回归、门限顺序与根外 target 拒绝均通过，且未创建 `rondo-local` 或 `rondo-multi`。

### 当前工作

- 冻结并提交共享 target/永久门候选；随后从空 `rondo-multi` 启动 checksum-verified V8 冷全 workspace。

### 本任务剩余步骤

- 提交共享 target/永久门候选，按第 4 节 C–D 完成冷全量、有界修复与最终正式轮。
- 按第 4 节 E 整理证据、动态 Plan 与实施日志并提交 093；随后由计划制定者独立验收。合并、推送、093 归档和
  worktree 释放等待用户另行批准。

### 阻塞项

- 当前无执行阻塞；069 target 与旧 worktree 释放前置已闭合。

### 当前验收状态

- `IN_PROGRESS / LIGHTWEIGHT_GATES_PASS / FULL_WORKSPACE_PENDING / MAIN_INTEGRATION_PENDING / NOT_PUSHED`。

### 交接边界

- 本任务完成后冻结此计划；它不重新打开多智能体第四期，也不改变 Publication Critic 三期路线。任何下游工作只见 WBS，不在本计划追加。
- 执行者技术完成后的固定停止点是 093 分支本地提交与 clean worktree；最终主线集成和清理由用户后续授权。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Cargo target 从 worktree 级改为物理 Git common root 下的产品级叶子；本任务只创建 `rondo-multi` | linked worktree 共享构建缓存，同时保持两产品和源码 identity 隔离 | 构建入口、磁盘 | 已采纳 |
| 002 | 永久项目线更新为 270/285/290GB，永久 C 盘线保持 50GB；本任务 C30 仅为命令级例外 | 适配当前冷全量容量，同时保留宿主长期安全底线 | watchdog、文档、正式运行 | 已采纳 |
| 003 | 091/092 ignored 原始测试 run 不迁移，释放前只核对 tracked 成果已进入 main | 用户决定不把旧局部原始 run 纳入本任务保留范围；tracked 日志、代码和测试足以支持现场释放判断 | 旧现场、证据范围 | 已采纳 |
| 004 | 调试期保留构建进度并自主窄修，最终冻结 clean HEAD 后完成完整正式轮 | 避免因可修小问题反复报废重型构建，同时保证正式基准对应最终代码 | 测试策略、证据 | 已采纳 |
| 005 | Plan 093 自身完整 workspace 证据与共享 target 直接保存在主物理 ignored 路径，成功后不清理 | 093 worktree 最终会释放，这两类资产需要供后续任务复用 | ignored 写入、交付 | 已采纳 |
| 006 | 执行者本轮只提交 093 分支；最终 PASS 必须等待独立验收和用户另行批准的集成/推送/清理 | 服从用户最新 Git 停止点，不提前冒充主线状态 | Git、终态标识 | 已采纳 |
| 007 | 执行者的额外授权请示、完成交审和整改反馈只通过用户指定的 Codex 跨会话队列传递，发送后停止且不轮询 | 让计划制定者在独立会话中统一批示和验收，避免重复或旁路消息 | 沟通、验收 | 已采纳 |
| 008 | 正式入口只传内部 `RONDO_BUILD_CARGO_PRODUCT` 身份；watchdog 统一解析、导出默认 target，并在启动 payload 前移除该内部变量；显式 `CARGO_TARGET_DIR` 保持优先 | 避免按 cwd 猜产品，修复 linked/no-cd/manifest 入口偏差，同时保留未来单任务专用 target 能力且不影响生产 watchdog lease 环境 | watchdog、Just 入口、测试 | 已采纳 |
