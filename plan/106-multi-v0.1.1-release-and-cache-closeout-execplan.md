# Plan 106：RONDO Multi 0.1.1 发布与缓存收尾 ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

对应 WBS：`doc/WBS.md` 的“发布工程”与“产品线配套补齐与逐条收口”阶段一收尾。
规划基线：`main@12a20ca56ca15fc559ba0ba62acf514e33a7a37a`；Plan 105 最终全 workspace 为
`14713/14713` passed、零 failure/error/timeout/retry，已独立验收、合入推送且轻量 CI 全绿，Multi 实质代码与功能冻结。

## 1. 目标

### 最终目标

沿用 Plan 103 已实跑的双产品发布能力，正式发布并公开复验 `multi-v0.1.1`。确认发布物可用后，再对主物理仓库唯一的
Multi Cargo target 做只读盘点并停在明确删除授权门；只有用户随后逐字批准该精确对象，才释放它并完成 Multi 阶段记录，
把 WBS 的下一工作包切换到 Local 配套补齐。

### 完成/验收标准

#### 第一阶段：发布与公开复验

- `multidev/CHANGELOG.md` 顶部有 `0.1.1` 小节，准确概括相对 `multi-v0.1.0` 的配套补齐和测试稳定性收口；
  不把测试通过数字写成性能、质量资格或生产承诺。打 tag 前用既有脚本渲染并审读正式 Release notes。
- 发布准备内容先形成工作树提交；在用户执行提示明确授权后合入并推送 `main`。必须按 workflow 和 exact commit 找到
  该提交对应的根轻量 CI，等待其真实成功后才能打 tag；无运行、运行中、skip 或其它提交的绿色记录均不算通过。
- 创建并推送 annotated tag `multi-v0.1.1`，tag 的 peeled commit 是上述包含对应 CHANGELOG 的已验候选。
  tag 推送后不可移动、覆盖、删除或重建；`multi-v0.1.0` 的 tag、Release 和资产保持原样。
- tag 触发的既有 `release` workflow 中 validate、build、verify、publish 四个 job 全部成功，公开 Release 为非 draft、
  非 prerelease，并包含预期的 `rondo-multi-0.1.1-x86_64-unknown-linux-musl.tar.gz` 与 `SHA256SUMS`。
- 从项目目录外的 task-owned 临时目录，以未认证访问重新取得公开 Release 元数据和两个资产；公开 `SHA256SUMS` 对下载归档
  校验通过。不得只复用 Actions artifact、本机旧包、登录态 `gh` 输出或 workflow 的成功结论代替公开下载复验。
- 对实际下载归档复验：归档根与入口属于 `rondo-multi`；`bin/rondo-multi` 可执行且 `--version` 仍报告冻结上游版本
  `0.147.0`；完整包布局、产品身份、根 LICENSE/NOTICE、流水线要求的第三方许可闭包及 Multi 专属 Release notes 均正确，
  不夹带 Local 产品说明，也不把 Publication Critic 写成发布门或已获质量资格。
- 只有公开 Release 与资产复验全部通过后，才把 README 中 Multi 的固定下载、解压和入口路径切换到 `multi-v0.1.1`；
  Local 固定链接与历史版本不变。同步当前 WBS、完成记录、计划动态状态和一份精炼实施日志，提交并在已授权范围内合入、推送。
- 发布准备及发布后 tracked 差异不含 Multi 实质代码、功能、测试语义、依赖、lockfile、发布 workflow 或许可材料变化；
  因而 Plan 105 的最终全 workspace 结果继续适用于发布候选，不重跑本地全 workspace。

#### 第二阶段：只读缓存盘点与强制暂停

- 发布和公开复验完成后，重新测量
  `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi` 的实时占用；确认路径不是符号链接、边界解析准确，
  并以可用的共享构建锁、Cargo/Rust/Nextest 进程和打开句柄检查确认没有任务正在使用它。
- 给出只针对该精确路径的删除方案，记录预计释放空间、日后重建代价、对 Local 阶段的影响，以及删除 WSL 文件后
  Windows `C:` 实际可用空间可能不会同步增长这一事实；同时说明 Local target、retained test evidence 和其它资产不在范围内。
- 将任务状态记为 `RELEASE_VERIFIED / AWAITING_CACHE_DELETION_AUTHORIZATION` 并暂停。第一阶段授权、发布成功、
  WBS 排程或本计划文字都不构成删除授权。

#### 用户二次授权后的最终收口

- 只有用户随后明确批准删除
  `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi`
  这一精确对象后，才可继续；批准不得解释为允许清理其父目录、Local target、其它缓存、Docker 对象、测试证据或 worktree。
- 删除前复核并记录占用、非符号链接、无使用者和精确 canonical path；删除后确认该路径不存在，复测项目与宿主可用空间，
  并确认 `.codex/cargo-target/rondo-local`、retained test evidence、其它项目文件和已发布版本未受影响。
- tracked 收尾只更新本计划动态状态、当前 WBS、`doc/WBS-COMPLETED.md` 和同一份必要日志；主工作区与执行工作树最终 clean，
  Multi 阶段标记完整收口，WBS 的下一工作包正式转为 Local 配套补齐。计划制定者完成独立复核后才记最终接受。

## 2. 范围

### 允许修改

- `multidev/CHANGELOG.md`：新增 `0.1.1` 变更记录，不改旧版历史内容。
- 根 `README.md`：只在公开复验通过后更新 Multi 的固定 tag 下载、解压与入口路径。
- `doc/WBS.md`、`doc/WBS-COMPLETED.md`、本 ExecPlan 的动态状态及一份精炼 `agent_log/`：只记录本任务当前状态、
  已完成事实、发布证据、删除门和最终交接；必要时可窄修与本任务直接相关且不改变发布语义的维护文档错误。
- 专用工作树内上述 tracked 编辑；项目目录外 task-owned 临时下载目录及其中本任务创建的公开 Release 复验副本。
- 用户执行提示明确授权后的本地 Git 提交/合并、`main` 推送、annotated tag 创建与推送、GitHub Actions 监控与安全重跑、
  正式 GitHub Release 发布和只读公开复验。
- 获得用户第二阶段精确删除授权后，仅删除下方“Git-ignored 与主物理工作区边界”列出的唯一 Multi target，并完成记录。

### 不允许修改

- `multidev/` 内除 CHANGELOG 外的产品代码、测试、fixture、snapshot、配置、依赖与 lockfile；Multi 功能、默认值、
  Publication Critic 资格结论和冻结上游基线。
- `.github/workflows/release.yml`、`.github/licenses/`、许可收集/Release notes 脚本、打包器或任何发布语义。
  若现有流水线或许可材料本身必须修改才能通过，本任务越界，必须暂停汇报。
- `mydev/` 的 Local 产品文件与语义、Local 固定下载链接，以及 WBS 规定的下一阶段实际实现。
- 已推送 tag 或已创建 Release 的移动、覆盖、删除、重建和资产替换；`multi-v0.1.0` 及其它历史 tag/Release 的任何变更。
- 未获第二阶段精确授权时的任何删除；获批后也不得扩大到 `.codex/cargo-target/rondo-local`、retained test evidence、
  其它缓存/target、Docker 对象、worktree、来源不明资产或父目录。
- 本地全 workspace 重跑、Docker、真实 API/模型、GPU/RunPod、训练、付费服务、上游升级、批量测评、项目数据上传或其它外部状态。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/API Key、真实私有配置、项目外个人文件或私有数据。
- 冻结 qualification/unseen 测试正文、模型权重、其它 worktree 的未提交 diff 或 ignored 资产正文。

### Git-ignored 与主物理工作区边界

所有 tracked 编辑在
`/home/sjc/desktop/RONDO/.claude/worktrees/109-multi-v0.1.1-release-closeout/` 完成。
唯一因 gitignore 和共享构建路径而必须直接针对主物理仓库处理的对象是：

- `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi`：发布后只读盘点对象；用户第二阶段明确授权前绝不删除。
  获批后的删除也只能命中这个完整路径。

公开 Release 下载放在项目外 task-owned 临时目录，不写入仓库或 retained test evidence；只把 URL、资产名、大小、摘要和复验结论
精炼记录到 tracked 日志。合并 `main` 与 Git ref 操作属于已授权 Git 流程，不是 ignored 文件编辑；除此之外若意外需要写入其它
主工作区 ignored 路径，先报告准确路径、用途、预计体积和清理责任并取得授权。

## 3. 硬约束

以下约束只固定发布候选、外部状态、二次删除门、诚实验收与 Git 停止点，不固定普通只读核验命令、文档组织细节或小故障诊断路线。

1. **两段授权严格分离**：用户给执行者的初始提示可一次授权第一阶段全部 Git/GitHub 外部动作、公开下载复验、只读缓存盘点，
   以及二次删除获批后的最终文档合并推送；它绝不授权删除缓存。执行者必须在规定状态停下，等待用户对精确路径另行批准。
2. **冻结候选不扩围**：本任务只做发布版本说明、发布、复验和记录。若发现必须修改 Multi 代码、测试口径、依赖、workflow、
   打包器或许可材料，现有候选与 Plan 105 证据不能直接沿用，停止发布或收尾并请用户决定，不用窄修名义越界。
3. **正式 tag 不可变**：推送前确认 tag 不存在、候选 commit 与 CHANGELOG 正确；推送后无论 workflow 进行到哪一步都不得移动、
   覆盖或删除 `multi-v0.1.1`。本任务不创建额外 RC。已创建的 Release 也不得为美化运行记录而删建。
4. **CI 和 release 绑定精确身份**：打 tag 前的 CI 必须绑定候选 exact SHA；发布 workflow 必须绑定正式 tag。不得把其它 commit、
   其它 workflow、历史 run、Actions artifact 或 0.1.0 结果替代本次门禁。
5. **失败可自主收敛但不得改策略**：网络抖动、runner 瞬态、下载超时等非代码问题，可以先对账远端状态后在原 commit 或原 tag 上
   安全重跑失败 job；CHANGELOG、README、WBS、计划和日志的非实质错误可在不移动 tag 的前提下窄修、提交。不得在已存在 Release 时
   盲目重跑非幂等 publish，也不得通过改 workflow、换产物、删建 Release、弱化校验或改冻结候选解决失败；需要这些动作时暂停汇报。
6. **公开复验独立于登录态**：至少一次 Release 元数据与资产取得使用未认证 HTTP 访问；SHA256 对真实下载字节计算，包内入口、
   身份、许可和 notes 对解压后的公开归档检查。任何 skip、未下载、只看网页或只信流水线绿色都不能记为发布复验通过。
7. **README 后置**：README 在公开资产确认可用前继续指向 0.1.0。切换后链接必须是 Multi 自己的固定 tag，不能使用仓库级 `latest`，
   也不能改动 Local 链接。
8. **不重复重型验证**：发布 workflow 自身完成构建与干净 runner verify；本任务不运行本地全 workspace，不新建 Cargo target，
   不加热或写入现有 Multi target。只要 tracked 差异保持在本计划范围，Plan 105 最终结果继续有效。
9. **缓存删除 fail-closed**：路径、非符号链接、占用或使用者状态任一不能可靠确认，就不删除并如实报告；获批后先精确解析目标，
   不使用未解析变量、glob、父目录或广义 prune 扩大命中范围。删除是可重建缓存释放，不得描述为 Windows 虚拟磁盘必然缩容。
10. **文档职责不重叠**：WBS 只写当前阶段、授权门和下一工作包；WBS-COMPLETED 只写完成进展；Plan 动态段记录任务恢复状态；
    agent log 记录发布、复验和删除证据。无需新建 manifest、数据库、签名链、可信/审计/因果设施，也不保留二进制副本。
11. **工作树、Git 与审查停止点**：未知修改全部保留。tracked 编辑只在 109 工作树完成并形成清楚提交；合并和推送只依赖用户
    给执行者的明确执行授权。任务不得归档/释放工作树或重命名分支。第一阶段与只读盘点完成后必须 clean 停在二次授权门，
    最终删除与记录完成后再次 clean 交给计划制定者独立验收。

## 4. 软性建议

以下内容用于帮助执行者收敛，不是固定路线。执行者可以依据 live Git/GitHub 状态采用更优、更干净的做法，但不得越过上节边界。

- 写 CHANGELOG 前可从 `git diff/log multi-v0.1.0..HEAD` 提炼用户可理解的变化：Multi `/status` 的 Guardian override
  配置摘要与根配置指南、轻量 CI 对 `codex-team-state` 的持续覆盖，以及 fuzzy-file-search app-server 启动争用的既有
  Nextest 串行化。可记录最终全 workspace 已提升到 `14713/14713` 且零 retry，但应清楚说明这是正确性与稳定性收口，
  没有新增质量资格、性能承诺或默认开启能力。
- tag 前复用 `.github/scripts/compose-release-notes.sh` 做无构建渲染；同时复核 `multi-v0.1.1` 尚不存在、旧版 tag peeled SHA
  与 Release 未变、候选相对 Plan 105 冻结点只有允许的非实质发布准备差异。
- CI/Release run 可能稍晚才出现在列表中，可以轮询 exact SHA/tag 并等待最终结论。瞬态重跑前先查看失败 job 和 Release 是否已创建，
  让处置与实际远端状态匹配，而不是机械重跑。
- 公开复验可用临时目录完成，并在日志保留 Release URL、tag peeled SHA、run ID/URL、资产名与大小、归档 SHA-256、入口/版本、
  许可与 notes 结论。现有 workflow 已有完整校验，任务只需做独立且够用的外部复核，不复建第二套发布审计。
- 缓存盘点可组合 `du`、共享 build lock 状态、进程命令行和可用的 open-handle 工具。工具缺失时不必安装大型设施；但不能仅凭
  单一模糊进程名就宣称目标空闲。删除前后可同时记录项目占用与 Windows `C:` 实测余量，诚实解释二者可能不同步。
- 第一阶段收尾时，WBS 宜明确写“Release 已公开复验、等待精确缓存删除授权”；最终删除后再把当前指针切到 Local 配套补齐。
  WBS-COMPLETED 可记录已完成的发布里程碑，并在最终收口时补全同一 Plan 的缓存结果，避免重复堆叠执行流水账。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-09-02：核对主工作区 clean，`main` 与 `origin/main` 同为
  `12a20ca56ca15fc559ba0ba62acf514e33a7a37a`，进入时无遗留 linked worktree。
- 2026-09-02：阅读根/`multidev` 规则、README、当前 WBS、计划模板、Plan 103/104/105、CD 操作手册、当前 release workflow、
  Multi CHANGELOG 及相关实施/验收记录；确认现有发布设施足以直接承接 0.1.1，无需新建发布或验证体系。
- 2026-09-02：从上述基线建立专用工作树
  `.claude/worktrees/109-multi-v0.1.1-release-closeout` 与分支 `worktree-109-multi-v0.1.1-release-closeout`，冻结本 ExecPlan。
- 本次规划没有修改产品、workflow、许可材料或其它权威文档，没有运行构建/测试、写入共享 target、访问/修改 GitHub 远端、
  创建 tag/Release、下载发布物或删除任何对象。

- 2026-09-02：用户下达第一阶段执行授权。`multidev/CHANGELOG.md` 已新增 `0.1.1` 小节，覆盖 `/status`
  Guardian 配置行、根配置指南、CI `codex-team-state` 常跑覆盖与 fuzzy-file-search Nextest 串行化，
  并把 `14713/14713`、0 retry 明确限定为正确性与稳定性结果。已用
  `.github/scripts/compose-release-notes.sh` 无构建渲染并审读正式 Release notes：banner、版本号说明、
  包布局、判官后端不在包内与 bubblewrap 许可段落均正确，无 Local 内容夹带。

### 当前工作

- 执行第一阶段：发布准备提交 → 合入推送 `main` → 等待候选 exact SHA 的轻量 CI → 打 tag → 发布与公开复验。

### 本任务剩余步骤

1. 执行并提交发布准备，按已授权流程合入推送，等待候选 exact SHA 的轻量 CI 通过。
2. 创建并推送 `multi-v0.1.1`，监控既有 Release workflow，完成未认证公开发布物复验。
3. 后置更新 README 与权威状态文档，提交、合入、推送。
4. 只读盘点唯一 Multi target，提交精确删除方案，记录
   `RELEASE_VERIFIED / AWAITING_CACHE_DELETION_AUTHORIZATION` 并暂停。
5. 用户明确批准精确路径后删除、复核、记录并交计划制定者最终验收。

### 阻塞项

- 缓存删除必须在发布复验和只读盘点完成后，另取用户对精确路径的第二阶段授权；当前没有该授权。

### 当前验收状态

- `FIRST_STAGE_IN_PROGRESS / CACHE_DELETION_NOT_AUTHORIZED`。

### 交接边界

- 执行者第一阶段完成后必须在删除门暂停并交回发布与盘点证据；最终删除和记录完成后再次交回。
- 计划制定者负责独立验收，不替执行者补做未经授权的外部或删除动作。任务最终接受后冻结本计划；下游只链接 WBS 的
  Local 配套补齐条目，不在本计划继续规划 Local 实现。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 发布、公开复验与缓存收尾放在同一 Plan，但以精确删除二次授权门硬分隔 | 发布成功才能判断缓存可释放；删除又是独立破坏性动作，不能由发布授权隐含 | 阶段、授权、停止点 | 已采纳 |
| 002 | 直接复用 Plan 103 的现有正式发布轨，不新增 RC、workflow、许可或验证设施 | 0.1.0 已实跑证明整链，本次冻结候选只含配套和测试稳定性收口 | 发布策略、范围 | 已采纳 |
| 003 | CHANGELOG、后置 README 和状态文档不使 Plan 105 全 workspace 结果失效 | 它们不改变 Multi 代码、功能、测试口径、依赖或发布构建语义 | 正确性证据、测试成本 | 已采纳 |
| 004 | 公开复验必须至少一次不带认证，并核验真实下载字节与解压内容 | Release 存在和 workflow 绿色不能单独证明公众能取得正确资产 | 公开验收 | 已采纳 |
| 005 | 只记录精炼哈希、URL 与结论，不把约 150 MB 发布包留在仓库或建设新证据体系 | 现有 CD 自检加独立下载复核已足够，避免无收益占用 Local 阶段空间 | 证据、磁盘 | 已采纳 |
| 006 | 小型文档错误和瞬态基础设施问题由执行者自主窄修/安全重跑；触及冻结候选、发布策略或不可变历史才暂停 | 给执行者合理收敛余量，同时保护正式 tag 与冻结证据 | 故障处理、自主性 | 已采纳 |
| 007 | 所有 tracked 编辑留在 109 工作树；用户执行提示可一次批准第一阶段及后续记录的合并推送，但不能预授权缓存删除 | 同时满足 worktree 纪律、分阶段发布需要和用户指定的二次删除门 | Git、授权、交付 | 已采纳 |
