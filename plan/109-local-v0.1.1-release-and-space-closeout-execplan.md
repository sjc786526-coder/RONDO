# Plan 109：RONDO Local 0.1.1 发布与本地空间收尾 ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

对应 WBS：`doc/WBS.md` 的“发布工程”与“产品线配套补齐与逐条收口”Local 收尾。
规划基线：`main == origin/main == d97b6c3a7d9739bc052dbce720e4fc251d31ccc0`；Plan 108 的最终 Local
全 workspace 为 `14122/14122` passed、23 skipped、零 failure/error/timeout/retry/flaky，已独立验收、合入推送，
exact-main Local 轻量 CI 为 745 passed / 0 failed，Local 实质代码与功能冻结。

## 1. 目标

### 最终目标

复用 Plan 103 已实跑的发布能力，正式发布并公开复验 `local-v0.1.1`；确认真实公众可取得正确发布物后，再更新 README
和阶段记录。随后对 Local 阶段遗留的明确可释放对象做一次完整只读盘点，停在逐对象删除授权门。只有用户第二次授权点名的
精确对象才可删除；处置完成并经独立验收后，关闭 Local 阶段及本轮两条产品线收口路线，使 WBS 回到无 active 工作包状态。

### 完成/验收标准

#### 第一阶段：发布、公开复验与后置记录

- `mydev/CHANGELOG.md` 顶部新增 `0.1.1` 小节，准确概括相对 `local-v0.1.0` 的 Local 配套、正确性和测试稳定性收口；
  不声称性能提升、本地审批模型质量通过、生产资格或新默认能力。打 tag 前用既有脚本渲染并审读正式 Release notes。
- 发布准备先形成专用工作树提交，并在用户明确授权后合入、推送 `main`。打 tag 前必须找到该 exact commit 对应的 Local
  轻量 CI，等待真实成功；无运行、运行中、skip、其它 SHA 或未执行 Local job 均不算通过。
- 创建并推送 annotated tag `local-v0.1.1`；tag 的 peeled commit 必须是上述包含 `0.1.1` CHANGELOG 的已验候选。
  推送后的 tag 不移动、不覆盖、不删除、不重建。
- tag 触发的既有 `release` workflow 中 validate、build、verify、publish 四个 job 全部成功；公开 Release 非 draft、
  非 prerelease，至少包含 `rondo-0.1.1-x86_64-unknown-linux-musl.tar.gz` 和 `SHA256SUMS`。
- 从项目目录外的 task-owned 临时目录，以未认证 HTTP 访问取得公开 Release 元数据和真实资产；归档通过公开
  `SHA256SUMS` 校验。不得用 Actions artifact、本机旧包、登录态 `gh` 输出或 workflow 绿色代替公开下载复验。
- 对公开归档复验：根目录和入口属于 Local，`bin/rondo` 可执行且 `--version` 继续报告冻结上游版本 `0.147.0`；
  包布局、根 LICENSE/NOTICE、现有流水线要求的第三方许可闭包、Local 身份与 Release notes 正确，不夹带 Multi 内容，
  也不把本地审批模型写成已获质量资格或下载即用。
- 只有以上公开复验全部通过后，README 中 Local 的固定下载、解压和入口示例才切换到 `local-v0.1.1`；链接不得依赖
  仓库级 `latest`。同步 WBS、WBS-COMPLETED、本计划动态状态和一份精炼日志，使当前事实与公开状态一致。
- `local-v0.1.0`、`multi-v0.1.0`、`multi-v0.1.1` 及其 tag、Release 和历史资产保持不动。发布准备与后置记录不改
  Local 实质代码、测试口径、依赖、lockfile、workflow、打包器或许可材料，因此 Plan 108 最终全量结果继续有效，
  本任务不重复本地全 workspace。

#### 第二阶段：完整只读空间盘点与强制暂停

- 第一阶段的发布、README 后置更新和状态记录完成后，只读盘点至少覆盖：
  `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-local`、111/113 两个历史 worktree、Plan 109 自己产生且可能已无
  保留价值的临时下载目录与工作目录，以及现场发现的其它“明确属于本轮、可重建且确有释放价值”的对象。
- 每个候选单独给出：精确绝对路径、实时占用和预计实际释放量、canonical path 与符号链接状态、进程/共享构建锁/打开句柄
  使用情况、tracked/未提交/未跟踪/ignored 独有资产情况、删除后的重建或恢复代价、建议与明确排除的相邻对象。
  worktree 还须证明 tracked 提交是否已完全进入 `main`/`origin/main`，并检查其 ignored 内容是否含只存在于该工作树的证据。
- 盘点应区分 `du` 逻辑占用、硬链接可能导致的预计实际释放量和宿主 Windows `C:` 可用空间；明确说明删除 WSL 文件
  不会自动缩小 `.vhdx`，所以 `C:` 可能不增加。信息不足的对象不得包装成安全删除建议。
- 盘点完成后，把任务状态固定为
  `LOCAL_RELEASE_VERIFIED / AWAITING_CLEANUP_AUTHORIZATION`，提交必要的 tracked 记录并在已获 Git 授权范围内完成交付，
  然后主动暂停。第一阶段授权、发布成功、WBS 排程、盘点建议或本计划文字均不构成任何删除授权。

#### 用户逐对象二次授权后的最终收口

- 用户可逐项批准、拒绝或要求保留。执行者只处理授权消息中明确点名的精确绝对路径；未点名对象视为未授权，
  用户拒绝或决定保留的对象须如实记为“用户决定保留”，不得写成已经清空。
- 每个获批对象在删除前重新核对路径、符号链接、实时占用、使用者和独有资产；现场与盘点发生实质变化或不能安全确认时，
  暂停该对象而不扩大命中范围。删除后复测对象、项目和宿主占用，实际减少量应与获批对象的可释放量大体闭合。
- 未批准对象与明确排除项保持存在且未被改变；已发布 `local-v0.1.1` 仍可公开访问，历史正式版本不变，主工作区与保留
  worktree clean。若 Plan 109 工作树本身获批释放，须在全部 tracked 收尾已经提交、合入并推送且确认无独有 ignored 资产后最后处理。
- 最终只更新必要状态文档和同一份精炼日志，记录实际删除与用户保留决定。独立验收通过后，WBS 才把 Local 阶段和
  两条产品线的配套、全量、冻结、发布收口路线记为完成，并回到无 active 工作包状态。

## 2. 范围

### 允许修改

- `mydev/CHANGELOG.md`：新增 `0.1.1` 小节，不改写旧版历史。
- 根 `README.md`：只在公开复验通过后更新 Local 固定下载、解压和入口示例；可一并窄修与本次发布直接相关且已被 live
  GitHub 状态证伪的版本/`latest` 说明，但不扩写新的发布体系。
- `doc/WBS.md`、`doc/WBS-COMPLETED.md`、本 ExecPlan 动态状态与一份精炼 `agent_log/`：分别记录当前指针、完成事实、
  任务恢复状态和必要证据，不在多处复制流水账。
- 专用 worktree 内的上述 tracked 编辑和提交；用户执行授权明确覆盖后的本地 `main` 合并、`main` 推送、annotated tag
  创建与推送、GitHub Actions 监控与安全重跑、正式 GitHub Release 发布、未认证公开下载复验。
- 项目目录外 task-owned 临时下载目录；第一阶段只创建、读取和盘点，不因“临时”而自行删除。
- 发布完成后的项目内只读空间盘点；获得用户第二次逐对象精确授权后，仅删除获批对象，并完成获批范围内的最终记录与 Git 交付。

### 不允许修改

- `mydev/` 内除 CHANGELOG 外的产品代码、测试、fixture、snapshot、配置、依赖与 lockfile；Local 功能、默认值、
  本地审批模型资格结论和冻结上游基线。
- `.github/workflows/release.yml`、`.github/workflows/ci.yml`、`.github/licenses/`、Release notes/许可收集脚本、打包器或许可材料。
  若这些内容必须修改才能成功，本任务越界，必须暂停请用户决定。
- `multidev/` 产品文件与语义；任何既有 tag、Release、资产或 Actions 历史的移动、覆盖、删除、重建、替换。
- 未获第二次精确授权时的任何文件、目录、缓存或 worktree 删除；获批后也不得扩大到候选父目录、glob、广义 clean/prune，
  或未点名的相邻对象。
- 默认排除 `eval-data/`、`test-data/_retained-test-evidence/`、`.codex/build-watchdog/` 中需保留的证据、Multi/Docker
  对象、来源不明缓存，以及尚未完全合入或仍可能被并行任务使用的 worktree。
- 本地 Cargo 构建或测试、本地全 workspace、上游升级、Docker、真实 API/模型、训练、测评、GPU/RunPod、付费资源或数据上传。

### 不允许读取/查看

- `.env.local` 内容、任何密钥/API Key、真实私有配置、项目外个人文件或私有数据。
- 冻结 qualification/unseen 测试正文、模型权重，以及与候选安全性判断无关的 ignored 内容正文。

### Git-ignored 与主物理工作区边界

所有 tracked 编辑在
`/home/sjc/desktop/RONDO/.claude/worktrees/114-plan109-local-v0.1.1-release-closeout/` 完成。
以下操作无法只靠该分支内的 tracked 文件表达，执行时必须单独识别为主物理仓库或项目外动作：

- `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-local` 是全仓唯一 Local Cargo target，位于主物理仓库的
  git-ignored `.codex/`；本任务只在发布后盘点，第二次授权前不写入、不清理。任何意外需要的本地构建也绝不能在 worktree
  下创建另一套 target；本任务原则上不运行本地 Cargo。
- 111、113 和 114 worktree 位于主物理仓库 git-ignored 的 `.claude/worktrees/`，其增删同时修改共享 Git 元数据；
  第一阶段只读盘点，删除必须逐路径获批。对 ignored 独有证据的任何迁移需求应在盘点中明示，不能因 worktree 的 tracked
  状态 clean 就直接释放。
- `main` 合并、远端推送和 tag 操作作用于共享 `.git` 与 GitHub，不是普通 worktree 文件编辑；只能在用户提示明确授权后执行。
- 公开资产下载放在项目目录外的 task-owned 临时目录，不写入仓库、共享 target 或 retained evidence。该目录若需删除，
  也作为精确候选进入第二阶段授权门。

除此之外，若意外需要写入其它主工作区 ignored 路径，先报告准确路径、用途、预计体积与后续处置，不自行扩围。

## 3. 硬约束

以下约束只固定冻结候选、不可变发布历史、公开验收、删除授权门和 Git 停止点，不固定普通命令、文档措辞细节或小故障诊断路线。

1. **发布与删除授权分离**：用户可一次授权第一阶段的 Git/GitHub 外部动作、公开下载、只读盘点和必要提交；这绝不授权删除。
   第二阶段必须停在指定状态，之后只按用户逐项点名的精确路径处置。
2. **冻结候选不扩围**：若必须修改 Local 产品代码、测试口径、依赖、workflow、打包器或许可材料，本任务不能继续沿用 Plan 108
   的冻结证据，必须暂停。不得以“窄修”名义改变候选或发布语义。
3. **正式发布身份不可变**：推 tag 前确认 `local-v0.1.1` 在本地和远端均不存在、候选 SHA 与 CHANGELOG 正确；推送后不移动、
   覆盖或删除 tag，不删除/重建已经公开的 Release，也不替换历史资产。
4. **CI、tag、workflow 和发布物绑定精确身份**：打 tag 前的 Local CI 必须绑定候选 exact SHA；发布 workflow 必须绑定正式 tag；
   公开复验必须针对该 tag 的真实公众资产。历史绿色记录和其它产品线结果不能替代。
5. **小故障可自主收敛，原则边界不可越过**：在保持 exact commit/tag 和发布语义不变的前提下，网络、runner、下载等瞬时故障可
   诊断后安全重跑，普通文档/记录错误可窄修再提交。重跑 publish 前必须先核对 Release 是否已创建，避免重复非幂等发布。
   若修复需要改冻结内容、改流水线、换产物、弱化校验、移动 tag 或删建 Release，则暂停汇报。
6. **公开复验独立且够用**：至少一次不带认证地取得元数据和两个资产，对真实归档字节与解压内容做既有关键检查；skip、只看网页、
   只信 workflow 或保留登录态都不能记为通过。同时复用现有 CD 自检，不新建签名链、数据库或审计/可信平台。
7. **README 严格后置且使用固定 tag**：公开资产存在且正确前继续指向 0.1.0；切换后只指向 Local 自己的固定 0.1.1 tag，
   不以仓库级 `latest` 代替，Multi 固定链接不变。
8. **不重复重型验证、不产生第二套 target**：本任务不运行本地 Cargo 或全 workspace，不写入或加热共享 Local target，
   更不得在 worktree 内创建 `target/`。只要 tracked 差异保持在允许范围，Plan 108 的最终结果继续有效。
9. **盘点广度不等于删除权限**：可完整发现候选，但删除建议和授权必须逐个精确到绝对路径。路径、符号链接、使用者、独有资产或
   实际命中边界任一不能可靠确认，就不删除该对象；不得使用父目录、未解析变量、glob、递归广义清理或 prune 扩大范围。
10. **诚实记录保留决定与空间效果**：删除 WSL 文件不等于 Windows `C:` 自动回收；实际释放不足、对象决定保留或工具无法核验均
    如实记录。不得为了宣称“清空”而触碰未批准对象。
11. **工作树、Git 与审查停止点**：未知修改全部保留。执行者只在 114 worktree 编辑并提交；合并和推送必须有用户明确授权，
    不能从本计划文字推定。第一阶段/盘点与二次处置完成后分别交回计划制定者独立验收；未经授权不归档分支或释放 worktree。

## 4. 软性建议

以下内容帮助执行者收敛，不是固定路线。执行者可以依据 live Git/GitHub/文件系统状态选择更干净有效的做法，只要不越过硬边界。

- CHANGELOG 可从 `local-v0.1.0..候选` 的实际差异提炼四项宏观变化：Local `/status` 增加 Guardian override 配置摘要；
  根配置指南补齐 Local 专属说明；完整 workspace 暴露的网络 fixture 与 app-server 并发稳定性问题已闭合；最新 Local 正确性
  基线为 `14122/14122` 且最终轮零 retry。措辞宜面向用户，不堆执行流水账。
- 优先复用 `.github/scripts/compose-release-notes.sh`、现有 `ci.yml`/`release.yml` 和 `doc/cd-release-pipeline.md` 操作经验。
  本次没有改发布链，通常不需要另发 RC；若 live 事实显示必须改变这个判断，应先请用户决定，而不是临时另造版本路线。
- CI/Release run 可能延迟出现，可按 exact SHA/tag 轮询。瞬态重跑前先读失败 job 并对账 Release 现状；能在原身份安全收敛的小问题
  自主处理，不因一次网络或 runner 抖动提前放弃。
- 公开复验保留 Release URL、tag peeled SHA、run ID/URL、资产名与大小、归档 SHA-256、入口/版本、布局/许可/notes 结论即可；
  无需把约 150 MB 归档复制进仓库，也无需建设第二套机器证明设施。
- 当前 README 的 `latest` 描述与已实测 CD 语义可能不一致；可在公开复验后以 live Release 状态为准做一处短小纠正，核心仍是
  告诉用户两条产品线都使用各自固定 tag，而不是让 README 跟随仓库级 `latest`。
- 盘点可组合 `realpath`/`readlink`、`stat`、`du`、Git ancestor/status、ignored 文件清单、共享 build lock、进程命令行、`lsof`/`fuser`
  等现有轻量手段。工具缺失时不必安装大型设施；应通过互补证据说明不确定性，删除前仍须 fail-closed。
- 111/113 当前只是候选：规划时已知两者 clean、归档分支完全进入 `main`，但执行期仍需重测使用者和 ignored 独有资产。
  114 只有在最终记录已安全进入主线后才可能成为可释放候选。不要预先认定全部 worktree 都应删除。
- 最终状态文档保持职责分工：WBS 写当前路线终态与无 active 工作包；WBS-COMPLETED 写完成事实；Plan 动态段支持恢复；
  同一 agent log 保存必要执行证据。无需新增盘点 manifest、持久数据库或自动清理器。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-09-03：核对主工作区 clean，`main` 与 `origin/main` 同为
  `d97b6c3a7d9739bc052dbce720e4fc251d31ccc0`；111、113 两个历史 worktree clean、分支均为 `main` 祖先。
- 2026-09-03：阅读根与 Local 规则、README、当前 WBS、计划模板、Plan 103/106/108、CD 操作手册、Local CHANGELOG、
  发布 workflow 及相关实施/验收记录；确认现有发布能力足以承接 0.1.1，无需新增发布或验证设施。
- 2026-09-03：实测唯一 Local target 为真实目录，占用 `103070741200` B（约 96.0 GiB）；仅用于规划基线，
  尚未执行完整进程/锁/句柄与 ignored 资产盘点。
- 2026-09-03：从 `main@d97b6c3a` 创建专用 worktree
  `.claude/worktrees/114-plan109-local-v0.1.1-release-closeout` 与分支
  `worktree-114-plan109-local-v0.1.1-release-closeout`，制定本 ExecPlan。
- 本次规划没有修改产品、workflow、许可材料、README 或权威状态文档；没有运行构建/测试、写入共享 target、访问或修改
  GitHub 远端、下载发布物、创建 tag/Release，亦未删除任何对象。

- 2026-09-03：用户已明确授权第一阶段（CHANGELOG/后置 README/状态记录、必要批次的 `main` 合并与
  `origin main` 推送、annotated tag `local-v0.1.1` 的创建与推送、发布流水线监控、未认证公开复验、
  项目外 task-owned 临时下载目录、只读盘点）。删除仍未授权。
- 2026-09-03：复核 live 状态——主工作区 clean，`main == origin/main == d97b6c3a`，`local-v0.1.1`
  在本地与 `origin` 均不存在；现存 tag 只有 `local-v0.1.0`/`local-v0.1.0-rc1`/`multi-v0.1.0`(+6 RC)/`multi-v0.1.1`。
  公开 Release 三个（`multi-v0.1.1`、`multi-v0.1.0`、`local-v0.1.0`），仓库级 `latest` 现落在 `multi-v0.1.1`。
- 2026-09-03：核对 `local-v0.1.0..d97b6c3a` 的实际 Local 差异，据此写入 `mydev/CHANGELOG.md` 的
  `0.1.1` 小节，并用既有 `compose-release-notes.sh` 渲染审读正式 Release notes（Local 专属段正确、
  无 Multi 内容、无性能/质量声明）。核实 `ci.yml` 本轮只改了 Multi 选包与文档指针注释，Local 选包未变，
  因此 CHANGELOG 不声称 Local CI 覆盖变化。
- 2026-09-03：查明 `local-v0.1.0` 的 release run `33609017890` 之所以红是 publish job 在 Release
  已创建后被旧的"任一产品线都不得占用仓库级 latest"硬门禁判负；该门禁已在当前 `release.yml` 中改为
  只对 prerelease 生效（`multi-v0.1.1` run 已实证通过）。故正式 `local-v0.1.1` 预期四个 job 全绿，
  并预期由 GitHub 把 `latest` 指派给它——这是平台展示状态，不是版本权威。

- 2026-09-03：候选 merge `e560d33f` 已推送；其 exact SHA 的轻量 CI run `33779415523` 全绿
  （`gh run watch --exit-status` 返回 0，路径分流只跑 `check (local)`）。随后创建并推送 annotated tag
  `local-v0.1.1`（tag 对象 `1e9c60e8`，peeled 到 `e560d33f`）；release run `33780571720` 的
  validate/build/verify/publish 四个 job 全部成功。tag 推送后未移动、未覆盖、未删除。
- 2026-09-03：在项目目录外的 task-owned 临时目录完成未认证公开复验并全部通过——元数据非 draft/非
  prerelease、两个资产齐备；归档 SHA-256 `e3e7df4c…41d30c6` 与公网 `SHA256SUMS` 一致；包根/入口/
  `codex-package.json` 为 Local 身份且无 Multi 内容；`bin/rondo --version` 仍报 `0.147.0`；
  21 项必需文件非空、`THIRD-PARTY-LICENSES/` 17 份；Release notes 9 项必需内容命中、3 项 Multi 专属内容缺席。
  四个公开 Release 齐全，历史三个的时间戳与资产数未变。
- 2026-09-03：复验通过后才更新 README 的 Local 固定链接到 0.1.1，并按 live 状态窄修仓库级 `latest` 说明；
  同步 `doc/WBS.md`、`doc/WBS-COMPLETED.md`、本节与 `agent_log/2026-09-03-plan109-local-v0.1.1-release.md`。
- 2026-09-03：完成第二阶段的完整只读盘点（五个候选 + 明确排除项 + 空间口径说明），**未删除任何对象**。
  盘点的验证边界已如实记录：本会话被 worktree 隔离守卫限制，未能对 111/113 直接跑 `git status`，
  该项须在删除前补做。

- 2026-09-03：停止点独立审查以"验收通过 / 阶段目标完成"接受（审查提交 `fdec70dd`，报告
  `agent_log/2026-09-03-plan109-release-and-cleanup-gate-review.md`，已合入并推送 `main`），
  并代用户给出逐对象清理授权。审查补测确认 111/113 clean、无句柄、已完全进入主线，
  另指出盘点漏列 113 内约 15.2 MB ignored watchdog 内容（含约 205 KB 独有早期 3/3 证据），
  判定已被后续 retained 3/3 与最终 `14122/14122` 覆盖，可随 113 删除；执行者接受该判断。
- 2026-09-03：按逐对象授权执行清理。删除前复核全部通过（canonical path、非符号链接、零打开句柄、
  无构建进程、构建锁无持有者，并补做 111/113 的 `git status`）。删除 `.codex/cargo-target/rondo-local`，
  以 `git worktree remove` 正常移除 111、113 并保留 `zz-done/` 分支。项目占用
  `151,221,708,658` → `47,772,685,781` B，实际释放 `103,449,022,877` B（约 96.34 GiB），与实测占用闭合；
  Windows `C:` 基本不变，符合盘点时的预判。排除项经复测全部未受影响。

### 当前工作

- 全部完成。最终记录合入推送后，按授权删除任务专属临时目录并归档/移除 114 工作树；本计划就此冻结，
  后续工作只由 WBS 另行立项。

### 本任务剩余步骤

- 无。发布、公开复验、只读盘点、停止点独立验收与获批清理均已完成并记录。

### 阻塞项

- 无。

### 当前验收状态

- `COMPLETED / GOAL_COMPLETED / LOCAL_RELEASE_VERIFIED / FINAL_REVIEW_ACCEPTED /
  AUTHORIZED_CLEANUP_EXECUTED / INTEGRATED / PUSHED`。
  发布已完成并经未认证公开复验；只读盘点已交付并通过停止点独立验收；用户逐对象授权的清理已执行，
  实际释放约 96.34 GiB。没有任何未获授权的对象被删除。本计划冻结为任务合同与历史记录，
  后续路线只以 `doc/WBS.md` 为准。

### 交接边界

- 执行者在第一阶段与只读盘点完成后必须停在删除门，把发布和逐对象盘点证据交给计划制定者审查；最终处置后再次交回。
- 计划制定者作为独立审查者，不替执行者补做未经授权的 GitHub 状态变更或删除动作。最终接受后冻结本计划；以后若有新工作，
  只由 WBS 另行立项，不在本计划续写路线。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 发布、公开复验、只读盘点与获批清理放在同一 Plan，但以逐对象二次授权门硬分隔 | 先确认不可变发布成功再判断本地对象价值，同时不让发布授权隐含破坏性清理 | 阶段、授权、停止点 | 已采纳 |
| 002 | 直接复用 Plan 103 的现有正式发布轨，不新建 RC、workflow、许可或验证体系 | 0.1.0 与 Multi 0.1.1 已实跑证明整链，本次候选只含配套和测试稳定性收口 | 发布策略、复杂度 | 已采纳 |
| 003 | CHANGELOG、后置 README 和状态记录不使 Plan 108 最终全量结果失效 | 这些内容不改变 Local 产品、测试口径、依赖或打包语义 | 正确性证据、测试成本 | 已采纳 |
| 004 | 公开复验至少一次未认证下载真实字节并检查解压内容 | workflow 成功或 Release 存在不能单独证明公众取得的是正确完整资产 | 发布验收 | 已采纳 |
| 005 | 空间盘点覆盖全部明确候选，但授权与删除始终逐对象精确处理 | 既完成 Local 阶段收尾视野，又避免从“可盘点”推导“可删除” | 磁盘、破坏性操作 | 已采纳 |
| 006 | 主物理仓库的 ignored target/worktree 与项目外下载目录单独列边界，不把它们伪装成普通 tracked 编辑 | 这些对象不随分支提交，且删除/共享状态影响需要单独判断 | 工作树、磁盘、交付 | 已采纳 |
| 007 | 瞬时基础设施故障和非实质文档错误允许执行者自主诊断、窄修与安全重跑，触及冻结候选或不可变历史才暂停 | 给执行者合理收敛余量，同时保护正式发布身份和最终正确性证据 | 故障处理、自主性 | 已采纳 |
| 008 | 执行者在 114 分支提交；main 合并与推送必须来自用户给执行者的明确授权，规划提交本身不构成授权 | 遵守用户指定的工作树纪律与 Git 停止点 | Git、角色 | 已采纳 |
| 009 | 最终关闭路线时如实记录用户保留项，不以“全部删除”作为完成前提 | Local 收口取决于发布验证和明确处置决定，不取决于清空所有可重建资产 | 完成口径、记录 | 已采纳 |
