# Plan 078：M4-S2 恢复与生命周期收口 ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 普通实现、fixture、轻量检查或审查问题应由执行者自主窄修并重跑，不属于改变任务合同；重型命令仍须按第 3 节逐批取得用户批准。
> 本计划只描述 Plan 078；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

在 clean `main@dfc4278233cf6c361fd6bbef7b3fb6107906f22d` 已取得的 `M4_S1_PASS` 持久接缝上，完整闭合 Durable Team
Session 的恢复、分叉、detach、关闭、异常退出与原生冷态生命周期，使 Session、canonical Root、child Thread 与 TeamInstance 在
resume/reload、顶层 fork、child spawn、new/clear、idle unload、archive/unarchive/delete 和异常状态中保持既定身份与单一 Root
authority 语义。

本任务先把上游 `#37847` 作为 Plan 078 内的独立前置阶段窄回移：只保留 V2 member residency reload 的 inherited environment，
保持已有显式 override 优先。该阶段单独提交、聚焦验收，经用户批准进入本地 `main` 后，Plan 078 才消费该精确主线并开始 S2 正式轮。
它不另建第三份计划/worktree，不承担 Team durability、Workspace Binding 或新的环境管理体系。

职责契合时复用现有 Session/thread lineage、Agent graph/residency、Team durability/read、Root writer、close barrier 与 ThreadStore 冷态
生命周期；强行复用会扭曲产品语义时，允许新建与现有配置、生命周期、错误、测试和观测方式契合的专用能力，但不得形成第二套
Session/Team 状态源、writer authority、registry 或控制平台。

### 完成/验收标准

- [x] **`#37847` 独立前置**：V2 member 在 residency eviction 后按需 reload 时保留继承的 environment selections，已有显式 override
      仍优先，且不会因默认 config/fallback 覆盖正确选择；reload 本身不自动发起 model turn 或真实 API。实现采用上游
      `4996cf05...` 的产品结果或当前架构下的等强窄适配，不机械升级基线。前置形成独立提交、聚焦测试和独立审查结论。
- [ ] **恢复身份**：Root cold resume 与 member reload 恢复原 `SessionId`、canonical Root `ThreadId`、`TeamInstanceId`、child identity/
      metadata 和自洽 committed Team State；V2 Root resume 不自动打开 child runtime，member 只在真实消费入口按需 reload，不自动启动
      模型/API。旧 V1/legacy 的既有恢复行为保持原合同。
- [ ] **fork/spawn/new/clear 边界**：顶层 `thread/fork` 按原生 history 规则创建新 Session、Root 与新空 TeamInstance，来源 Team 不变，
      跨实例旧 Team 引用 fail-closed；`spawn_agent fork_turns=none/all/N` 创建新 child Thread 但仍属于原 Session/root/Team，参数只决定
      conversation context；`/new` 与 slash `/clear` 创建新 Session/Root/空 Team，纯终端/UI 清屏不改变任何身份、Team State 或 authority。
- [ ] **detach 与 unload 分离**：TUI switch/unsubscribe、客户端断连和即时 detach 只解除附着，不 close/unload Team、不释放 Root authority；
      零订阅后的 deferred idle unload 是独立生命周期动作，必须复用同一 member unload 或 Root/Team close barrier。submit failure、timeout
      或 live descendant 阻断时保持 loaded/closing/failed 且可重试，不伪报完成或移除唯一 owner。
- [ ] **关闭与异常退出**：正常 Root/Team close 只有在应持久状态达到承诺边界、所有 mutation-capable descendants 已失能且 Root authority
      已释放后才完成；存活进程内 session task/shutdown/persistence 失败不等同进程退出，保留可定位、可重试 owner 并拒绝第二 writer。
      完整进程终止后 OS 才释放旧 writer，新进程验证 durable 状态后可恢复同一身份并继续 mutation。
- [ ] **原生冷态生命周期**：archive/unarchive/delete 继续通过 Codex 原生 Root/subtree 与 ThreadStore 领域能力，不为操作加载 Root、不强制
      takeover 活跃 writer。archive 保留同一 Team identity 并提供诚实 archived read；unarchive 恢复原 Root/Team 而不批量复活 descendants；
      delete 只有在线程 subtree 与对应 Team durable 结果均确认后才 terminal。active writer、descendant、部分失败或结果未知均明确暴露，
      不得先丢 owner、伪报完成、re-ID 或留下可被正常恢复误认的半删除状态。
- [ ] **异常与兼容**：旧版本、legacy/non-durable、缺失、损坏、版本不兼容及 Session/Root/Team identity mismatch 返回与现行合同相符的
      unavailable/unsupported/failure 或可验证只读降级；不创建空 Team、不静默升级、不换 ID、不切换状态源。功能关闭态、单 Agent、
      普通 V1/V2、non-durable Team 与 shared workspace 无回归。
- [ ] **测试与正式轮**：用相称的领域、deterministic/fake、故障注入、公共入口和真实子进程回归覆盖上述结果，不建设全笛卡尔积或新测试
      平台。调试全链打通且代码/配置稳定后，从全新的任务专用 Session/store namespace 完整运行一次正式生命周期场景组；互斥终态可使用
      同一 fresh namespace 内的多个 fresh Session，不用 `cargo clean` 冒充干净状态。
- [ ] **并行兼容与独立终审**：若 Plan 077 已先进入 `main`，078 作为后进入者须在最新主线上完成一轮只读 Session Query 与最新 lifecycle
      的聚焦兼容验收；若 078 先进入主线，该责任由后续 077 整合者承担。最终独立审查无未关闭的高/中等级 correctness finding；普通
      finding 允许自主修复、重跑和复验，不因首次可修复失败整组作废。
- [ ] **本地交付**：按有意义阶段提交 078 分支，精炼记录实现、门禁、正式轮、审查与未运行项；最终 worktree clean。未经用户批准不把
      前置或最终 078 合入 `main`，不推送、不关闭 worktree、不重命名/归档分支。

## 2. 范围

### 允许修改

- `multidev/codex-rs/core/` 内与 Session/thread、AgentControl、V2 residency、resume/reload、fork/spawn、new/clear、Root/Team close barrier、
  异常退出恢复和必要 lifecycle result 直接相关的实现与测试。
- `multidev/codex-rs/thread-store/`、必要的 `team-state/`、Agent graph/state/rollout 接缝，以及 archive/unarchive/delete、active writer、
  durable artifact 生命周期和异常兼容直接相关的实现与聚焦测试。
- `multidev/codex-rs/app-server/` 中 detach/deferred idle unload、既有 thread lifecycle consumer 和冷态操作的窄适配/测试；只在真实
  产品入口需要时修改，不借此建设正式 Session Query 或新控制面。
- 为闭合上述行为所必需的少量相邻 `protocol`、feature/config、test support、fixture、schema/snapshot、Cargo/Bazel manifest/lock；只有
  live 编译/生成接缝证明必要时才进入这些共享路径，并使用仓库既有生成工具。
- 本计划的“当前状态”和“关键决策记录”、一份或少量有实质内容的 Plan 078 `agent_log/`，以及任务 worktree 内由既有命令产生的 ignored
  watchdog、fresh Session/store 和测试临时资产。
- 只读核对冻结 `codex-source-code/`、Codex 文档快照、Git 历史与上游 `#37847` primary source；普通依赖下载和只读源码查询在本任务
  授权内。

### 不允许修改

- Plan 077 所拥有的正式 app-server v2 Session Query API、projection、client、TUI 查询展示、公开文档与其 schema/test 资产。若 S2 的
  真实 app-server lifecycle consumer 与 077 写集重叠，延后该共享文件、等待一方进入 `main` 后由后整合者窄收敛；不得读取或吸收
  077 未提交内容。
- Plan 076、Publication Critic、`eval/`、训练、模型/权重、M4-W0/W1、Workspace Binding/handoff、后续正式 Session Control/TUI 或
  M4-Z(core) 的实现与测评。
- 完整上游 Codex 基线升级、`#39616`、`#39153` 或其它上游增量；`#37847` 也不得扩张为环境持久化 schema、环境 registry、权限恢复或
  通用环境管理能力。
- takeover/抢锁、跨进程 mutation relay/queue/IPC router、第二套 writer lease/registry、第二套 Session/Team State/read source、
  补偿事务平台、daemon/dashboard、通用审计/可信/机器验收体系或严格全局因果设施。
- README、历史 plan/log/audit snapshot、`doc/WBS-COMPLETED.md` 的提前完成结论。立项所需的 WBS 并行关系与 `#37847` 例外已随本计划
  窄同步；执行期共享 WBS 的完成状态由获批的后整合者基于最新 `main` 统一更新，不在并行 worktree 争写。
- Docker、真实 API/模型、训练、性能测评、CI/PR、发布、上传、付费或其它远端状态变更。
- 未经批准的 merge/rebase/cherry-pick/push、worktree 删除、分支重命名/归档、069 target 清理，或对其它任务 worktree 的 tracked/ignored
  内容进行编辑、复制和清理。

### 不允许读取/查看

- `.env.local` 内容、密钥/凭据、私有模型/测评正文、训练输出/权重、项目外个人文件和其它 worktree 的未提交文件、diff 或设计。
- 其它 Agent 的未提交实现；并行核对只使用 branch/HEAD/status 路径、锁/进程/资源元数据及已经进入 `main` 的事实。

### Git-ignored 与主工作区边界

全部 tracked 编辑在 `.claude/worktrees/078-m4-s2-recovery-lifecycle` 完成。预计不需要直接写主工作区 ignored 文件；主物理仓库的
`codex-source-code/` 仅作只读上游对照。只有用户针对具体重型批次明确批准并安排运行时，Plan 078 才可通过 canonical
`multidev/justfile`/shared wrapper 显式复用并写入
`/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target`，这是唯一预期的跨 worktree
ignored 写入例外；不得手工修改、clean 或删除该缓存。078 自有 `.codex/build-watchdog/` 与 `/tmp` 下的任务专属 fixture 可由既有命令
创建。若实现意外要求直接写主工作区、其它 ignored 资产或项目外路径，先停止该动作并报告准确路径、原因、影响与清理责任。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部进度而违反。

1. **精确基线与两阶段 Git 门**：078 从 clean `main@dfc4278...` 开始，只消费已进入该基线/后续本地 `main` 的事实。`#37847` 前置必须
   是独立、可审查提交，不夹带 S2 正式实现；完成后停在 078 分支并请求用户批准。只有它获批进入本地 `main`，且用户批准 078 消费包含
   该提交的精确最新主线后，才开始 S2 正式轮。普通可修失败不能越过这一原则性主线门。
2. **三类身份与原生分叉语义不变**：resume/reload 保留同一 Session/Root/Team；顶层 fork/new/slash clear 创建新 Session/Root/空 Team；
   child spawn 只新建 child Thread 并留在原 Session/root/Team。不得 remint/rewrite/map/clone Team，不得让 old Team reference 跨实例成功。
3. **单一 Root authority 与完整 close barrier**：所有 Root/child Team mutation 继续使用 S1 的 canonical Root authority；close、idle unload、
   archive/delete 准备或失败路径不得绕过它。任一 mutation-capable descendant 存活、提交未决或 teardown 失败时不得释放 authority、移除
   唯一可重试 owner或报告完成。实现可阻止 close，也可在同一 barrier 内安全 quiesce/close descendants，由执行者按 live 架构选择。
4. **恢复和冷态结果诚实**：恢复只有在 lineage/instance/durable state 可证明时才可写；冷态操作继续走原生 Root/subtree/ThreadStore
   能力。partial/unknown/unsupported/conflict/failure 不得折叠为成功，不强制接管活跃 owner，不加载 Root 来伪造冷态结果，不建设 relay、
   queue、第二套 registry 或补偿平台。
5. **`#37847` 严格窄回移**：只解决 persisted V2 member residency reload 的 inherited environment 保留与现有显式 override 优先；不改变
   V1、fresh root、顶层 fork 的默认环境合同，不自动发起 turn/API，不引入新配置、协议、权限、durability/binding 或环境管理体系，除非
   live code 证明一个更小的等强适配必须经过既有相邻接缝。
6. **默认关闭与兼容 fail-closed**：Durable 仍是 opt-in；feature-off、legacy/non-durable、单 Agent、普通 V1/V2 与 shared workspace 行为
   不因本任务改变。缺失、损坏、版本/identity 不兼容不空建、不静默升级、不换源、不扩权；只有可独立验证部分才能明确只读降级。
7. **Plan 077 并行隔离**：不读取、修改、合并、rebase 或依赖 077 未提交内容。078 主要拥有 core/thread/session lifecycle；正式 query 的
   protocol/client/TUI 由 077 拥有。共享 app-server consumer、protocol、feature/config、schema、Cargo/Bazel lock 和 WBS 同一时刻只由一方
   修改；冲突面延后，后进入主线者基于已提交事实窄整合并承担兼容门，不预定合并顺序。
8. **允许有界调试和重跑**：按最小未打通接缝逐段实现、检查和修复，保留已验证进度。普通代码、fixture、snapshot、轻量检查或审查
   finding 可自主窄修后重跑，不因一次失败停工；重型命令只能在第 10 条对应的已批准批次范围内运行或重跑。不得删测试、弱化断言、
   扩大 fallback 或过早冻结凑绿。只有目标/硬边界冲突、授权外高危扩张、共享写所有权冲突或资源门 fail-closed 才暂停对应动作。
9. **正确性测试而非测评平台**：测试使用 deterministic/fake/offline 和必要真实子进程，不调用真实 API/模型、不训练、不运行 Docker、
   benchmark、CI/PR、发布、上传或付费动作。优先跑受影响 crate/产品入口；core/common/protocol 实际改动触发的就近完整门禁只在聚焦链
   稳定后运行一次，不 routine 使用 `--all-features`，skip/未运行/基础设施失败不得表述为通过。
10. **重型批次须额外批准并由用户调度**：本 ExecPlan 和执行提示词都不授权任何 Cargo build/test/clippy/fix、schema generator 或
    其它会读写 Rust target 的命令。执行者须先完成源码、测试设计和不触发 target 的轻量检查，再向用户报告拟运行的准确命令批次、
    测试范围、`CARGO_TARGET_DIR`、项目/069 target/Windows `C:` 当前容量，以及与 077 或其它重型任务的冲突状态；只有用户可明确批准
    该批次并决定运行时机。批准可按用户明示口径覆盖同批次、同范围的修复后重跑；未明确覆盖的新增、扩大或重跑须再次批准。执行者
    不得自行排队，canonical lock/watchdog 也不能替代该人工授权与调度。
11. **统一共享重型入口**：任何已经用户批准的 Cargo build/test/clippy/fix、schema generator 及其它读写 Rust target 的命令必须显式设置
    `CARGO_TARGET_DIR=/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target`，并通过
    `multidev/justfile` 已接入的 canonical lock/watchdog 入口。不得 direct Cargo，不得使用仍直调 Cargo 的 `just codex`/`exec`/
    `app-server-test-client` 作为正式重型入口，不得禁用/绕过 wrapper、提高 jobs/test threads、并行构建或与 Docker/真实本地模型重叠。
12. **磁盘与缓存边界**：每轮 Cargo 前后记录项目总量、069 target 体积、Windows `C:` 实际余量及 wrapper summary/metrics。达到 240GB
    后不再启动新的宽范围构建，先定位增长并收窄；255GB 主动停止，260GB 绝对停止，Windows `C:` 或其它计数按 wrapper/根规则
    fail-closed。不得用 WSL 虚拟余量；不得清理 069 既有缓存。工具链/profile/features 不兼容时不得静默创建第二个大型 target，先评估
    空间与最小增量方案；只清理可精确归属 078 的临时产物。
13. **本地提交后停止**：按 `#37847` 前置、S2 主体、正式验收/文档等有意义批次提交 078 分支；提交前检查 diff、生成物、允许写集、
    主工作区/全部 worktree 元数据和资源退出状态。任何向 `main` 的合并、主线向 078 的整合、push、worktree 删除或分支归档都须用户
    明确批准；最终只交付 clean 本地 078 分支。

## 4. 软性建议

以下建议基于 `dfc4278` live code，只帮助执行者高效收敛，不固定 crate、API、错误枚举、调用顺序、测试数量或内部机制。执行者可采用
更简洁、更优雅且与现有架构契合的等强策略；有实质影响的偏离记录到关键决策即可。

- `#37847` 可先对照官方 [PR #37847](https://github.com/openai/codex/pull/37847) 的
  [commit `4996cf05...`](https://github.com/openai/codex/commit/4996cf05af6e96e03d0d997681e7db85bce04deb) 与当前
  `AgentControl::ensure_v2_agent_loaded` → `resume_thread_with_history_with_source` → `StartThreadOptions` 链，优先做当前架构下的最小修复。现有测试 helper 足够清楚时复用；若完整
  产品 eviction→reload 场景更能证明行为，可增加专门 integration test，不必机械复制上游全部测试辅助代码。
- 顶层 fork/new/clear 的底层新 Root/Session 接缝已经存在，优先解除 S1 阶段性 durable gate 并补身份/空 Team 结果，而非重写 history
  fork。`spawn_agent fork_turns` 只选择 none/all/一个代表性 N 验证 Team 边界，既有 history 矩阵继续拥有截断细节。
- V2 Root resume 优先复用现有 Agent graph metadata restore 与按需 member reload；不要自动重开 descendant subtree。member
  re-register 已有幂等 Team participant 语义，先找真实断点再决定是否需要新能力。
- Root close、failed close 与 idle unload 优先复用 S1 的 lifecycle gate、close permit、`shutdown_and_wait` 和 tracked-owner 语义。重点检查
  app-server removal/archive/delete 的准备顺序是否在失败前丢掉 owner；若现有 consumer 适配即可闭合，不增加新的 close coordinator。
- archive 可以保留 Team snapshot 原位，unarchive 可以只恢复原生 Root；本计划不预定介质移动方式。delete 若需要协调 Team durable
  artifact，可在现有 ThreadStore/Team durability 权威域加入窄能力，以“两个结果都确认才 terminal”为准，不要求通用事务平台。
- 建议分层测试：`#37847` core 聚焦；team-state/thread-store 领域与故障；core durable Session/fork/spawn/close/进程退出产品链；只有触及
  app-server/TUI consumer 时才跑对应公共入口和 snapshot。避免为同一语义在每层复制重型用例。
- 调试时用小型 task-owned Session/store fixture 逐段保留进度；全链稳定后再冻结候选，从新的 namespace 运行正式场景组。正式轮受窄修
  影响时只废弃并重跑受影响的正式场景，不把无关已验证进度全部清零；最终结论必须对应最终代码与配置。
- 可使用少量子智能体并行调查互不重叠的 reload、fork/spawn、close/cold lifecycle 或做独立终审；共享代码由单一集成者修改，不建立
  评审委员会、审计清单、签名或机器可信设施。

### 建议的阶段编排与退出条件

**A. 基线、写集与资源确认**

- 核对 078/077/main/069 的 branch、HEAD、clean 状态、共享写集与当前重型资源；映射 S1 已有 reload/resume/close/cold lifecycle 接缝。
- 退出条件：只依赖已进入 `dfc4278` 的事实；共享冲突面已识别；如需重型批次，已准备供用户判断和调度的准确命令、范围与资源报告。

**B. `#37847` 独立前置阶段**

- 完成窄适配、聚焦回归代码和轻量检查；需要 test/lint 等重型门禁时，先按第 10 条逐批请求用户批准和调度。验证 inherited
  environment、override 优先与 reload 无自动 turn/API 后单独提交并做独立审查。
- 退出条件：前置 commit clean、无高/中 finding；停在 078 分支请求用户批准进入本地 `main`，不夹带 S2 正式实现。

**C. 前置主线消费与 S2 分段实现**

- 在用户批准的 Git 边界内消费包含前置的精确最新 `main`；依次闭合 resume/member reload、顶层 fork 与 child spawn、new/clear/
  display clear、detach/idle unload、正常/失败 close、完整进程退出、archive/unarchive/delete、legacy/corrupt/incompatible。
- 退出条件：每类核心结果有最小产品回归，失败路径保留可重试 owner/authority，未新增第二套权威或控制平台。

**D. 聚焦门禁与相邻回归**

- 先按实际写集把 team-state/thread-store/core 及必要 app-server/TUI 公共入口组织成尽量少且可判定的重型批次，逐批向用户申请批准并
  由用户安排与 077/其它重型任务的运行顺序；获批后关闭真实 finding。聚焦稳定后，如 core/common/protocol 写集需要相称完整门禁，
  再把该批次单独报请用户批准。
- 退出条件：最终代码上的相关 test/lint/fix/fmt/generator/diff 门满足，资源记录完整；未运行项与基础设施阻断诚实记录。

**E. fresh 正式轮、兼容验收与本地交付**

- 把 fresh 生命周期场景组及必要的 query × lifecycle 兼容门作为独立重型批次报请用户批准、调度；获批后从全新 Session/store
  namespace 运行，且只在 077 已进入 main 时纳入兼容门。由未参与主体实现的审查者复核身份、authority、失败可重试、冷态
  partial/unknown、关闭态和无自动模型/API。
- 退出条件：正式轮有效、无未关闭高/中 correctness finding、日志与计划动态状态精炼、078 分支本地提交且 clean；不 merge/push。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已从 clean `main@dfc4278233cf6c361fd6bbef7b3fb6107906f22d` 创建
  `.claude/worktrees/078-m4-s2-recovery-lifecycle` / `worktree-078-m4-s2-recovery-lifecycle`。
- 已只读核对根/`multidev/` 规则、README、当前 WBS、Plan 067/069/070/072/074、S1/C0 日志、live core/thread-store/team-state/
  app-server 生命周期源码与测试，并确认 `#37847` 的 exact 上游提交及当前缺口。
- 已把 Plan 077/078 并行关系、后整合兼容责任及 `#37847` 作为 Plan 078 独立前置阶段的例外窄同步到权威 WBS；其它上游回移规则不变。
- 已完成未参与起草者的独立计划审查，无 high、medium 或需修正的 low finding；重型逐批授权/人工调度、069 缓存例外、合理重跑和
  Git 停止边界相互一致。
- 规划时只读实测项目总量 `169884008448` B（约 158.2 GiB）、069 target `76324540416` B（约 71.1 GiB）、Windows `C:` 可用
  `103033847808` B（约 96.0 GiB）；这些是规划快照，执行者须在每轮重型命令前后刷新，不得当作持续事实。
- 已按上游 `4996cf05...` 的产品结果完成 `#37847` 窄适配：V2 member reload 把 inherited environment selections 显式传入
  `StartThreadOptions`，V1、fresh root 与顶层 fork 路径不变。
- 已把既有 `ensure_v2_agent_loaded` 回归扩展为真实 residency eviction → reload 场景，验证 inherited selection 压过 sender/default
  fallback、恢复后的默认 turn 仍绑定该环境，且 reload 前后没有新增 thread Op。
- 最终聚焦门禁 3/3 通过，覆盖 V2 eviction/reload、旧 root/fork environment 合同和 V1 descendant resume；`fmt-check`、`diff --check`
  通过。独立实现审查无 high、medium 或 low finding，不要求新增测试。
- `#37847` 已形成独立提交、通过外部审查并获准进入本地 `main`；078 已消费包含该精确前置的本地主线提交，未 merge/push。
- S2 主体已闭合 durable Root/member resume 与 lazy reload、顶层 fork/new/clear 和 child `fork_turns` 身份边界、descendant-first close、
  可重试 failed close、idle unload 以及 archive/unarchive/delete 的 owner、writer 与部分失败语义，并补齐相应聚焦回归。
- shutdown 提交、等待取消和 app-server 超时采用既有 Session/ThreadManager 生命周期接缝：已接受 Shutdown 保持 Session Control fenced，
  late observer 只在真实 termination 后按 exact owner 收尾；独立聚焦复审最终无 high/medium correctness finding。
- 已补齐轻量验收矩阵复核发现的四处证据缺口：保留 non-durable V2 resume 旧合同并精确比较 durable child metadata；用 paused-time
  单元测试覆盖完整 idle delay；让 default/Local archive 共同使用 ordered helper 并显式报告 runtime partial；覆盖 Team artifact 已 unlink、
  Root marker 尚存的 delete retry。另补公开 corrupt snapshot resume 无模型请求及显式 `/new` 新空 Team 回归。
- 最终候选已通过 thread-store 全量 `199/199`、app-server 全量 `1134/1134` 及 Plan 078 app-server 正式场景
  `23/23`；受最后重构影响的 idle-unload 场景又以禁用重试的 fresh 运行 `1/1` 通过。core 最终聚焦
  `19/19` 通过，包含 18 个 S2 合同和当前源码的 schema 一致性；三个受影响 crate 的 clippy 最终无警告。
- 一次三 crate 组合批次在测试前被内存 PSI watchdog 停止，随后改为 `CARGO_BUILD_JOBS=1` 串行。core 全量批次
  首次被外部 Cargo 进程中断，第二次完成为 `3417 pass / 16 fail / 8 skipped`；失败由 Publication Critic
  外部环境要求、旧基线 fixture/realtime timeout 与共享 target 的 077 过期 schema artifact 构成，不与 078 产品链
  重叠。在不 clean 共享 target、不建第二 target 的前提下强制当前源输入重建，后续 app-server 全量与
  core schema 聚焦门均证明最终候选使用当前 078 源码。
- 最终候选已通过 `fmt-check` 和 `git diff --check`。未运行 Docker、真实 API/模型、训练、测评、CI/PR、
  push 或 main 合并。
- 最终独立终审发现一项 medium：app-server 成功移除 V2 member runtime owner 后没有清除该 Team 的独立
  residency 槽，容量为 1 时同 ID lazy reload 会被残留的 protected slot 拒绝。修复已把清理收口到
  ThreadManager 所有成功 map removal，并在 exact-owner 的 map/gate lease 内使用实际 removed thread 所属
  `AgentControl` 清理，避免误清 replacement。现有 eviction/reload 回归新增 capacity=1 的 app-style
  unload → lazy reload 链；轻量复审确认 finding 已关闭，无新 high/medium/low。
- 整改后最终源码上，capacity=1 unload/reload、exact late removal 和 shutdown-all 三条 core 聚焦回归
  `3/3` PASS；`codex-core` clippy 无警告 PASS。clippy 首轮发现的 `expect_used` 仅把不必要 panic 窄修为
  fail-closed `false`，同一审查者确认不改 exact-owner/gate/residency 顺序，最终 high/medium/low 均无。

### 当前工作

- S2 产品、最终整改、相邻回归、fresh 正式场景、clippy、独立终审、精炼日志和 078 本地提交已完成。
  当前只待向指定外部审查者发送 Codex 跨会话队列消息；发送后停止，不 merge/push。

### 本任务剩余步骤

- 发送外部审查队列交接；不 merge/push。

### 阻塞项

- 无阻塞项。最终重型资源已释放，未使用用户的额外授权清理 077 产物或共享 target。

### 当前验收状态

- `PREREQUISITE_ACCEPTED / S2_IMPLEMENTED / HEAVY_GATES_PASS / FRESH_FORMAL_PASS / FINAL_REMEDIATION_PASS /
  INDEPENDENT_REVIEW_PASS / LOCAL_DELIVERY_COMPLETE / EXTERNAL_REVIEW_PENDING`。
  core 全量基线批次的 16 项非 078 失败如实保留，不冒充为全 core PASS；Plan 078 聚焦产品门、完整 app-server/
  thread-store 相邻回归和 fresh 正式组均已通过。

### 交接边界

- 执行者从阶段 A/B 开始；不得把计划编制时的源码调查或 WBS 更新冒充产品实现。
- 与 Plan 077 并行共享文件的 078 语义所有权限定为：`core/src/team/durable.rs` 的 durable Team snapshot 路径统一调用；
  `thread-store/src/lib.rs` 的该路径 helper 导出；`thread-store/src/store.rs` 的 `ThreadStore::archive_threads` /
  `archive_thread_ids_in_order` ordered lifecycle write 语义，保证部分 archive 不得伪报成功。Plan 077 继续拥有正式 durable query
  read/locator seam；当前未发现双方需要改变同一 API 语义的实质冲突，普通文本冲突留给后整合者基于最新 `main` 收敛。
  077 的 durable query read/locator seam 不属于 078；后整合者基于最新 `main` 收敛普通文本冲突，不改变上述 lifecycle/write 合同。
- Plan 078 完成后冻结本计划；后续正式 Session Control/TUI 与 M4-Z(core) 只链接当前 WBS，不在本计划继续规划。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 从 clean `main@dfc4278...` 创建独立 078 worktree；与 077 只共享已进入 main 的事实 | 保护两项并行工作及共享接缝，避免吸收未提交设计 | Git/并行 | 已采纳 |
| 002 | `#37847` 收入 Plan 078，作为独立前置提交和验收阶段，不另建第三份 plan/worktree | 修复很窄但仍是 S2 PASS 前置；减少无必要的计划、工作树与缓存分叉 | 范围/阶段 | 已采纳 |
| 003 | `#37847` 前置获批进入本地 main 后，078 才消费精确主线并开始 S2 正式轮 | 保持前置可独立审查，也遵守 merge/push 需用户批准的 Git 边界 | Git/验收 | 已采纳 |
| 004 | 078 拥有 core/thread/session lifecycle，077 拥有正式 query；共享面由后整合者窄收敛，后进入者跑兼容门 | 两任务无产品前置，但不能并发争写协议、TUI、锁文件和 WBS | 并行/所有权 | 已采纳 |
| 005 | 身份、authority、失败与冷态结果是硬产品边界，内部 module/API/机制由执行者按 live code 自主选择 | 保留架构自由，避免为追求复用扭曲语义或过早固定路线 | 架构 | 已采纳 |
| 006 | 普通失败和 finding 自主窄修重跑；稳定后再用 fresh Session/store 跑正式轮，不以 cargo clean 定义干净 | 保留已验证进度与合理调试冗余，同时保证最终证据对应最终实现 | 调试/验收 | 已采纳 |
| 007 | 077/078 的重型批次须逐批获得用户明确批准并由用户人工调度；获批后复用 069 target、走 canonical wrapper，不新建第二个大型 target | 把串行判断留给用户，同时满足全局互斥与当前磁盘余量，避免重复约 72G 缓存 | 构建/资源 | 已采纳 |
| 008 | detach 与 deferred idle unload 分离，idle/close/cold removal 都不能在失败时先丢唯一 owner | 即时客户端附着不是领域生命周期；S1 barrier 只有被真实 consumer 正确调用才成立 | lifecycle/authority | 已采纳 |
| 009 | archive/unarchive 复用原生冷态能力；delete 仅在线程与 Team durable 结果均确认时 terminal，但不预定介质/事务形状 | 闭合产品结果且避免建设 takeover、补偿事务或第二套 registry | cold lifecycle | 已采纳 |
| 010 | `#37847` 采用上游 5 行产品结果，并在现有 AgentControl fixture 中验证真实 residency 驱逐与恢复，不机械移植上游完整 mock 集成用例 | 当前 disabled/default environment 测试接缝会在协作调用前阻塞；复用既有 residency 能力更窄且直接验证目标语义 | 前置测试 | 已采纳 |
| 011 | S2 重型批次在宽限期间使用临时 `270/285/290GB` 项目门限、共享 069 target 和 `CARGO_BUILD_JOBS=1` 串行 | 保留共享缓存且避免内存 PSI 再次停止；临时变量不写入仓库配置 | 构建/资源 | 已采纳 |
| 012 | 共享 target 出现 077 schema artifact 污染时，仅通过当前源输入时间戳触发有界重建并以 app 全量/core schema 复验，不 clean 共享 target、不建第二 target | 纠正跨 worktree 增量 artifact 不属于当前源码的证据偏差，同时遵守缓存与空间边界 | 构建/验收 | 已采纳 |
| 013 | 成功移除 ThreadManager owner 时，在 map/availability gate 内用实际 removed thread 的 `AgentControl` 同步清理 V2 residency | residency 是 Team 作用域的独立容量状态；在移除原子区内收口才同时防残留 slot 与 replacement 误清 | lifecycle/residency | 已采纳 |
