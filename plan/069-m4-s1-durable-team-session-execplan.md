# Plan 069：M4-S1 Team Session 持久生命周期

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 普通实现、构建、测试或快照问题应由执行者自主窄修并重跑，不属于改变任务合同。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

在 `main@445b6eae7f1df5bfd106fcd963141173a1292af5` 的 M4-A 共同合同上，把进程内 canonical Team State
实现为可跨进程延续的 Team Session：它与既有 Session/root lineage 和 `TeamInstanceId` 绑定，Root 与 child 的 Team mutation
共享同一个 Root 写 authority；该 authority 连续覆盖 mutation 的 durable commit 与成功返回。已经成功的 mutation 在进程退出后可恢复，
非 owner 能读取自洽的 committed state，新进程重新取得 authority 后能恢复同一 Session/Root/TeamInstance 并继续一次 mutation。

这是 Team 领域、Root authority、持久提交、读取和基础恢复组成的一项完整产品能力，不是单独给 `TeamStore` 增加序列化。职责契合时
复用既有设施；强行复用会扭曲语义时允许新建专用能力，但新能力仍须融入现有配置、生命周期、错误、测试和观测方式，不得形成第二套
Team State、writer authority、Session identity 或只读状态源。

### 完成/验收标准

- [ ] **完整跨进程主链**：从全新的任务专用 Session/store 状态创建可写 Durable Team，完成至少一次 canonical Team mutation 并得到
  durable success；非 owner 读取到自洽 committed view；进程退出后，新进程定位并取得同一 canonical Root authority，恢复原
  `SessionId`、Root `ThreadId`、`TeamInstanceId` 与已提交 Team state，再成功继续一次 mutation。不得用重铸 ID 或空 Team 冒充恢复。
- [ ] **成功边界真实**：mutation 只有在其结果已达到可恢复边界后才返回成功。Team revision 之外但为 canonical 不变量、重试或后续正确
  mutation 所必需的状态轴也达到相称的 durable 边界；提交失败、authority 丢失或结果不确定时返回诚实的 failure/conflict/unknown/
  unavailable，不把仅内存成功报告为 durable success。该合同适用于现有全部 canonical mutation 入口，不限于主链选取的示例；测试
  可依共同提交接缝和代表性状态轴覆盖，不要求机械枚举笛卡尔积。既有 route grant/assignment 在 notice/delivery 前完成 canonical commit
  的顺序不得退化；已报告成功的 delivery state 同样达到 durable 边界，但外部 notice/副作用本身不纳入持久化。
- [ ] **单一 Root authority**：第二进程在 owner 存活时不能取得重叠写 authority 或成功写 Team；Root 与 child mutation 都使用同一个
  canonical Root authority，child 自身的 Thread writer、participant 身份或一次性预检查都不能绕过它。authority 必须连续覆盖提交和
  成功返回，而非只在 mutation 前后探测锁文件。
- [ ] **committed read**：健康后端上的非 owner read 能返回一个满足 Team 领域不变量的完整已提交视图；并发或故障现场若不能证明当前
  视图，可明确返回 stale/unknown/unavailable。不得拼接不同提交边界，也不得绕过 canonical durable read model 读取第二份状态。
- [ ] **恢复 fail-closed**：durable marker/backend/lineage/state 缺失、损坏、版本不兼容、Root/Session 无法交叉证明或
  `TeamInstanceId` 不匹配时，不创建空 Team、不换新 ID、不静默退回内存 Team、不覆盖旧状态；只有能独立验证的兼容部分才可按明确
  只读语义降级。
- [ ] **失败关闭可重试**：durable commit、session task 或 shutdown/close 失败不伪报完成，不移除唯一可重试 owner，不提前释放或交接
  Root authority。只要仍有 mutation-capable descendant，Root/Team close 就不能完成或释放 authority；实现可阻止 close，或在同一
  barrier 内先安全 quiesce/close 这些 descendants。
- [ ] **启用与兼容**：Durable capability 默认关闭；只有有效的 V2 + Team State + durable backend + canonical Root authority 组合才可
  创建或恢复为可写 Durable Team，缺一项即 activation/start fail-closed。关闭态保持既有单 Agent、V1/V2、non-durable Team 与 shared
  workspace 行为；legacy/non-durable Session 不自动升级。已有 durable marker 的 lineage 在 Durable 关闭时只能按可独立验证的能力
  只读，或拒绝可写恢复，不能创建 fresh non-durable Team 覆盖原实例。
- [ ] **故障与领域回归**：用相称的 deterministic/fake、领域、跨进程和故障注入回归覆盖 root/child mutation、双进程竞争、非 owner
  committed read、authority 丢失、提交失败/结果未知、损坏与不兼容、失败 close 及 Root-close-with-live-child。测试必须验证可观察
  结果和恢复后的真实状态，不以只检查文件存在、marker 或 mock 调用次数替代产品行为。
- [ ] **最终前置与正式轮**：`#37198` 由独立任务合同完成 RONDO 窄回移并进入 `main`；在用户另行批准把该最新 `main` 合入 069 分支后，
  闭合 persisted cwd 与 live execution override 的聚焦回归，并从全新的任务专用 Session/store 状态完整重跑一次 S1 主链，以该轮作为
  正式结果。“全新状态”指新的领域状态和最终代码/配置，不要求 `cargo clean`。
- [ ] **独立验收**：实现、相关门禁和最终正式轮均有可复核记录；独立审查无未关闭的高/中等级 correctness finding。普通 finding 允许
  执行者自主窄修、重跑和复验，不因首次失败整组作废。

## 2. 范围

### 允许修改

- `multidev/codex-rs/` 内实现 canonical Team durability/read、Root authority 连续资格、基础定位/装载/恢复、默认关闭配置、关闭 barrier
  和相称领域/跨进程测试所必需的产品代码；可修改职责匹配的现有模块，也可新建与现有架构契合的专用模块或 crate。
- 为上述能力服务的窄测试支持、deterministic/fake/fault-injection fixture，以及既有测试组织要求的 snapshot/schema；不得借测试设施
  建设独立 daemon、通用协调平台或第二套运行时。
- 本任务自己的 `plan/069-m4-s1-durable-team-session-execplan.md`、精炼 `agent_log/` 和任务专属源码。
- 若实现确实需要依赖、workspace member、公共 core/protocol/config 接缝或生成物，允许做最小必要修改并运行仓库工具更新对应
  Cargo/Bazel lock 或 schema；这些路径属于三任务共享串行面，开始修改前必须确认当时没有 068/070 执行者持有该共享面，完成后及时
  形成可合流的本地提交。若存在并发所有者，只延后冲突面并继续其他不冲突工作，不读取对方未提交内容或猜测合并。

### 不允许修改

- `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS/durable-team-runtime.md`、`doc/WBS-COMPLETED.md`。并行开发期不在
  069 分支同步路线或完成状态；后续获批的主线整合者基于最新 `main` 窄同步。
- Plan 068 的 Publication Critic crate、`eval/`、训练/模型部署/资格资产、计划或日志；也不消费其模型、Docker、远端资源或未提交结果。
- Plan 070 拥有的 experimental app-server v2/client/TUI 协议、正式/实验控制面 API、通知、UI 和其 schema/test 资产。若 Root authority
  或 close barrier 的领域结果确实需要现有 app-server 内部 lifecycle consumer 做窄适配，069 只能在共享面串行规则下接入该结果，
  不新增控制面能力、不经控制面直接写 durable medium，也不为 S1 发明 RPC、TUI 或跨进程 mutation relay。
- M4-S2 的顶层 fork、child spawn 完整矩阵、`/new`、`/clear`、detach、idle unload、member reload、archive/unarchive/delete 等完整
  生命周期收口；M4-W0/W1、worktree binding/handoff；M4-Z 或最终 Critic + durable Team resume 组合回归。
- `#37198` 的实际回移、其他上游增量或 Codex `v0.147.0` 整体升级。069 只在该独立回移进入 `main` 后消费其事实并做聚焦兼容回归。
- 完整 transcript、reasoning/CoT、运行中的模型/工具请求、外部副作用、自动恢复 model turn/API、Team clone/branch、writer lease/
  registry、workspace registry、通用事务/补偿/审计/可信平台或第二套 Team State/read source。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/凭据、ignored 私有模型或测评正文、训练输出/权重，以及项目外个人文件或私有数据。
- Plan 068、070 或其他 worktree 的未提交文件、diff、commit 内容或设计；并行核对只使用 `git worktree list`、branch/HEAD/status 路径和
  资源/进程元数据。已经进入 `main` 的提交按正常主线事实读取。

### Git-ignored 与主工作区边界

本任务全部 tracked 编辑都在 `.claude/worktrees/069-m4-s1-durable-team-session` 中完成，不预计需要直接修改主工作区或 ignored 产品
资产。linked worktree 内正常的 `target/`、`.codex/build-watchdog/`、临时 Session/store fixture 可由仓库既有命令在任务边界内创建；
共享构建锁与资源计数器只能由 `just` / `scripts/with-build-lock.sh` 正常管理，不手工编辑。若只读核对 git-ignored
`codex-source-code/` 确有必要，只从主物理仓库读取冻结源码，不在其中写入或开发。任何必须直接写主工作区、修改 ignored 资产或读取
私密运行数据才能继续的发现，都属于范围变化，应停止该动作并向用户说明。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部进度而违反。

1. **精确基线与并行隔离**：开发从 `main@445b6eae7f1df5bfd106fcd963141173a1292af5` 开始；只读核对其他 worktree 的
   branch/HEAD/status 路径和资源状态。069 不覆盖旧分支文档、不吸收未提交实现，也不与 068/070 并发争写共享 WBS、manifest/lock、
   schema 或不可避免的 common/core/protocol/config 接缝。
2. **复用现有三类身份与 canonical 状态**：`SessionId`、canonical Root `ThreadId`、`TeamInstanceId` 分别继续拥有 lineage、原生
   lifecycle/authority anchor 和 Team generation 职责；当前部分 ID 同值不是新格式承诺。Team State 仍是唯一 canonical coordination
   状态，durability/read 只为它提供持久提交、恢复和读取，不新建身份映射或竞争状态源。
3. **Root authority 覆盖完整成功路径**：以现有 canonical Root active-writer 为唯一排他基础做架构内扩展。Root/child mutation 必须
   使用同一不可绕过的 authority，且从 mutation 开始连续覆盖 durable commit 与成功返回；不能以 child writer、participant check、
   进程内 mutex、一次性 probe、后台最终一致或新 Team lease 代替。
4. **恢复和读取结果必须诚实**：成功即已可恢复；健康非 owner read 必须能读到自洽 committed state，故障/竞争时可明确降级为
   stale/unknown/unavailable。mutation 的领域校验、canonical commit、durable success、通知与返回之间必须保持可证明的线性边界；
   执行者自主选择同步/异步 API、事务或 prepare/commit 形状，但不能让 durable commit 重排、失败后内存状态被读成 committed，或错误
   返回与后续可见成功互相矛盾。无法证明 lineage、instance、兼容或提交结果时 fail-closed，不创建空 Team、不换源、不静默升级 legacy。
5. **失败不释放唯一资格**：commit/shutdown/close/session-task 失败时保留可重试 owner 与 Root authority，不伪报完成；仍有
   mutation-capable descendant 时 Root close 不得完成。显式 discard 若被复用，必须是另行确认的数据丢失语义，不能冒充正常关闭。
6. **默认关闭且依赖闭合**：Durable 是明确 opt-in；可写启用必须验证有效 V2、Team State、backend 和 canonical Root authority。
   可写 owner 的 cold resume 必须在证明 Session/Root lineage、取得 canonical Root authority 并完成合法 hydrate 后，才可向 owner
   runtime 暴露可写 Team；不得让当前默认创建的 fresh handle 先冒充恢复结果。非 owner durable read 不取得 writer authority，但须先
   验证 lineage/instance 并只走 canonical committed read model。关闭态和 legacy/non-durable 行为不得因 marker、恢复入口或新配置而改变。
7. **保持 S1 边界**：不把 S2/C0/C*/W/M4-Z、Publication Critic、完整 transcript/运行中副作用或通用平台夹带进 069。必要的专用
   能力可以完整实现，但不能用“未来任务会处理”下放本计划明确拥有的 durable success、read、authority、基础恢复或 close barrier。
8. **调试允许有界修复与重跑**：按创建 → mutation → durable success → non-owner read → 进程退出 → 新进程恢复 → 继续 mutation 的
   顺序逐段打通，保留已验证进度并从首个未通处修复。普通代码、依赖、构建、测试、fixture 或 snapshot 问题自主窄修并重跑；不得因
   一次可修复失败停工，也不得删测试、弱化断言或扩大 fallback 凑绿。只有目标/硬边界冲突、授权外高危扩张或共享面所有权冲突才暂停
   相应动作。
9. **测试与资源门禁**：不调用真实 API/模型，不训练、不做性能测评，不运行 Docker、CI/PR、发布、上传或付费外部动作。Rust 格式、
   lint、构建与测试使用 `multidev/justfile` 及仓库共享锁/看门狗，保持既有并发上限；拿不到锁、cgroup、Windows `C:` 实际余量或其他
   必要计数器时 fail-closed。069 接管重型资源前必须确认 068/070 的模型、Docker 或构建进程已经真实退出；其他任务的资源与外部
   授权不转授 069，build lock 也不能替代对 Docker/模型进程的核对。资源尚未释放或锁正忙时等待后重试，不终止其他任务、不绕过门禁。
   调试期只跑受影响 crate/目标的聚焦门禁；若 common/core/protocol 的实际改动触发就近规则，可在最终整合边界经用户本次授权运行一次
   必要的完整 `just test`，不在调试期反复跑全量，也不使用 `cargo clean` 伪造“干净状态”。
10. **外部前置不夹带**：`#37198` 必须由独立任务合同进入 `main`，不由 069 实施。069 可在此前完成开发与预验收，但不得宣布最终
    M4-S1 PASS；只有用户另行批准把含该回移的最新 `main` 合入 069 分支后，才执行 persisted cwd/live override 回归和最终正式轮。
11. **本地交付后停止**：按有意义批次精炼记录并提交 `worktree-069-m4-s1-durable-team-session`；提交前检查 diff、生成物、允许写集、
    主工作区及所有 worktree 元数据。未经用户后续批准，不把 069 合入 `main`，不 merge/rebase 其他分支，不推送、不关闭 worktree、
    不归档/重命名分支，也不触碰 068/070 工作。

## 4. 软性建议

以下内容用于帮助执行者高效收敛，不固定介质、格式、crate、API、同步机制或测试形状。执行者可以采用更简洁、更契合当前代码的等强
策略；有实质影响的偏离只需写入关键决策记录，不必为每个局部选择请示。

- 开始时把现有 `TeamStateHandle/TeamStore`、Root `ThreadStore` active-writer、AgentControl/root tree、cold resume 和配置入口映射成
  “已有保证 / S1 必须补足 / S2/C0 所有”，再选择落点。不要做全仓 census，也不要把当前类型布局升级为永久公共 API。
- 对 TeamStore 的状态轴按“恢复 canonical 不变量、幂等重试和继续 mutation 是否需要”分类；允许显式排除纯运行中、可重建或本任务
  明确不持久化的状态，但不能只保存 revision/可见 Event 而无意丢失 participant、retry、wake、route/fact 等继续正确运行所需事实。
- 优先复用现有持久介质的原子提交、版本和损坏处理能力；如果它无法提供 Team 所需的 committed read 或身份交叉验证，新建窄的
  Team durability/read 能力通常比把 Team State 塞进 transcript 更干净。具体用文件、数据库、journal、snapshot 或组合由真实接缝决定。
- authority 可以通过现有 guard 的所有权延伸、显式 capability 或等强结构传到 Team mutation/commit；选择以“调用者无法绕过且失败时
  不提前释放”为准，不要求某个类型名、锁层次或事务顺序。
- 测试可分为：持久格式/兼容与故障单元测试，Team 领域与 authority 集成测试，真实子进程竞争/退出/恢复测试，以及关闭态/legacy
  回归。跨进程链优先复用现有 test binary/process helper；只有确有缺口时再加窄 helper，不建设测试专用服务平台。
- 调试链先用小而可丢弃的 Session/store fixture 逐段复跑；每段通过后保留代码和诊断入口，从首个失败点继续。全链稳定后冻结实现和
  配置，再以全新的领域状态完整运行一次，避免过早把第一次长链当正式结果而因窄修整组报废。
- 可用少量子智能体并行处理相互独立的 durability、authority、测试或终审工作；共享文件由单一集成者修改，避免多个 agent 同时改
  TeamStore、config 或 manifest。独立审查聚焦可复现的高/中 correctness，不建设审计清单、签名、可信证明或机器化验收平台。
- `#37198` 进入主线后的回归只验证它拥有的 persisted cwd read/list 与 explicit live execution override 边界，以及 069 受影响接缝；
  它不替 Team durable read model 或 workspace binding 背书。后整合者吸收最新 `main` 后只重跑真正受影响的门禁。

### 建议的阶段编排与退出条件

**A. 基线、写集与接缝确认**

- 核对指定 HEAD、主工作区/全部 worktree 元数据、当时的重型资源所有者，以及 Team State、Root authority、ThreadStore、恢复入口和
  配置的 live 接缝；只冻结产品结果，不预选介质或格式。
- 退出条件：069 专属写集明确；共享串行面没有并发 owner，或已把相应修改延后；主链首个真实缺口已定位。

**B. 调试链打通**

- 逐段实现并验证创建 Durable Team、root/child mutation、durable success、非 owner committed read、进程退出、新进程定位/取得
  authority、恢复同一 TeamInstance 和继续 mutation。
- 退出条件：从首个未打通处修复后，整条链在调试 fixture 上连续成立；成功边界和真实恢复结果均可观察。

**C. 失败、竞争与兼容收口**

- 覆盖竞争 owner、child 绕过、authority 丢失、提交失败/unknown、损坏/不兼容、failed close、live child barrier、配置非法组合、
  durable marker 与 legacy/non-durable 混合现场。
- 退出条件：失败不伪造成功/空 Team/authority handoff，关闭态与 legacy 聚焦回归通过；无需为测试预建额外控制面。

**D. 预验收、本地提交与外部前置等待**

- 运行格式、lint、受影响 crate/集成目标及由实际公共改动触发的相称门禁；审查 diff、生成物、任务日志和工作树状态，形成干净的 069
  本地提交。独立审查普通 finding 由执行者窄修并复验。
- 退出条件：069 自有实现达到预验收且本地提交完整；若 `#37198` 尚未进入 `main` 或尚未获批吸收最新 `main`，诚实标记为等待最终
  前置，不把预验收写成 M4-S1 PASS。

**E. 最终合流后的正式验收**

- 用户另行批准后，把已包含独立 `#37198` 回移的最新 `main` 合入 069 工作树分支，解决真实冲突并复跑受影响门禁；从全新的任务专用
  Session/store 状态完整执行一次主链和 persisted cwd/live override 聚焦回归。
- 退出条件：正式轮证据有效，独立终审无未关闭高/中 correctness finding，069 分支形成最终本地提交；仍不自行合入或推送 `main`。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已在指定基线和 069 worktree 内完成阶段 A-C 主体实现；四份共享 WBS、Plan 068/070 资产及控制面协议均未进入写集。
- canonical Team snapshot 已具备版本、checksum、完整领域状态、严格 hydrate、committed read、未知结果 reconcile 与 durable success 边界；
  pending observation 保持短生命周期，不伪装为 committed state。
- Root active writer 已扩展为可传递 capability；Root/child mutation 共用同一 OS-backed authority，写 permit 连续覆盖 commit、安装、通知和成功返回；
  close permit 跨越 thread persistence shutdown，失败 abort 后保留 owner。
- Session 已接入默认关闭的 durable 配置、fresh/cold resume、marker/legacy fail-closed、稳定共享 Team handle、显式初始化失败清理和最小 live-child close barrier。
- 调试与聚焦预验收已覆盖 Team 领域、thread-store authority、真实子进程竞争/恢复、真实 Session/tool cold resume、durable-off marker 拒绝、
  failed close 无 `ShutdownComplete` 且可继续 mutation；配置 schema 已生成，Bazel 9 lock update 成功且无 lock diff。
- 独立终审发现 owner 在 transient/unknown commit 后缺少产品路径自动 reconcile；已把串行 reconcile 接入 Team capability resolve，补足
  unavailable 与 after-write unknown 重试回归，同一审查者复验通过且无剩余高/中 correctness finding。
- 最终 `just fix`（team-state、thread-store、core）与 `just fmt` 已执行。标准 `just test` 因上游 rusty-v8 默认归档 404 在测试前失败；
  checksum-verified Codex V8 等价完整轮实际执行 14,373 项：14,363 passed、10 failed、24 skipped。失败为 8 项 068 Publication Critic
  fixture/断言和 2 项未修改 realtime 连接失败超时；069 durable cold-resume 主链在该完整轮通过。

### 当前工作

- 阶段 D 预验收已完成；069 停在本地提交与外部前置等待边界。

### 本任务剩余步骤

- 等待 `#37198` 由独立任务进入 `main`，以及用户另行批准把最新 `main` 合入 069 分支。
- 执行阶段 E 的聚焦回归、全新领域状态正式轮和独立终审，形成最终本地提交。

### 阻塞项

- 当前无 069 主体实现阻塞。最终 `M4-S1 PASS` 仍受 `#37198` 独立进入 `main` 与后续分支同步批准约束；不得越权回移或宣布最终 PASS。

### 当前验收状态

- `IMPLEMENTATION_COMPLETE / PREACCEPTANCE_COMPLETE / FINAL_PASS_BLOCKED_BY_#37198`。

### 交接边界

- 本任务完成后冻结此计划；S2、C0/C*、W0/W1、M4-Z 和跨线组合回归只链接
  `doc/WBS/durable-team-runtime.md`，不在本计划继续规划。
- 069 工作树只形成本地提交。把 069 合入 `main`、推送、关闭 worktree、归档分支及共享 WBS/COMPLETED 同步均等待用户后续批准。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 从已推送的 `main@445b6eae...` 建立独立 069 worktree，只在其中保存 tracked 变更 | 三任务必须共享正确基线并隔离开发，不从旧 `origin/main` 或 068 分支取事实 | Git/基线 | 已采纳 |
| 002 | 069 开发期不修改四份共享 WBS；manifest/lock/schema 与不可避免的 common/core/protocol/config 接缝实行单 owner 串行 | 避免三路并行覆盖，主线状态由后续单一整合者基于最新 main 窄同步 | 并行写集 | 已采纳 |
| 003 | canonical Team State 直接复用，必要时新建与其集成的 durability/read 能力；不冻结介质、格式、crate、API 或 guard 类型 | 既不能把“序列化”当完整能力，也不应为复用而扭曲语义或过早固定路线 | 架构自由 | 已采纳 |
| 004 | 现有 canonical Root active-writer 是唯一排他基础，Root/child 共用且连续覆盖 durable commit/成功返回 | child writer 与进程内 mutex 不提供跨进程 Team authority，另建 Team lease 会制造竞争权威 | authority | 已采纳 |
| 005 | S1 拥有 durable success、committed read、基础恢复、fail-closed 和最小 live-child close barrier；完整生命周期矩阵留给 S2 | 闭合本任务产品正确性，同时避免吞并 fork/new/detach/archive/delete 等后续任务 | 任务切分 | 已采纳 |
| 006 | 调试链保留已验证进度，从首个未通处自主窄修；稳定后再以全新领域状态跑一次正式轮 | 避免因可修复窄问题整组报废，也防止过早冻结把调试结果冒充正式验收 | 执行/验收 | 已采纳 |
| 007 | `#37198` 独立回移是最终 PASS 前置，不属于 069 实现；吸收最新 main 也等待用户另行批准 | 上游增量有独立任务合同，不能夹带；用户要求本地提交后不自行 merge/push | 外部依赖/Git | 已采纳 |
| 008 | 不为 069 建设 app-server/TUI 控制面、Publication Critic 集成、workspace binding 或通用审计/可信设施 | 保持三任务所有权和第四期子线边界，复杂度只服务真实 S1 问题 | 范围 | 已采纳 |
| 009 | 规划与实现不需要直接写主工作区或 ignored 产品资产；构建缓存/锁/fixture 只由既有受监控命令管理 | linked worktree 足以交付 tracked 代码，手工共享状态会破坏隔离和资源门禁 | 工作区/资源 | 已采纳 |
| 010 | committed Team 使用 Root `ThreadId` 下的版本化 checksummed snapshot；格式与领域校验由 team-state 拥有，core 只实现本地介质适配 | 避免把 Team 状态塞进 transcript，也避免介质层复制领域不变量 | durability/read | 已采纳 |
| 011 | AgentControl 保留稳定共享的 `Arc<TeamStateHandle>`，在 Root 激活时原位安装 durable runtime，不改变既有 `team()` API | 已存在的 control clone 必须看到同一 Team，同时避免为热替换触碰 068 owned 测试和扩大共享 API churn | lifecycle/API | 已采纳 |
| 012 | fresh generation 0 不落 marker，最终 Root 注册才首次提交；激活错误显式等待 `LiveThreadInitGuard::discard` | 避免失败初始化留下可竞争 writer；提交结果未知时仍 fail-closed，不把不确定结果报成功 | activation/failure | 已采纳 |
| 013 | Root close 先停止 child admission并拒绝 live descendant，再取得 Team close permit；thread shutdown 失败时双 barrier abort | 保证 close 与 mutation 不重叠、失败无 `ShutdownComplete`、owner 仍可重试 | close barrier | 已采纳 |
| 014 | owner 的 Team capability resolve 在 read/mutation 前串行执行必要 reconcile；read-only handle 不获得该能力 | transient/unknown durable commit 后必须能从产品入口恢复可写状态，同时不能让非 owner 越权取得写 authority | recovery/authority | 已采纳 |
