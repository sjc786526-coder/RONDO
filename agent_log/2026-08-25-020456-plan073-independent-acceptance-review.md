# Plan 073 独立验收审查

日期：2026-08-25

## 结论

- **验收不通过。** 正式指标与 `NO-GO` 推导可以复算，但实现违反 unseen lock 前的隔离边界，且 selection lock 可由不一致的 `SELECTED` 文档打开；当前分支不能作为正确完成态合入。
- **任务目标完成。** 三候选同口径质量横评已形成可信的 `NO-GO`：所有候选在完整 operating curve 上的最佳 balanced accuracy 都低于冻结底线，结论不依赖 Judge，也没有理由选择 base 兜底。Publication Critic 继续 default-off，M3-D 保持锁定。

## 阻塞性 finding

### 1. validation release 在 lock 前读取了 unseen 内容

`selection/release.py:89-93` 以 `allow_evaluation=True` 创建完整 `DatasetConsumer`；`training_data/consumer.py:219-229` 随即整体读取 v8 的 packets、supervision、pairs，且 `consumer.py:144-180` 把所有 split 放入可见集合。代码到 `release.py:94-131` 才过滤 validation。

因此，归档中确实没有 unseen release/score/Judge/confirmation，最终 validation release 也只含 validation；但正式进程在 selection lock 前已经读取并持有 unseen，执行日志和结果报告所称的“unseen 全程未读取/封存”不成立。这违反 Plan 073 的明确盲验边界，不是单纯文案问题。

最小整改是让 validation 从不含 unseen 的冻结输入或 split-scoped reader 构建，完整 v8 只在有效 lock 后打开；测试应证明 validation 路径没有打开 unseen-bearing 数据源，而不只是检查输出 release 已过滤。

### 2. 不一致的 SELECTED 结果可以生成有效 selection lock

`selection/decision.py:303-343` 构锁时只浅查 schema、mode、freeze hash 和 terminal，未验证 result 的完整结构以及 selected、ranking、admission、artifact、run identity 的一致性；`selection/runner.py:451-456` 又接受任意 validation-result 路径。

审查使用本轮真实 `NO_GO` result，仅把 terminal/selected/ranking/reasons 改成 `SELECTED/base`，在 base 的 `admission.admissible=false` 未变的情况下，`build_selection_lock()` 仍返回 `unseen_release_authorized=true`。这会使本应封存的 unseen 被错误打开。

最小整改是增加严格的 validation-result validator，并让构锁核对 run/freeze、完整 terminal、ranking、selected candidate admission、artifact、threshold 和归档身份的一致性；一项 forged-result 拒绝回归足够，不需要签名链、数据库或复杂可信设施。

## 其他 finding

- Judge item 内容没有 GPT 标签、pair direction、模型身份或模型 score，但正式 package/batch 控制 ID 含明文 `validation`。因此报告中的“Judge 未见 split 名”不准确，且违反冻结 Judge 盲化口径。该泄漏不提供答案，也不改变不依赖 Judge 的 `NO-GO`；后续改用 opaque package ID、修正文案即可，不要求重跑 Opus。
- Judge aggregate 的通用 validator 没有把 aggregate 的 package SHA 和期望的 Opus 身份绑定到 freeze/evaluate 输入。实际 7 份 response 均为 `claude-opus-5`，package hash、覆盖和重聚合均匹配，所以当前证据有效；整改时宜做局部绑定，不建设 Judge 平台。
- freeze 只绑定 `model.safetensors`，未机器绑定实际加载目录的 tokenizer/config；typed failure CLI 路径又会因缺行先触发 cohort mismatch，无法落到已有 admission gate。两者未影响本轮零失败、既有快照的真实结果，但应在同一窄整改中复用现有 identity 能力并明确 incomplete scoring 的 `INCONCLUSIVE`/candidate failure 语义。
- watchdog 的 Windows C: 余量事实约为 `103.4 GB / 96.3 GiB`，不是交接中的 `103.5 GiB`；仍高于 80 GiB 门。任务共留有 8 次 wrapper 记录，其中正式三候选加 Plan 071 C3 path parity 的 4 次均 `rc=0`；其余为 commissioning/首次路径失败，日志已有说明。
- 执行日志记录 publication-critic suite `167/167`，交接摘要写成 `184`，两者口径未说明。该偏差不影响功能结论；本次审查按统一文件模式实际运行了 301 项并在下方单列结果。

## 复核证据

- 从正式 freeze、validation release、base/C1/C3 raw scores 和 Judge aggregate 重建 validation result，与归档对象完全相等；canonical SHA-256 为 `2b36eb4b408ff9a1a6a9830429fb806e9e2df1e54b6374755b98febb3cc98915`。
- operating points 为 base/C1/C3 `105/21/43`，全曲线最佳 balanced accuracy 为 `0.666/0.524/0.616`，均低于冻结 `0.75`。正式 terminal 为 `NO_GO`、selected 为 null。
- tracked JSON 由归档 result 重建后逐字节一致，SHA-256 均为 `f97fcdcc78c9932dd96eb17c419ef29bf574649d7b67c1c497e861daa2eee8e4`。
- Judge 7 批共 55 个 verdict，模型身份均为 `claude-opus-5`；GPT/Opus 一致 53/55。ignored Plan 073 资产为 54 文件、18 目录、2,012,268 bytes，文件 `0600`、目录 `0700`、无 symlink；没有 selection lock 或 unseen 产物。
- 定向验证：Plan 073 focused `44/44` 通过；全部 `test_publication_critic*.py` 为 `301` 项通过、`1` 项 skip；Plan 071 comparability 定向 `17/17` 通过。未加载模型，未运行 Cargo、Docker 或 unseen。
- Plan 069 与当前 main 的新增路径不触及 `eval/`、`training/` 或 Publication Critic；未见由 Plan 073 引入的跨任务回归或工作树污染。

## 代用户作出的决定

1. 接受当前三候选质量事实和 `NO-GO` 产品结论；不把 base 作为未达标兜底，不生成 selection lock，不释放 unseen，不解锁 M3-D。
2. 当前分支在上述两个阻塞项完成窄整改并复验前不合并；无需建设审计、签名、registry 或第二套评价体系。
3. 不重跑三候选模型或 Opus。现有 validation release 输出未混入 unseen，冻结规则先于候选输出，`NO-GO` 又可由 archived scores 独立推出；整改后用现有 raw 证据重建结果、运行 focused tests，并如实保留本次形式边界偏差即可。
4. Judge 的 `validation` 控制 ID 泄漏按非实质偏差处理：修代码和报告，不因其内容重问 Judge。任何未来 unseen campaign 仍必须由有效 lock 首次释放，不得沿用当前有缺口的门禁。

本审查只提交 Plan 073 worktree；未合并、未推送、未归档分支。
