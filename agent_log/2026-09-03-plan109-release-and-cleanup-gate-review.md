# Plan 109 发布与清理授权门独立审查

日期：2026-09-03
审查基线：`main == origin/main == ec7acd760b7e0b1f28ec8805be870df3124f0e70`
合同：`plan/109-local-v0.1.1-release-and-space-closeout-execplan.md`
实施记录：`agent_log/2026-09-03-plan109-local-v0.1.1-release.md`

## 结论

**验收通过**：`ACCEPT / LOCAL_RELEASE_VERIFIED / CLEANUP_GATE_ACCEPTED`。

Plan 109 的第一阶段发布、未认证公开复验、README 后置更新和第二阶段只读盘点均正确完成；没有发现产品正确性、
发布身份或历史资产方面的阻断性问题。当前停在计划要求的删除授权门，尚未删除任何对象。

**任务总目标尚未完成，但不是失败**：仍需执行本报告代用户作出的逐对象清理决定、记录实际释放与保留项、完成最终
Git 交付并再次独立验收，才能关闭 Local 阶段和两条产品线收口路线。当前状态应保持
`LOCAL_RELEASE_VERIFIED / AWAITING_AUTHORIZED_CLEANUP_EXECUTION`。

本轮没有运行 Cargo、全 workspace、Docker、真实 API/模型、训练或测评，也没有重复下载约 149 MB 的公开归档。
候选相对 Plan 108 冻结点无产品代码变化，现有 CI、发布流水线、公开 digest 与执行者未认证下载证据足以验收。

## 发布与文档复核

- `d97b6c3a..e560d33f` 只有 `mydev/CHANGELOG.md` 与 Plan 109 ExecPlan；对 `mydev/codex-rs`、`multidev`、
  `.github`、依赖、lockfile、脚本和打包器的差异为空。Plan 108 的 `14122/14122`、23 skipped、零 retry
  最终结果继续适用于发布候选，不重跑本地全量是正确选择。
- 远端 `main` 为 `ec7acd76`；远端 annotated tag 对象为 `1e9c60e8`，peeled 到候选
  `e560d33f`。候选 exact SHA 的 CI run `33779415523` 为 success，实际执行 `check (local)`；
  后置 main 的 CI run `33787819247` 为 success，产品 check 因纯文档差异按设计 skip。
- release run `33780571720` 的 Validate、Build rondo、clean-runner Verify、Publish 四个 job 全部 success，
  head SHA 为 `e560d33f`。Build/Verify 中既有归档、许可、入口、sandbox、A13/A14 检查均真实执行。
- 未认证公共 API 当前显示 `local-v0.1.1` 非 draft、非 prerelease；两个资产均为 uploaded。归档大小
  `149323476` B，平台 digest 为
  `sha256:e3e7df4c0536e18d77189a0e1f9f1b87e5fb1caace57e16bb35a6f28141d30c6`；未认证下载的
  `SHA256SUMS` 声明同一摘要。公开 Release notes 与 tag 内容重新渲染后正文一致，仅 API 文本末尾多一个空行。
- 四个正式 Release 当前均非 draft、非 prerelease，历史三个的 Release/资产时间戳、名称、大小与 digest 与既有记录一致；
  没有发现 tag 移动、Release 重建或资产替换。仓库级 `latest` 当前确为 `local-v0.1.1`。
- 接受执行者两处主动纠偏：Local 本轮 CI 选包没有变化，因此 CHANGELOG 不照抄 Multi 的 CI 覆盖项；README 把已被
  live 状态证伪的“两条线都不占 latest”改为平台展示指针跟随最近正式发布，同时继续以各产品固定 tag 为权威入口。
  两处都比机械复制旧文案更准确。
- CHANGELOG 将 `/status`、Local 配置指南与两类测试稳定性收口限定为正确性/可用性事实，明确不作性能、模型资格或生产承诺；
  README 的 Local 下载、解压和 `bin/rondo` 示例均已后置切到固定 `local-v0.1.1`，Multi 固定链接未动。

## 只读盘点复核与一项非阻断纠正

审查会话补做了执行者受隔离守卫限制而未完成的检查：111、113、114 三个 worktree 当前 tracked/untracked 状态均 clean；
111/113/114 的 HEAD 均为 `main` 与 `origin/main` 的祖先；111、113 当前 `lsof +D` 均无打开句柄。三个 worktree 路径本身
都是普通目录，不是符号链接。由此关闭 111/113 删除前必须补测的 Git 状态不确定性；实际执行删除时仍按合同重测现场。

发现一处盘点文字遗漏，但不阻断停止点验收：113 除执行日志已列的两个 `.venv`、小型 cache 与空 target 骨架外，
还包含 ignored 的 `.codex/build-watchdog`（`15197619` B）、`cloud-tasks/error.log`（`6426` B）等。
该 watchdog 目录 39 个文件中，Plan 108 正式保留的 27 个文件已在主工作区
`test-data/_retained-test-evidence/plan108-local-final-full-workspace/` 逐 SHA-256 对应；另有约 `204930` B
非空独有字节，来自一轮较早的 `3/3` 定向通过、对应 console 与辅助脚本。它们是已被 retained 的后续 `3/3` 定向轮和最终
`14122/14122` 覆盖的开发期冗余，不是唯一正式证据。本审查决定不另行复制或建设归档设施，可随 113 worktree 一并丢弃。
执行者最终记录应把“无独有资产”修正为“存在上述开发期独有字节，经审查明确批准丢弃”。

Local target 仍为普通目录，实时占用 `103070741200` B；审查时无 Cargo/Rustc/Nextest 构建进程，构建锁无持有者，
未见 target 打开句柄。它仍只包含可重建 Cargo 产物，Plan 108 正式证据位于明确排除的 retained evidence 中。

## 代用户作出的清理决定

用户明确委托本审查直接作出合理决定。以下构成 Plan 109 第二阶段的**逐对象精确批准**；执行者不得扩大到父目录、glob、
其它缓存或排除项。每个对象操作前仍须按合同重新确认 canonical path、非符号链接、实时占用、无使用者与无未决 tracked 变化；
现场发生实质变化时只暂停该对象，不影响其它已批准对象。

1. **批准删除** `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-local`。
   Local 已冻结并公开发布，WBS 没有排定后续 Local 构建；释放约 96.0 GiB 的收益明显高于保留热缓存的价值。
   接受未来若重开 Local 开发需重新冷构建的代价。只删除该完整目录，保留 `.codex/cargo-target` 父目录及其它 `.codex` 内容。
2. **批准通过 Git worktree 正常移除**
   `/home/sjc/desktop/RONDO/.claude/worktrees/111-plan107-closeout`；保留其既有
   `zz-done/worktree-111-plan107-closeout` 分支。
3. **批准通过 Git worktree 正常移除**
   `/home/sjc/desktop/RONDO/.claude/worktrees/113-plan108-local-full-workspace`；保留其既有
   `zz-done/worktree-113-plan108-local-full-workspace` 分支，并按上节决定一并丢弃已明确识别的冗余 ignored 字节，
   不再复制到 retained evidence。
4. **批准删除** `/home/sjc/.claude/jobs/5bba0e34/tmp`，但仅在执行者重新确认它仍是本任务专属普通目录、无打开句柄且没有
   新增独有资产后处理；不得删除 `/home/sjc/.claude/jobs/5bba0e34` 或其任何相邻目录。
5. **有条件批准最后移除**
   `/home/sjc/desktop/RONDO/.claude/worktrees/114-plan109-local-v0.1.1-release-closeout`。
   它必须最后处理：先在其中完成本审查报告、清理结果、用户决定和最终状态的 tracked 提交，确认全部提交已合入并推送
   `main/origin/main`，工作树 clean、无 ignored 独有资产、无打开句柄；再按仓库惯例把分支归档为
   `zz-done/worktree-114-plan109-local-v0.1.1-release-closeout`，最后用 Git worktree 正常移除精确路径。

继续明确排除且不得触碰：`eval-data/`、`test-data/_retained-test-evidence/`、主物理仓库 `.codex/build-watchdog/`、
`.codex/hooks*`、Multi/Docker 对象、来源不明缓存、任何候选父目录及全部已发布 tag/Release/资产。

删除完成后须以对象和项目占用前后值核对实际释放；Windows `C:` 不增长是预期现象，不应当成删除失败。随后确认公开
`local-v0.1.1` 仍可访问、未批准对象未变、主工作区与保留工作树 clean，并更新同一实施日志、ExecPlan 动态状态、WBS 与
WBS-COMPLETED。完成这些动作后再交回最终独立验收；在此之前不得把 Plan 109 或整条产品线收口路线记为最终完成。
