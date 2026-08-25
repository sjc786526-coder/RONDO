# Plan 073 第二轮整改中断交接复验

日期：2026-08-25

审查对象：`worktree-073-m3-c2-publication-critic-selection@77ef232`

## 结论

- **验收不通过。** validation 的物理 split 生产读取与 selection lock 的真实输入重算已经正确修复，但测试仍在 lock 前读取 unseen，bundle reader 未使用现成的固定 Plan 066 身份校验，unseen confirmation/report 的 `GO` 仍可由自洽但未绑定真实 release/raw/Judge 的文档伪造。
- **任务目标完成。** 正式 validation 证据仍逐字节复算为 `NO-GO`；本轮发现不改变三候选质量结论。不得生成 selection lock、释放 unseen、启用 Publication Critic 或解锁 M3-D。

## 已确认关闭

1. `selection/dataset_source.py` 的 production validation 分支只读取 Plan 066 train+validation bundle，不再打开 mixed v8。bundle 重建的 55 条、26 pairs validation release 与归档逐字节相同，SHA-256 为 `757dd624c3d47f87dd5683d24f9f1753b1dbbffb42fdeff567c9e3e5e0b71a91`。
2. `build_selection_lock()` 会先从 bundle 重建 validation release，再用三份 raw observations 与成对 Judge package/aggregate 重算 validation result，并要求与待锁结果 canonical 相等。先前的 synthetic release 与手改 `SELECTED` 路径已关闭。
3. 归档 raw、Judge package/aggregate 与当前代码重算得到原 validation result，SHA-256 仍为 `2b36eb4b408ff9a1a6a9830429fb806e9e2df1e54b6374755b98febb3cc98915`，terminal 为 `NO_GO`。tracked JSON 仍为 `f97fcdcc78c9932dd96eb17c419ef29bf574649d7b67c1c497e861daa2eee8e4`。
4. 真实 Plan 066 handoff bundle 经已有 canonical `verify_plan066_bundle()` 验证有效：63 files、train 128/58、validation 55/26、unseen rows 0。

## 阻塞性 finding

### 1. containment 测试仍在 lock 前读取 unseen

`eval/tests/test_publication_critic_plan073_selection.py:353-363` 的 `UnseenContainmentTest.setUp()` 直接全文读取并 `json.loads` mixed `supervision.jsonl`，还筛出了 45 个 unseen id。访问 spy 到该文件 `365-391` 才开始，因此 production reader 的“不打开 mixed v8”断言本身成立，但执行者所称本轮 312 项测试“未释放/未碰 unseen”不成立，也违反 ExecPlan 对代码和测试在 selection lock 前不得访问 unseen 内容的硬边界。

最小修复是删除该 `setUp()` 对 mixed supervision 的读取，改用 bundle 固定边界、行数和全路径访问 spy 证明 validation 不触碰 mixed v8。无需读取 unseen id 来证明物理隔离。

### 2. bundle reader 只验证自洽摘要，没有绑定 canonical Plan 066 身份

`selection/dataset_source.py:192-229` 只检查 manifest 自身 content hash、data size/hash、零 unseen 声明和一个格式正确的 v8 manifest SHA；它没有校验 Plan 066 固定 source constants、完整文件集、精确边界或 data source。临时副本中修改一条 packet、重算 data/manifest 两层摘要并只保留 manifest+data 后，现有 `load_split()` 仍接受 55 条 validation。

仓库已有 `full_model_training.plan066_bundle.verify_plan066_bundle()`，并已证明当前真实 bundle 通过。应优先复用该 canonical verifier/loader，或实现等强固定身份检查；不需要新增签名、registry、数据库或审计体系。

### 3. unseen confirmation/report 的 GO 仍由文档自证

`decision.py:679-750` 的 `validate_unseen_confirmation()` 只接收 confirmation、freeze 和 lock；它校验声明的哈希/组合，并从 confirmation 自带 rows 重算 confusion、AUC、gates 与 terminal，但不绑定真实 unseen release、raw score 或 Judge package/aggregate。`runner.py:527-543` 的 `confirm` 也不从冻结数据重建传入 release，且只接 Judge aggregate，没有 package。

已用纯内存合成反例复现：官方 evaluator 在 Judge 缺失时给出 `INCONCLUSIVE`；仅把 confirmation 自报的 Judge view 改为 `present=true`、同步改 terminal/reasons，当前 validator 即接受为 `GO`。同理，测试文件明确标注为非真实 unseen body 的 synthetic release 也可经现有 evaluator/validator形成 `GO`。

`runner.py:613-670` 的 report 进一步直接把该 confirmation terminal 提升为 `task_terminal`，且没有核对 selection lock 的 `validation_result_sha256` 是否等于同时传入的 validation result。由此，GO 路径尚不具备和 validation lock 同等级的真实输入绑定。

最小修复是让 confirm/report 在 lock 下重建 unseen release并要求输入相等，用 raw score 与成对 Judge package/aggregate 重算 confirmation 后作 canonical equality，再把 lock 的 `validation_result_sha256` 与 report 的 validation result 绑定。补 synthetic release、伪造 Judge view、错配 result/lock、缺 Judge package 四个回归即可。

## 文档状态

ExecPlan 当前同时写有 `REMEDIATED_R2_AWAITING_RE_REVIEW`、`无代码剩余/无阻塞` 与 `SECOND_RE_REVIEW_FAILED`，关键决策 012/013 又保留第一轮“未关闭/部分关闭”描述，互相矛盾。功能修复完成后应一次性整理为真实当前状态；不要把本轮 review finding 写成已关闭。

## 复验证据与未运行项

- 14 项 `SelectionLockTest` / `UnseenConfirmationTest` 通过；这些绿灯同时证明现有测试没有覆盖一致性伪造 Judge view。
- canonical Plan 066 bundle verifier 通过；validation release 与正式 result 均逐字节重建一致。
- `git diff --check 71525eb..77ef232` 通过；审查前 worktree clean。
- 未运行执行者报告的 312 项全模块测试，因为其中 containment `setUp()` 会在无 lock 时读取 unseen；该既有结果不能表述为“未碰 unseen”。
- 未加载模型，未运行 Opus、Cargo、Docker、服务或 unseen campaign；未改主工作区和其他 worktree。

## 代用户作出的决定

1. 保留正式 `NO-GO` 及全部原始质量证据，不重跑三候选模型或 Opus，不生成 selection lock，不释放 unseen，不启用 Critic，不解锁 M3-D。
2. `77ef232` 不通过验收、暂不合并。下一轮仅处理上述三项窄修及 ExecPlan 状态同步，不扩建可信、签名、registry、数据库或通用评审设施。
3. 修复后只跑不读取 unseen 的 pure/focused tests、canonical bundle verifier、归档 validation release/result/report 重建与 `git diff --check`；无需 Cargo、Docker、模型或全量重型测试。

本审查只提交 Plan 073 worktree；不合并、不推送、不归档分支。
