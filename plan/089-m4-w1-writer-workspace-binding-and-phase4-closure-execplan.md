# Plan 089：M4-W1 Writer Workspace Binding 与第四期最终收口 ExecPlan

> 本计划是 Plan 089 / M4-W1 的稳定任务合同，也是第四期最后一个必需工作包的收口合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停对应动作并通过本计划指定的跨会话队列请求确认；范围内普通实现、fixture、
> 构建、测试和审查问题允许自主修复与重跑。
> 本计划只描述 Plan 089；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

基于 `main@f258ea5b3ad7ef7799a671b39e91afdca38523f3`，为 RONDO Multi 的显式 writer 实现生产级 Workspace Write
Binding：由调用者预先准备并授权的本地 Git linked worktree 建立稳定 primary binding，决定 writer 的默认 cwd 与默认写入范围；
提供与现有 permission、sandbox、reviewer/auto-review 共同生效的显式有界绑定外辅助写授权；在 reload、member reload、cold
resume 与真实 app-server 进程替换后重新验证；并提供独立、显式、事务式 replacement binding。

Writer binding 是写入能力，不新增 Team Role、第二套 writer authority、workspace registry/manager 或 structured handoff。
Plan 089 必须在自身任务内完成生产实现、M4-S2 与正式 Session Query/Control 兼容、唯一 fake/offline Publication Critic 组合回归、
fresh 四期正式全链、独立终审、文档收口，以及在用户另行批准后的最新主线整合和推送；不得遗留 M4-W2、兼容补丁包或无编号收口任务。

唯一成功结论为 `M4_W1_PASS`。该结论只有在成果通过独立验收、进入并推送 `main`，且权威 WBS/COMPLETED 已标记
`PHASE_4_COMPLETE` 后才成立；仅工作树实现完成或审查接受时只能记录为待用户批准整合，不得提前宣告 PASS。

### 完成/验收标准

- [ ] **生产入口**：显式 writer 可通过真实产品入口建立 primary binding；scoped authorization 的 request/grant/use 走真实现有
      permission/reviewer 产品链；replacement 也有独立、显式、可调用的生产动作。不要求本包增加 binding dashboard 或 TUI，
      但不得用内部构造、test-only permit 或“未来可选控制面”掩盖核心操作入口缺失。
- [ ] **首次动作与双 writer 隔离**：在 task-owned 临时 repository 中创建两个真实 linked worktree，两个 writer 分别绑定后，首次模型或
      工具动作及后续默认写入均从各自 primary cwd 执行，默认写入互不污染。
- [ ] **副作用前 fail-closed**：worktree 缺失、Git/repository/worktree identity 或 trust 失配、workspace roots、permission、sandbox、
      execution environment 不兼容时，在 writer 激活、模型/工具动作或文件副作用前拒绝；不得回退父 cwd、repository root、`main`
      或其它可写目录。一个 binding 失效不得污染另一个 writer。
- [ ] **写入时仍受约束**：所有代表 bound writer 的文件写入路径收敛到一致的 binding 约束。目标路径、symlink、Git/worktree identity、
      permission 或授权在验证后、写入前发生变化时，不得越界写入；主工作区、另一 worktree 与其它绑定外路径在未授权时保持无副作用。
- [ ] **读取语义不扩张**：相对读取和 Git 上下文从 primary cwd 解析；W1 不新增读取授权、读取禁令、保密隔离或 read grant，实际可读
      范围继续由任务授权和现有 permission/sandbox 决定。
- [ ] **Scoped authorization**：绑定外辅助写入只有同时获得显式、有界的 W1 授权和现有 permission/sandbox 允许时才成功；目标与
      生命周期不能外溢，不改变 primary cwd/binding。批准成功、拒绝、超时、失效、权限不足、目标变化及普通 sandbox escalation
      均有直接证据；失败场景不得产生绑定外副作用。
- [ ] **Scoped 生命周期**：实现可以采用最小的不跨恢复临时授权；若选择支持跨恢复授权，必须持久化其必要事实并在恢复时按当前
      permission/trust/sandbox 重新验证。无论采用哪种策略，临时授权都不得静默恢复，也不得随 replacement 自动迁移。
- [ ] **事务式 replacement**：新 worktree 的 Git identity/trust、roots、permission 与 sandbox 全部验证成功后才替换旧 binding；
      失败保留旧 binding，成功后 cold resume 重验新 binding。旧 worktree 的路径和既有 Git 事实继续诚实可见，不自动 merge、
      cherry-pick、判断正确性或解决冲突。
- [ ] **Durable identity 兼容**：resume/member reload 保持原 Session、canonical Root、TeamInstance 和 writer 身份，同时重验 binding；
      顶层 fork、`/new`、slash `/clear` 创建的新 Session/Team 不误用来源 binding；`spawn_agent fork_turns=none/all/N` 保持既有同 Team
      child 语义，不形成第二套身份关系。
- [ ] **Query/Control 与 lifecycle 兼容**：binding 失效不阻止权威 Session Query、只读恢复或诚实展示 unavailable；Session Control、
      close、archive、unarchive、delete、owner replacement 不能绕过 binding，也不能因 binding 失败提前释放 Root authority。
      terminal lifecycle 不遗留可继续写入的孤立 binding；partial/unknown 不伪报清理完成，query/control 不维护第三份 workspace 状态。
- [ ] **关闭态兼容**：W 关闭时，shared workspace、普通单 Agent、既有非 durable/V1/V2 和已完成 S/C 行为不变；已有不可写 binding
      事实如可见，只能按消费入口的诚实 unavailable/read-only 语义展示。
- [ ] **Publication Critic 组合回归**：维护唯一一条 deterministic fake/offline Publication Critic + Durable Team resume 组合回归，
      并纳入 binding 路径；不复制第二条组合链，不调用真实模型/API 或训练。
- [ ] **fresh 四期正式全链**：从全新临时 Session/store/repository/two-linked-worktree 现场开始，使用真实旧/新 app-server OS 进程
      替换，完整证明：创建 Durable Team → 两 writer 分别绑定 → 默认隔离写入 → 有界绑定外辅助写入 → 进程退出与 cold resume →
      binding/permission/trust 重验 → 一个 binding 失效及 replacement → 继续 Team mutation → Session query/control → 正常 lifecycle
      收口。正式轮必须对应最终冻结代码与配置；影响链路的后续修复须相称重跑。
- [ ] **工程门禁**：按实际写集完成必要生成物、格式化、scoped fix/clippy、受影响 crate 聚焦测试、相称邻接回归和 fresh 正式链。
      在资源门允许且代码已冻结后尝试一次 canonical full workspace `just test`；历史无关失败或基础设施阻断单独归因，不冒充通过，
      W1 相关新失败必须关闭。不得机械重跑稳定且未受影响的所有历史矩阵。
- [ ] **独立终审**：执行者先形成 clean 的本地提交并通过指定队列请求本会话审查；范围内 finding 可自主整改、复验、提交并再次通知，
      直至没有未关闭的高/中等级 correctness/security finding，或审查者明确判定任务失败。审查者以代码、功能与保存证据为主，
      不无限扩建审计/可信设施，也不机械重跑重型测试。
- [ ] **文档与四期收口**：独立验收后精炼更新本计划、实施/审查日志、`doc/WBS.md`、`doc/WBS/durable-team-runtime.md`、
      `doc/WBS/multi-agent-trusted-evidence.md` 与 `doc/WBS-COMPLETED.md`。历史 M4-Z(core) 不依赖 W 的形成时事实不反向改写；
      binding 状态展示和 replacement TUI 只可保留为未排期可选增强，不得遗留必需集成、恢复或兼容工作。
- [ ] **本地交付与最终整合**：未经用户另行批准，执行者只提交并保持 089 worktree clean，不合并、不推送、不关闭 worktree、不归档
      分支。用户批准后，整合者以届时最新 `main` 加法式保留 087 或其它已进入主线的权威状态，完成必要合并树检查、最终文档提交、
      推送 `origin/main`，再将完成分支改名为 `zz-done/...`。只有此后可记录
      `COMPLETED / ACCEPTED / INTEGRATED / PUSHED / M4_W1_PASS / PHASE_4_COMPLETE`。

## 2. 范围

### 允许修改

- `multidev/` 内与生产 writer binding、持久化与恢复重验、scoped write authorization、transactional replacement、Agent/Session
  生命周期、现有 permission/reviewer/sandbox 组合、代表性 writer 文件写入路径、Session Query/Control 兼容和正式测试直接相关的
  源码、测试支持、fixture、app-server 行为文档、manifest，以及确有需要的 schema/snapshot/生成物。
  执行者可以复用职责契合的现有设施，或新建与现有架构契合的专用窄能力；本计划不预选 crate、文件、类型、函数、字段、持久格式、
  RPC 形状、错误枚举或测试数量。
- 现有 W0 test-only 原型与测试可以删除、保留或重构为生产测试输入，但不得把 `cfg(test)` 原型直接冒充产品实现，也不得保留已知
  可绕过的平行语义。
- 本计划的“当前状态”和“关键决策记录”，一份精炼实施日志，以及审查者形成的一份精炼独立审查日志。
- `doc/WBS.md`、`doc/WBS/durable-team-runtime.md`、`doc/WBS/multi-agent-trusted-evidence.md` 与
  `doc/WBS-COMPLETED.md`，仅用于在独立验收和最终整合阶段同步已形成的当前事实、完成历史与第四期终态。
- `/tmp`、测试自有 `TempDir` 或 089 worktree 内明确 ignored 的 task-owned 目录，用于临时 Git repository/worktree、fresh
  config/store/session、fake/offline service、调试输出和正式轮现场；对象须可精确归属本任务并按既有 fixture 生命周期回收。

### 允许只读核对

- 根与 `multidev/` 就近 `AGENTS.md`、README、当前 WBS/四期子 WBS、Plan 069/077/078/080/083/084/086/088 及相关已进入
  `main` 的日志、验收报告、Git 历史和 live code。
- 冻结 `codex-source-code/`、`codex-doc/` 与普通只读网络资料；只用于核对 Codex `v0.147.0` 行为和已采用窄适配，不修改快照、
  fetch/切换其中基线或把上游当前 main 当作 RONDO 基线。
- 其它 worktree 只查看 branch/HEAD/status、构建锁、资源占用和重型任务是否活跃等元数据；不得读取或依赖 087 未进入主线的成果。

### 不允许修改

- RONDO 创建、adopt、remove、prune、清理或管理调用者 worktree；ignored 文件、`.env.local`、模型、数据或 cache 的自动复制、同步、
  快照或恢复；workspace registry/manager、remote controller、多机同步或跨文件系统 worktree。
- structured handoff、产品级自动 Git merge/cherry-pick/push、共享文件所有权/冲突解决、workspace dashboard、replacement TUI、通用
  scheduler/自动路由、新 Team Role、第二套 writer authority、permission/reviewer、Session/Team 状态源或生命周期平台。
- 读取隔离、复杂鉴权、严格因果/取证、审计/可信/机器验收平台，或为未来可选增强预建通用 token/registry/cleanup 体系。
- `mydev/`、冻结上游基线、087 worktree 内的代码/计划/日志和任何未进入主线的 WBS 内容、`eval/`、`training/`、Plan 082/087 资产、
  真实用户 repository、其它任务 worktree/分支，以及与 W1/第四期收口无关的 README、历史 plan/log/audit snapshot 或无关重构。
- Docker、真实 API/模型、本地模型推理、训练、性能测评、云资源、上传、发布、CI/PR、产生费用或其它真实远端状态变更；唯一条件
  例外是本计划通过独立验收后，用户另行明确批准的 `origin/main` 最终推送。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/凭据、项目外个人文件或私有数据、Plan 082/087 保留资产正文、其它 worktree 的未提交文件内容，
  以及与本任务无关的 ignored 私有模型、训练或测评资产。

### Git-ignored 与主工作区边界

全部 tracked 编辑在
`/home/sjc/desktop/RONDO/.claude/worktrees/089-m4-w1-writer-workspace-binding/` 完成并提交。当前规划未发现必须直接写入
主工作区的 git-ignored 业务资产；临时 repository/worktree、store/session 和 fake service 应由 `/tmp`、`TempDir` 或 089 自有
task-owned ignored 目录承载。

预期的跨 worktree ignored 写入仅包括全局构建锁、089 自有 watchdog metrics，以及用户授权复用的
`/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target`。这些是构建/测试状态，
不是 tracked 产品修改。除这些位置和精确 Git 元数据外，不直接写主工作区或其它 worktree。若 live 实现证明必须新增其它
git-ignored、跨 worktree 或项目外写入，执行前通过指定队列报告准确路径、用途、预计体积、生命周期和清理责任并取得批示。

## 3. 硬约束

以下约束只冻结产品语义、原则性安全、资源和交付边界；不锁死内部实现路线。

1. **指定基线与并行隔离**：089 从 clean `main@f258ea5...` 创建。089 与 087 无产品前置，不读取、修改、合并或依赖 087 未进入
   主线的成果；两者对 WBS 的并行变化由后整合者基于最新 `main` 加法式保留，不预判或覆盖另一任务状态。
2. **Primary binding 不扩权**：调用者负责预先准备并授权 worktree，RONDO 只验证和绑定。binding 必须在 writer 首次模型/工具动作前
   建立，决定默认 cwd 和默认写入范围，但本身不授予新权限、不增加读取能力，也不形成 Team Role 或第二 writer authority。
3. **单一 Git/trust 结论与副作用前拒绝**：binding/reload/replacement 应消费 Plan 086 已进入主线的 hardened linked-worktree
   identity/trust 结论和当前 permission/sandbox，而不是另建宽松 resolver。任何必要验证失败都在 writer 可执行或产生副作用前
   fail-closed，不回退到父 cwd、repository root、`main`、默认 profile 或历史权限快照。
4. **写时有效性与全部代表路径**：不仅在 admission 时检查；每次实际写入仍必须由有效 primary binding 或有效 scoped authorization
   覆盖，并同时满足当前 permission/sandbox。执行者须 census 并统一约束所有代表 bound writer 的文件写入路径，不得只保护一个
   fake helper 或单一工具而留下已知绕过。已启动的长驻进程或 unified-exec session 在 binding 失效、replacement 或 terminal
   lifecycle 后也不得成为继续写入旧位置或绑定外路径的孤立通道。具体 race-safe 路径和进程处置策略由 live 架构决定，不要求建设
   通用文件系统事务平台。
5. **Scoped authorization 双门**：绑定外辅助写入必须具有明确目标和有限生命周期的 W1 授权，并通过现有 permission/sandbox；复用
   现有 reviewer、delegated auto-review 与 additional-permission 设施，不建设第二审批器。普通 `require_escalated` 或 sandbox
   escalation 只改变其既有 sandbox 决策，不等于解除 binding，也不能单独授权绑定外写入。
6. **Scoped 生命周期保守**：允许选择不跨恢复的最小生命周期；若支持跨恢复，持久事实只保存重建必要 identity/scope，恢复时必须经
   当前 config/trust/permission/sandbox 重验。拒绝、超时、失效、目标变化或权限不足均不得产生绑定外副作用；临时授权不静默恢复、
   不改变 primary binding、不随 replacement 迁移。
7. **Replacement 独立且事务式**：辅助写授权不能解释为换绑。replacement 先完整验证新 binding，再以单一明确成功边界替换旧值；
   确定失败保留旧 binding，确定成功启用新 binding。响应丢失或观察结果 unknown 时诚实返回 unknown，并从 canonical binding 事实
   查询收敛；不得自动重放、回退或伪称旧 binding 仍有效。成功后的 cold resume 重验新 binding，不自动处理旧 worktree 成果。
8. **Durable/S/C 共用既有权威**：binding 持久事实与恢复结果接入现有 Session/thread/Agent 生命周期和 canonical Query/Control 事实，
   不复制第三份 workspace 状态源。binding unavailable 不阻塞权威只读；lifecycle 失败不释放 Root authority，terminal 成功后不得留下
   mutation-capable orphan binding。顶层 fork/new/clear 与 child spawn 身份语义保持 M4-S2 合同。
9. **默认关闭与兼容**：W1 必须有连贯的 opt-in/activation 语义；关闭时 shared workspace、普通单 Agent 与现有 S/C 行为不变。
   功能开启但前置能力、持久后端、trust 或 permission 不可用时 fail-closed，不静默降级为 caller-relative writer。
10. **生产入口完整但不扩建 TUI**：initial binding、scoped authorization 的 request/grant/use 和 replacement 都必须可由正式产品
    生命周期调用和测试；本任务不要求状态 dashboard 或 replacement TUI。内部 API、wire/config 形状、持久格式和错误类型由执行者
    按 live code 选择，必要 schema/docs 使用既有生成器。
11. **允许调试、修复与重跑**：调试阶段保留已验证进度，从第一个未打通处继续窄修；普通代码、fixture、跨平台、编译、生成物、测试和
    审查 finding 可自主多轮修复与重跑，不设机械失败次数。不得删测试、弱化断言、放宽 binding/permission/lifecycle 不变量或改变
    PASS 口径凑绿；只有原则边界冲突、计划外高危动作、额外授权需求或合理整改后仍无法形成有效结果时才通过队列请示。
12. **正式轮后置冻结**：耗时全链先在调试现场逐段打通并保存进度，公共边界与正式配置不得过早冻结。全链完整稳定后才冻结候选，
    从全新 Session/store/repository/worktrees 运行一次最终正式轮；正式轮失败可针对 finding 修复并重开新 fresh 轮，不把窄修升级为
    新任务，也不拿被污染/续跑现场冒充正式结果。
13. **共享重型入口与唯一 target**：必要的聚焦、邻接、changed-crate、schema、fix/fmt/clippy、fresh 正式链、修复重跑和一次 canonical
    full workspace `just test` 已在本任务范围内一次授权，无需逐项重复请示。所有会读写 Rust target 的重型命令全局串行，只能经根
    `scripts/with-build-lock.sh` 或已接入它的 `multidev/justfile` 入口运行，并显式复用
    `/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target`；不得 direct Cargo、另建 target、
    提高并发上限、绕过 lock/watchdog，或与 Docker、真实本地模型、其它重型 Cargo 同时运行。
14. **项目容量临时门限**：重型命令只通过命令级环境设置
    `RONDO_BUILD_PROJECT_WARN_BYTES=270000000000`、`RONDO_BUILD_PROJECT_STOP_BYTES=285000000000`、
    `RONDO_BUILD_PROJECT_MAX_BYTES=290000000000`；不修改脚本或长期默认。用户提供的规划快照为项目约 `271711268437 B`、069 target
    约 `213344277173 B`、target `debug/incremental` 约 `59014792108 B`；执行时以 watchdog/preflight 实测为准。
15. **Windows C: 本任务例外**：初始仍使用默认 `50,000,000,000 B` 门禁。若实际首次触发 50GB 停止，先确认没有 active build，并按
    第 16 条完成允许的空间处理；因 WSL 虚拟磁盘通常不会自动归还 Windows 空间，此后只要 Windows `C:` 实际余量仍大于
    `35,000,000,000 B`，可在命令级设置 `RONDO_BUILD_WINDOWS_C_FREE_STOP_BYTES=35000000000` 继续本任务，不修改长期默认。
    必须持续观察真实趋势；若余量达到或低于 35GB，或触发 50GB 后仍快速下降、明显趋向 35GB，立即停止会继续大幅膨胀的重型行为。
    WSL 文件系统虚拟余量不能替代 Windows `C:` 实际计数。
16. **资源不足只清精确 incremental**：preflight/watchdog 证明空间不足时，只有确认无 active build、无构建持锁者，并精确验证路径归属
    后，才可清理 069 target 的 `debug/incremental/`，记录清理前后体积并自主重跑。不得删除整个 target、`debug/deps`、release 工件、
    其它 cache、087/训练资产或来源不明文件；允许清理后仍不足时停止重型批次，不扩大删除范围。
17. **与 087 的资源互斥**：087 远端 GPU compute 可与 089 本地 Cargo 并行；087 大型上传/下载、任何本地模型或 Docker 活动不得与
    089 重型 Cargo 同时进行。执行者在每个重型批次前核对共享锁和相关活动；不读取或操作 087 工件。
18. **证据分类与外部禁区**：测试、deterministic/fake/offline、真实本地系统 Git 和真实 app-server OS process 证据清楚分类。
    不调用真实 API/模型、不训练、不运行 Docker、不做性能测评、不操作云资源、不发布/上传/付费。除独立验收后用户另行明确批准的
    `origin/main` 最终推送外，不推送远端。不得打开、搜索、打印、
    复制或记录 `.env.local` 内容；skip、未运行、历史失败和基础设施阻断不得表述为通过。
19. **审查、提交与文档顺序**：执行者完成实现、最终正式轮、自审、计划状态和精炼实施日志后提交 089 分支，再使用下述队列通知审查者；
    每条消息主动表明“Plan 089 执行者”身份。finding 在同一范围内整改、复验、提交后再次通知。独立审查接受后只记录待整合状态；
    未经用户明确批准，不合并、不推送、不删除 worktree、不归档分支，也不把 WBS/COMPLETED 写成最终 PASS/第四期完成。
20. **最终整合仍属本任务但等待用户批准**：用户批准后，整合者消费届时最新 clean `main`，加法式保留 087 或其它已进入主线的 WBS
    状态，完成合并树必要轻量/聚焦门禁、最终文档和推送；不重复已稳定的重型正式矩阵，除非合并实质改变 W1 链。推送成功且本地/远端
    main 一致后，才接受 `M4_W1_PASS / PHASE_4_COMPLETE` 并按仓库规则归档完成分支。

### 审查者跨会话队列（以下逐字照录用户追加要求，执行者必须原样遵循）

联系审查者，需要照如下的指定方法，使用 Codex 的跨会话队列，不要通过文件、终端输出或人工提醒传递消息。执行：
 codex queue --thread UUID --message 'XXX'
其中UUID用审查者的会话的UUID：01a03ed3-ec2f-7730-8d0e-9c83797ce438 替换。
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

执行者给审查者发送每一条消息时，`XXX` 的首句都必须是“我是 Plan 089 / M4-W1 执行者。”。普通请示或整改内容紧随其后；最终完成
通知则在该身份句之后原样放入上面指定的固定通知文字，并把原本 TUI 完成汇报原样嵌入 `<执行者的完成汇报>`。身份句之外的固定通知
文字和占位符填充规则不得改写。

## 4. 软性建议

以下建议基于 `f258ea5` 当前接缝，只用于帮助执行者高效收敛，不固定内部 API、数据布局、错误表达或测试拆分。执行者可以选择更优雅、
更干净且与现有架构契合的等强策略，并在关键决策中简要记录有实质影响的偏离。

- 先做 live seam census，再确定所有权。W0 的 `AgentControl` 邻接 test-only 原型可作为行为参考，但生产能力应放在职责自然的位置；
  如果把新概念继续塞进已膨胀的 `codex-core` 会造成耦合，可以新建专用模块或 crate，并沿用现有 config、error、lifecycle、test 和
  observability 方式。
- Git identity/trust 优先消费 Plan 086 的 hardened resolver；权限恢复优先消费 Plan 088 的 profile identity/current re-resolution；
  Durable identity、resume/member reload 与 terminal lifecycle 优先消费 S1/S2 的现有接缝。不要复制这些已验收体系。
- Scoped authorization 可优先评估现有 `additional_permissions`、`request_permissions`、file-change `grantRoot`、reviewer 和 delegated
  auto-review 链是否能承载 W1 的“双门”语义。若强行复用会把 sandbox escalation 与 binding authority 混为一谈，可以增加一个职责
  清楚的窄 binding authorization 层，但仍由现有 reviewer/permission 产生实际批准并由现有 sandbox 执行底层限制。
- 对 shell/unified exec、apply_patch、MCP/extension 等可能代表 writer 写文件的路径先做完整 census，再寻找尽可能靠近公共执行上下文
  的单一约束点；测试采用少量代表路径加绕过反例，不必复制工具 × 生命周期 × 失败类型的全笛卡尔矩阵。
- 普通 cwd/environment/settings 更新不能被误当作 replacement；现有 turn/session permission grant 若只按 environment 标识，换绑时需防止
  旧辅助授权被误带到新 binding。RONDO 自身 rollout、Team artifact、store、cache/config 写入不是 writer 产物，不应被误套 primary
  binding 而破坏 Durable/Query/Control。
- Binding 持久事实应靠近已有 Session/thread durable identity 与生命周期，不塞进 Team State 形成第二份 workspace 真相。Query/Control
  可以投影必要 availability/result，但不要求本包做 dashboard；replacement 的核心生产动作可通过最契合现有产品的正式入口提供。
- race-safe 文件写边界以“目标副作用发生时仍属于有效 binding/authorization”为可观察合同。可复用现有 sandbox/path 设施或增加专用
  小能力；不预设必须使用某一种平台原语，也不要求把整个文件系统封装成事务层。
- 测试建议分层：binding/trust/path/authorization 领域测试；core Agent/Session reload/replacement；app-server 公共入口和真实进程；
  S/C lifecycle 邻接；唯一 Critic 组合回归；最终 fresh 全链。让每层拥有最接近职责的断言，避免同一重型场景重复多次。
- 复用 Plan 083 的 real-process fresh store 全链基础设施通常比另建 runner 更合适；如现有 fixture 无法自然承载 two-linked-worktree 和
  scoped authorization，可以在同一测试体系内扩展专用 helper，而不是建设独立验收平台。
- 独立审查可重点检查：admission/first-action 顺序、各实际写路径、symlink/identity/time-of-check 变化、scoped 双门与普通 escalation、
  reload/replacement/terminal cleanup、S/C authority 和关闭态。保存的 JUnit/watchdog 与精确 finding 整改证据有效时，不必机械重跑
  已通过的重型矩阵。
- 可以使用少量子智能体并行调查互不重叠的 trust/path、permission/reviewer、durable lifecycle 或测试接缝，并由单一集成者统一写共享
  代码；不建立评审委员会或复杂审计流程。

### 建议的阶段编排与退出条件

**A. 生产合同与 live 接缝冻结**

- 核对 W0、086、088、S2、S/C 和当前代码，完成 binding owner、持久接缝、所有代表写路径、现有 permission/reviewer 组合及测试入口
  census；只冻结可观察产品合同，不预冻内部字段/API。
- 退出条件：实际消费点、共享写集、feature-off 路径、临时 Git/资源现场和最小验证层次清楚，没有依赖 087 未入主线成果。

**B. Primary binding 生产化**

- 建立正式产品入口、持久事实和激活/首次动作门；闭合默认 cwd/write scope、双 writer 隔离、Git/trust/permission/sandbox 验证、写时
  路径有效性与失效隔离。
- 退出条件：代表写路径的正反领域/集成测试通过，任一 binding 失败不影响另一 writer 或 Team/root 权威只读。

**C. Scoped authorization 与 replacement**

- 在现有 reviewer/permission 体系上闭合有界辅助写入，证明普通 escalation 不绕过；实现显式事务式 replacement 和授权不迁移。
- 退出条件：批准/拒绝/超时/失效/权限不足/目标变化无越界副作用，replacement 成功/失败与 primary 不变式有直接证据。

**D. Durable lifecycle、S/C 与跨期组合**

- 接入 persistence、reload/member reload/cold resume/real process replacement，覆盖 fork/new/clear/spawn、Query/Control、close/archive/
  unarchive/delete/owner replacement、terminal cleanup 与关闭态；把唯一 fake/offline Critic 组合回归纳入 binding。
- 退出条件：binding 状态只消费 canonical Session/lifecycle 事实，S/C authority 未旁路，组合回归没有真实模型/API。

**E. 聚焦门禁与调试全链**

- 按实际写集运行生成器、聚焦/邻接/changed-crate、scoped fix/clippy/fmt；用 task-owned fresh 现场从首个未打通处边修边跑，保留有效
  进度。资源不足按硬约束收窄、清理唯一允许的 incremental 或停止重型增长。
- 退出条件：全链已经完整打通，未关闭 correctness finding 为零，候选代码/配置可以冻结；未运行和设施停止诚实归因。

**F. fresh 正式轮、full workspace 尝试与独立终审**

- 从全新现场运行一次真实旧/新 app-server OS 进程正式链；资源门允许时尝试一次 canonical full workspace `just test`，只关闭 W1
  相关新失败。执行者自审、日志、提交后按队列请求审查，普通 finding 在同一任务内整改和相称复验。
- 退出条件：正式证据对应最终代码，无未关闭高/中 finding，089 worktree clean；文档只记录 accepted/pending integration，不提前 PASS。

**G. 用户批准后的主线整合与第四期关闭**

- 等待用户明确批准 merge/push；基于届时最新 `main` 加法吸收并行状态，完成必要合并树验证、最终 WBS/COMPLETED 收口、合并、推送和
  完成分支归档。
- 退出条件：local `main == origin/main` 且包含最终验收成果，权威文档为 `M4_W1_PASS / PHASE_4_COMPLETE`，不存在必需后置工作包。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 根 `AGENTS.md`、`multidev/AGENTS.md`、README、顶层/四期/方向 3 WBS、计划模板及 W0、086、088、S2、C2、Z(core) 计划与验收
  证据已完成只读核对。
- 规划时 `main == origin/main == f258ea5b3ad7ef7799a671b39e91afdca38523f3`，主工作区 clean；Plan 086/088 已进入该基线并分别取得
  `M4_W_39616_ADAPTATION_PASS`、`M4_W_39153_ADAPTATION_PASS`。
- 089 专用 worktree 已从该 clean main 创建：
  `/home/sjc/desktop/RONDO/.claude/worktrees/089-m4-w1-writer-workspace-binding`，分支为
  `worktree-089-m4-w1-writer-workspace-binding`。
- Plan 087 在独立 worktree，未进入 089 基线；089 不消费其成果，最终 WBS 冲突由后整合者加法处理。
- W0=`BINDING_ONLY_GO`、M4-S2=`M4_S2_PASS`、M4-C1=`M4_C1_QUERY_PASS`、M4-C2=`M4_C2_CONTROL_PASS`、
  M4-Z(core)=`M4_Z_CORE_PASS` 均已进入当前主线，可作为兼容前置而不返工其权威体系。
- 已完成 live seam census 与生产实现：caller-prepared exact local linked worktree binding 成为单一执行投影；初始 admission、写前重验、
  durable exact resume、显式 generation replacement、nested writer、现有 permission/reviewer 上的 turn-only W1 双门以及 app-server
  `writerWorkspaceBinding/read|replace` 均已接入。W0 test-only 平行原型已删除。
- 已完成 stable/experimental schema 生成和 changed-crate `1008/1008`、相邻回归、Critic process `7/7`、scoped clippy、fmt/diff 门禁。
  最终 fresh 真实 app-server 进程替换全链 `1/1` 通过；canonical full workspace `just test` 已按约尝试一次，但在测试前被
  rusty-v8 v150.4.0 默认 prebuilt archive URL 的 HTTP 404 阻断，未冒充通过。
- 首轮独立审查报告 `agent_log/2026-08-26-130318-plan089-m4-w1-independent-review.md` 提出的 F1–F7 已在同一工作树逐项整改：bound
  writer 禁止无 sandbox 的 `/shell` 与 stdio MCP；turn terminal/replacement/invalidation 以保留失败句柄的 confirmed barrier 撤销
  unified-exec；binding identity 使用 strict append/materialize/flush；turn admission 与 replacement 共用串行边界并核对 captured
  generation；child lazy reload 以自身 persisted roots 与当前 authority 交集恢复；W1 target 在 review 前 canonicalize、review 后及
  tool side effect 前重验；唯一 offline Critic 组合链断言一次实际调用及完整 packet。
- 整改代码与正式配置已再次冻结。聚焦 core/protocol/thread-store 回归、bound `/shell` 真实入口、scoped core clippy、fmt/diff 均通过；
  最终 fresh 真实 app-server OS 进程替换 + deterministic offline Critic 正式链 `1/1` 通过。当前没有执行者已知未关闭的 W1 高/中等级
  correctness finding；完整证据与资源事件见 Plan 089 实施日志。
- 第二轮独立复验报告 `agent_log/2026-08-26-140509-plan089-m4-w1-remediation-review.md` 的四项窄 finding 已关闭：local PTY confirmed
  terminate 会传播 kill 错误并保留可重试 handle；Forked current settings 使用 strict append/materialize/flush 且 `binding=None` 是冷恢复
  tombstone；bound active turn 拒绝 authority/profile 变化，idle 变化推进 runtime authority revision 使旧 context 失效；durable close 在关闭
  canonical persistence 前完成 bound process confirmed quiescence，失败时保留 persistence 与 Root authority。
- 上述四组聚焦回归及 app-server tombstone 邻接测试均通过，`codex-core + codex-protocol` scoped clippy 无 warning，fmt/diff 通过。最终
  fresh app-server OS 正式链 `1/1` 通过并断言 offline Critic 恰好一次调用；watchdog 为 `stop=none / cleanup=none`。验证全程未触发
  Windows 50GB 门、项目主动停止或 35GB 临时例外，也未进行额外清理。
- 第三轮独立复验报告 `agent_log/2026-08-26-151617-plan089-m4-w1-final-remediation-review.md` 唯一 finding 已关闭：durable close 的
  pre-persistence quiescence 使用 shutdown-specific task abort，禁止 trigger-turn/durable-sleep pending work 自动重启；单一窄
  task-admission gate 从 idle reservation 保持到 task install，并与 terminal teardown 串行。close 持有 gate 到 runtime teardown 完成，
  同时复用既有 shutdown-in-progress marker 拒绝终态后的新 admission；失败路径仍按既有规则恢复 marker 与 admission。
- shutdown + pending-work 聚焦回归 `1/1`、`codex-core` scoped clippy、fmt/diff 及 exact app-server build 均通过。冻结代码的 fresh
  app-server OS + unique offline Critic 正式链 `1/1` 通过（JUnit SHA-256
  `7ff58d6e6971654c1e6ad374698bfbd4534c364cee95f377596e90e00b8fdcef`），`stop=none / cleanup=none`；未触发项目/Windows stop、
  35GB 临时例外或任何额外清理。
- 第四轮独立复验报告 `agent_log/2026-08-26-154016-plan089-m4-w1-lifecycle-remediation-review.md` 唯一 finding 已关闭：no-restart
  quiescence 后、不可逆 persistence 成功边界前的失败回滚，会先释放 admission fence、再撤销 shutdown marker，随后用现有
  pending-work 入口恢复 trigger-turn/durable-sleep 唤醒。成功关闭、persistence 成功边界和 task admission 主流程未改变。
- late revoke fault + 既有成功关闭聚焦回归 `2/2`、`codex-core` scoped clippy、fmt/diff 均通过。测试 fixture 使用临时真实 linked
  worktree、managed authority 和 production binding revalidation，并断言 active task 确实安装。按审查决定沿用已接受的 fresh 正式链，
  不重复运行。默认 Windows 50GB 门实际触发并在 Cargo 前停止后，仅对剩余聚焦命令启用已授权的 35GB 临时门；最终余量约
  `49.97GB`，未清理任何文件、未触发项目 stop 或快速趋近 35GB。

### 当前工作

- 完成失败回滚窄整改提交，并按指定 queue 请求独立复验。

### 本任务剩余步骤

- 请求独立复验；若仍有范围内 finding，在同一 089 worktree 整改、相称复验并补充提交。
- 独立验收接受后保持 clean 089 worktree，记录 `ACCEPTED / PENDING_INTEGRATION`，并等待用户明确批准 merge/push。
- 获批后按 G 完成最新主线整合、文档最终收口、推送和完成分支归档，形成唯一 `M4_W1_PASS / PHASE_4_COMPLETE`。

### 阻塞项

- 当前无产品实现阻塞；canonical full workspace 的 V8 404 是已保存的基础设施阻断，不影响已通过的 W1 分层与正式全链证据。
- 最终 merge/push 尚未授权；这不阻塞工作树实现与独立审查，但阻止提前宣告最终 PASS。

### 当前验收状态

- `FAILURE_ROLLBACK_REMEDIATION_COMPLETE / FOCUSED_REGRESSION_PASS / REVIEW_PENDING / INTEGRATION_NOT_AUTHORIZED /
  M4_W1_PASS_NOT_YET_ESTABLISHED`。

### 交接边界

- 本任务完成后冻结本计划；PASS 后只可由 WBS 保留 binding 状态展示、replacement TUI 等非必需可选增强，不在本计划维护后续路线。
- 若任务不能达到唯一成功结论，必须明确记录具体未完成项和实际状态，不制造 M4-W2 或无编号补丁包掩盖缺口。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | W0 之后将 W1 明确委任为第四期最后一个必需工作包 | 用户本次明确要求；W0 已证明 binding-only 价值 | Plan 089、四期收口 | 已采纳 |
| 002 | Writer binding 是写入能力，不是 Team Role；不新增 structured handoff | 保持 canonical Team/Session authority，服从 `BINDING_ONLY_GO` | 产品模型、协议、测试 | 已采纳 |
| 003 | Scoped authorization 可选择最小不跨恢复生命周期；跨恢复仅在显式持久和当前重验成立时允许 | 满足核心价值，同时避免无必要持久化与第二套权限体系 | permission/reviewer、恢复 | 已采纳 |
| 004 | Core binding/replacement 生产入口属于 W1 必需范围，状态 dashboard/replacement TUI 不属于 | 防止把核心操作入口假装成未来可选项，同时控制任务边界 | app-server/core/TUI | 已采纳 |
| 005 | 最终 PASS 必须等待用户批准后进入并推送 main | 用户要求工作树只自觉提交，merge/push 单独批准；最终出口又要求 integrated/pushed | Git、文档、结论 | 已采纳 |
| 006 | 首次 50GB C: 停止后允许命令级 35GB 临时底线，但快速趋近 35GB 时立即停止增长 | 用户针对当前 56GB 紧张空间的明确例外；不修改长期默认 | 重型构建/测试 | 已采纳 |
| 007 | 执行者与本会话审查者只通过指定 Codex queue 沟通，并主动表明身份 | 用户指定跨会话审查与批示流程 | 请示、终审、整改 | 已采纳 |
| 008 | 复用 hardened trust、permission/reviewer 与 Session/thread persistence，但新建单一窄 writer binding owner | 现有设施分别拥有 trust、权限与生命周期职责，强行让其中任一兼任 binding 会扭曲语义 | core、protocol、app-server | 已采纳 |
| 009 | W1 绑定外授权只保留 active turn/environment/generation，底层普通 grant 即使为 Session scope 也不能替代 W1 双门 | 满足有界辅助写入并避免新增持久授权体系；resume/replacement 自动失效 | permission、turn state | 已采纳 |
| 010 | durable binding 只持久化 identity 与当前重验所需 authority roots；冷读统一显示 unavailable，恢复后用当前 profile/trust/roots 重验 | 不持久化 concrete permission snapshot，不复制第三份 workspace authority | persistence、resume、query | 已采纳 |
| 011 | bound writer 对无实际文件系统约束的 `/shell` 和 stdio MCP fail closed；HTTP MCP 保留现有只读声明门 | 两条宿主进程路径不能承载 binding sandbox，禁用比另建平行执行器更窄且不影响 W-off | shell、MCP runtime | 已采纳 |
| 012 | bound writer 在 turn terminal、replacement、invalidation 与 shutdown 使用 confirmed unified-exec 撤销屏障，失败句柄保留以便重试 | turn-only W1 不能被长驻进程带过生命周期，部分失败也不能伪报清理完成 | turn/session lifecycle、unified-exec | 已采纳 |
| 013 | bound active turn 拒绝 authority-relevant settings 变化；idle 变化推进 runtime-only authority revision | 旧 OS sandbox 与 TurnContext 不能在权限收窄后继续代表当前 writer，同时无需持久化或建设第二套 authority | settings、turn admission | 已采纳 |
| 014 | durable close 在 canonical persistence shutdown 前 confirmed quiesce bound process，并在 abort 后复验 late insertion | revoke 失败必须保留可持久 mutation 的 Root runtime，成功后才跨不可逆关闭边界 | Session Control、durable close | 已采纳 |
| 015 | durable close 使用 shutdown-specific task abort，并以单一 admission gate 串行 task install 与 terminal teardown | 普通 Interrupted abort 会自动启动 pending work；关闭必须阻止重启并覆盖 reserve 到 install 的竞态，同时复用既有 shutdown marker | Session task admission、durable close | 已采纳 |
| 016 | no-restart quiescence 在 persistence 成功前失败时，按 fence、marker、现有 pending-work 入口的顺序恢复 | 保留的 Root/runtime 必须继续消费 close 前已排队工作；复用现有 admission 可避免新增调度或生命周期权威 | durable close 失败回滚 | 已采纳 |
