# Plan 092 Durable Session TUI 基线欠账窄修复

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

关闭 Plan 091 完整 `codex-tui` crate 暴露的三项既有 Durable Session TUI 基线欠账，使 protocol fixture、当前正式
`setRootState` operation 集合和两项用户可见 query snapshot 重新一致，并以完整 crate 的可信零 failure/零 error 结果形成
`DURABLE_SESSION_TUI_BASELINE_DEBT_PASS`。

### 完成/验收标准

- [x] 三项既有失败均在当前正式合同下通过，不删除字段、不弱化断言。
- [x] protocol fixture 由完整 typed operation 集合约束，正式字段再次增加时不能静默遗漏。
- [x] 两项 snapshot 只反映当前 `setRootState` 展示语义，无无关 UI 漂移。
- [x] 分页替换、transport loss 和迟到 completion 行为保持通过。
- [x] 完整 `codex-tui` crate 为零 failure、零 error；skip 逐类记录，retry 显式记录并按需定点复核。
- [x] Plan 091 prompt-edit 回归覆盖继续通过。
- [x] 无计划外 `.snap.new`、生成文件或对 Plan 091 原始 JUnit 的覆盖/删除。
- [x] scoped fix、格式检查与 `git diff --check` 通过。
- [x] Plan 090 工作树和成果保持原样。
- [x] 独立只读审查无未关闭高、中等级 correctness finding。
- [x] 任务变更、Plan 动态状态、精炼日志和 `doc/WBS-COMPLETED.md` 形成完整提交与集成记录。
- [x] 验收提交进入本地 `main` 并推送 `origin/main`；任务分支不推送，完成后按仓库惯例归档。

## 2. 范围

### 允许修改

- `multidev/codex-rs/tui` 中与三项失败直接相关的 fixture、测试和 snapshot。
- 同一 Durable Session query/control 展示面的必要窄测试辅助代码。
- 防止 protocol operation fixture 再次遗漏正式字段的相称回归保障。
- 本 Plan 动态状态、精炼实施日志和最终 `doc/WBS-COMPLETED.md` 记录。

### 不允许修改

- Durable Session protocol、schema、产品能力定义或正式 `setRootState` 语义。
- Durable Session query/control UI 设计与产品逻辑。
- Plan 091 prompt-edit 实现以及 `mydev/`、`eval/`、`training/`、Plan 090 成果。
- 顶层 WBS 或任何子 WBS。
- 共享 target 长期位置、看门狗永久默认值、上游基线或其它任务成果。
- 069 target 的删除/迁移，以及任何现有 worktree 的清理、归档或删除。

### 不允许读取/查看

- Plan 090、其它 worktree 或主工作区的未提交内容；只允许状态级保护性检查。
- `.env.local` 内容及任务无关的项目外个人文件。

## 3. 硬约束

1. 本任务独立于 Plan 091 和多智能体四期，只关闭既有三项 TUI 测试欠账，不重开已完成产品任务。
2. 复用 Plan 091 正式 JUnit 作为修复前复现证据，不先重复运行已知必败的完整 crate。
3. 若聚焦复核显示根因是当前产品或协议语义错误，停止通过 snapshot 掩盖并重新评估任务边界。
4. 所有重型 Cargo build/test/fix/lint 必须经根 `scripts/with-build-lock.sh` 或正式 `just` 入口，全局单任务运行并复用唯一
   Plan 069 target：
   `/home/sjc/desktop/RONDO/.claude/worktrees/069-m4-s1-durable-team-session/multidev/codex-rs/target`。
5. 每条正式重型命令只以进程级环境变量设置项目门：warn `270000000000`、stop `285000000000`、max `290000000000` bytes，
   以及 Plan 092 临时 Windows `C:` stop `30000000000` bytes；不得改仓库或长期配置。
6. 每批前必须重新读取 canonical lock、项目/target 占用、`/mnt/c` 对应的真实 Windows `C:` 余量、Cargo/rustc/nextest、
   cgroup/watchdog 及其它必要资源计数器。任一不可得、`C:` 低于 30GB、项目达到停止线或其它门不满足时 fail-closed。
7. 不使用 WSL 虚拟文件系统余量满足 Windows 门，不提高并发、不绕过 watchdog/cgroup，不与 Docker 或真实模型并发。
8. 资源不足时，只有确认 target 无使用者后才可保守清理 069 target 中明确可再生且必要的 `debug/incremental` 产物；不得扩大到
   整个 target、release、deps、Cargo registry、其它 worktree、模型或 Docker 资产。
9. fake loopback 测试可只在命令级设置 `NO_PROXY=127.0.0.1,localhost` 与小写等价项；不得改全局代理或产品行为。
10. 不运行 full workspace、`--all-features`、Docker、真实 API/模型、训练、性能测评、发布或上传。
11. skip、retry、基础设施失败和未运行项必须诚实区分；不得为凑绿删测试、弱化断言或把未运行表述为通过。
12. 普通编译、fixture、snapshot、格式、测试和审查问题在范围内自主窄修并重跑；重大协议/架构问题不得擅自扩大。
13. 所有 tracked 修改先在 092 worktree 提交并确认 clean；仅验收通过后合并本地 `main`、推送 `origin/main`，不推送任务分支。

## 4. 软性建议

- 保留现有 protocol JSON round-trip 的测试目的，同时用 typed `DurableSessionOperations` 约束 operation 集合，避免建设第二套字段清单。
- 先运行三项原失败和相邻 query/control 测试；最终代码稳定后再运行一次完整 `codex-tui` crate。
- snapshot 逐行审查，只接受能由当前 `setRootState` 正式展示直接解释的差异。
- 完整 crate 如出现新的有效小型或中型相邻回归可在范围内修复；需要产品架构、协议或上游变更时停止扩大。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-26：确认主工作区 `main@7776ba0` clean，092 分支与 worktree 从该基线创建；090/091/069 等现有 worktree 未改动。
- 2026-08-26：完整读取根与 `multidev` 规则、README、当前 WBS、plan 模板和相关 091 证据；实际写集没有适用的更近
  `AGENTS.md`。
- 2026-08-26：只读复核 Plan 091 正式 JUnit。三项失败分别为一个手写 JSON fixture 缺 `setRootState`，以及两项 snapshot 缺同一
  `set-root-state` 展示；JUnit 中原失败均重试后仍失败，构成有效修复前证据。
- 2026-08-26：手写 JSON fixture 保留 response 反序列化和 duplicate identity 路径，但 operation 子树改由 typed
  `DurableSessionOperations` 序列化；两个 snapshot 只增加正式 `set-root-state` availability/provenance 展示。
- 2026-08-26：首个聚焦尝试在测试开始前由 watchdog 因 `memory_full_psi_sustained_above_limit` 主动停止，exit 125、payload 137、
  JUnit absent、`cleanup=none`；保留增量进度且不改门限、不清理 target，资源恢复后的正式聚焦轮 22/22 passed。
- 2026-08-26：完整 `codex-tui` crate Nextest `499b4a7d-dc21-4749-9bb3-8959b5504e99` 为 3439 passed、0 failure、0 error、
  4 skipped；其中 1 项 fake transport 测试首次 `Broken pipe` 后 retry 通过，随后定点复核 1/1 一次通过。
- 2026-08-26：4 个 skip 为 3 个显式忽略的 tmux/manual resize smoke 和 Linux 上按设计忽略的 Windows AltGr 测试；均未表述为通过。
  scoped `just fix -p codex-tui`、`just fmt`、`just fmt-check` 与 `git diff --check` 通过，无 `.snap.new`。
- 2026-08-26：Plan 091 原始 JUnit SHA-256 仍为
  `c4ca1b921297a7f4de67229051b4fff7b847631ec53788f3159986a2b00b2f03`，与其 summary 一致；Plan 090 既有未提交现场未改动。
- 2026-08-26：独立只读审查结论 `ACCEPT`，High/Medium correctness finding 均为 0；确认 fixture、snapshot、产品边界和保存证据均
  满足任务合同。
- 2026-08-26：最终资源核验项目 `272354115584` bytes、069 target `212729303040` bytes、Windows `C:` 实际余量
  `42414792704` bytes；canonical lock 可取得，无 active heavy scope 或 Cargo/rustc/nextest，memory full PSI avg10 为 0。
- 2026-08-26：实现与验收提交 `6ad805ca45cee5d477d33086d9f7ae8b68849f47` 已形成，092 worktree clean，并从
  `main@7776ba0` 无冲突 fast-forward 进入本地 `main`。
- 2026-08-26：本地集成记录提交 `4fce78c` 连同实现提交已推送 `origin/main`；任务分支未推送，已归档为
  `zz-done/worktree-092-durable-session-tui-baseline-debt`，092 worktree 保留且 clean。

### 当前工作

- 无。

### 本任务剩余步骤

- 无。

### 阻塞项

- 无。重型批次仍以每批实时资源预检为前置。

### 当前验收状态

- `COMPLETED / ACCEPTED / INTEGRATED / PUSHED / DURABLE_SESSION_TUI_BASELINE_DEBT_PASS`。

### 交接边界

- 本任务完成后冻结本计划；共享 target 迁移、旧 worktree 清理、永久看门狗调整和全 workspace 冷基准不在本任务处理。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 以 Plan 091 JUnit 作为正式修复前复现，不重复完整必败批次 | 三项失败、重试和具体 diff 已完整保存，重复运行没有新增诊断价值 | 测试/资源 | 已采纳 |
| 002 | 只修 fixture 和 snapshot，不改 protocol 或产品渲染 | 当前正式类型和渲染已经一致包含 `setRootState`，欠账只在测试资产 | 范围/语义 | 已采纳 |
| 003 | 手写 JSON fixture 的 operation 子树改由 typed `DurableSessionOperations` 序列化 | 保留 JSON response 反序列化与重复 identity 断言，同时让未来正式字段新增触发编译期遗漏 | 测试设计 | 已采纳 |
| 004 | Plan 092 重型命令使用命令级 270/285/290GB 项目门和临时 30GB Windows `C:` 门 | 用户本任务一次性授权；不改变长期资源政策 | 资源 | 已采纳 |
| 005 | 首个聚焦批次因 memory full PSI 被 watchdog 停止后保留增量进度，资源恢复再重跑，不清理 target | stop 发生在测试前且 watchdog 正常闭合 scope；增量重跑能避免无必要重建并保持全部安全门 | 执行/资源 | 已采纳 |
| 006 | 完整 crate 的唯一 retry 显式记为 fake transport `Broken pipe`，并以单测 1/1 一次通过定点复核 | 重试后通过不能静默冒充一次通过；独立复核可区分时序性 teardown 波动与本任务回归 | 测试/证据 | 已采纳 |
