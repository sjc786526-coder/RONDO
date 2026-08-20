# Plan 044 / M-5 v6 再整改独立验收

- 日期：2026-08-20
- 验收对象：`796eb4e27ec112586a47e02cfe8b9437bd6cb789`
- 范围：13:00 审查提出的 Gate 1 协议判据、terminal stop、首请求前恢复，以及本次关联改动的局部回归
- 边界：未修改有效代码；未调用真实 API、Docker 或重型 Cargo；未重跑正式/canonical 测评

## 结论

**NO-GO。验收不通过；本轮“完成正式付费门前整改”的任务目标失败。**

上一轮两项 resume P1 已正确关闭，Harbor/Docker 残留的 fail-closed 边界也合理；但 Gate 1 新判据仍有一组正式启动阻断：它会把幂等重试误认成 evidence 后新增的第二 Version，同时把合法的跨线程提交/唤醒交错误判失败。前者可让正式 Gate 1 假通过，后者会无故消耗最多 6 个尝试并让实际完成协议的模型失败。

P0=0；P1=1 组（两种相反方向的判定错误）。当前不能开始正式 Gate 1，Gate 2 继续不得启动。

## P1：Gate 1 对 canonical mutation 与异步 wrapper 完成边界的建模仍不正确

### 1. 幂等 `team_publish` 重试可伪装成 evidence 后新增 Version

`predicates.py` 已要求第二次 publish 返回不同于首次的 `version_id`，但没有检查结果里的 `deduplicated`。产品明确允许相同 `request_id` 的稳定重试返回旧 Version，并标记 `deduplicated=true`；这种重试不会新建 Version，也不会产生新的 publish revision。

独立内存反例按以下顺序构造：

1. 成员首次发布 `v1`；Root 发布并 route。
2. 成员在调用 `team_evidence` **之前**已经真实发布 `v3`。
3. evidence 后成员用相同 request identity 重试，返回旧 `v3`，`deduplicated=true`。
4. Root update。

当前结果：

```text
dedup_retry_after_evidence passed=True
predicates={spawn_member: True, event_with_two_versions: True, two_authors: True,
            team_route: True, team_evidence: True, root_resolved: True, root_woken: True}
```

因此当前判据仍不能证明“成员在 evidence 成功后追加了第二 Version”。同类风险也适用于被计入协议的首次/Root publish 和 route：被计入 canonical mutation 的调用都必须明确是 `deduplicated=false`，不能用稳定重试替代本轮动作。

### 2. 跨线程 `ToolCallEnded` 被误当作 canonical mutation 提交时刻

当前判据强制：

- member publish 的 trace end 早于 Root wait 的 trace end；
- route 的 trace end 早于 member evidence 的 trace start；
- second publish 的 trace end 早于 Root update 的 trace start。

这些都是 Root 与 member 两个线程之间的 wrapper 边界，不等于 team store 的提交顺序。产品实际先在 store 中提交 mutation、写入 revision/唤醒或投递，再返回 handler；trace end 还位于后置 finish/结果记录之后。于是 Root wait、member evidence 或 Root update 完全可能已经基于成功提交的状态合法开始/结束，而前一个线程的 wrapper 尚未写出 end event。

保持 inspect-log canonical revision 顺序完全正确，仅交换合法的跨线程 wrapper 交错后，当前判据稳定拒绝：

```text
wait_end_before_publish_wrapper_end passed=False
evidence_starts_before_route_wrapper_end passed=False
update_starts_before_second_wrapper_end passed=False
```

v6-r2 本身的 first publish 为 `35..37`、Root wait 为 `23..38`，两者只差一个 trace event；调度稍有变化就会把同一语义判成失败。这不是要求模型遵守协议，而是把调度偶然性错误加入验收。

### 最小整改要求

不新增复杂设施，只调整现有机械判据：

1. 被计入协议的 publish/route mutation 必须有完整结果且 `deduplicated is False`；补“提前创建 v3、evidence 后 dedup retry v3”负例。
2. canonical mutation 的先后以已有 inspect-log actor/thread/target/revision 为准；trace end/start 只约束同一 actor thread 的真实调用顺序。
3. Root wait 与首次 member publish 使用“调用区间发生重叠 + exact member publish wake log + Root wait 返回 TeamActivity”证明唤醒，不要求 member wrapper 必须先写 end。
4. 对 route→evidence、second publish→Root update 补三个合法跨线程交错正例，确保 canonical revision 正确时不会因 wrapper 调度假失败；原有 actor、event、Fact、delivery、不同 version_id、零 Direct 与明文门禁不得放宽。
5. `_resolved_version_id` 可顺手由“列表恰好一个元素”收敛为“请求/返回中存在唯一匹配的 member Version 更新”；合法批量 update 不应假失败。这是同一函数内的 P2，不另起设施。

## 已通过的整改

- terminal budget/capacity stop 在 requested-but-unarchived 恢复中保持 `budget_stopped`，Gate 1/2 均不再领取新 attempt，重复恢复不重复归档。
- Gate 2 的 per-run request cap 仍按合同作为槽级 retryable infra；没有被误升级成全批预算停止。
- Gate 1 与 Gate 2 的 pristine、精确 pre-Harbor 自有产物可各追加一次 abandoned infra 并进入下一 attempt；未知、错型和 symlink 继续 fail-closed。
- 已出现 Harbor trial dir 或 exact Docker/Compose 残留时保留 fail-closed 是合理边界。瞬时探针为空不能证明旧 Harbor 进程已经死亡；后续由执行 AI 在持锁状态下做受监督精确处理即可，不需要建设自动清理系统。
- provider frozen preflight、v6 正式 namespace、archive/ledger/receipt 顺序和同一 v6 Gate 1 pass 后才能进入 Gate 2 的主线未见回归。
- runtime-v4 产品代码和锁未被本提交修改。

## 独立验证与资产状态

- 定向轻量复跑 101/101：`MultiM5PredicateTests`、`MultiM5ResumeTests`、`CodeModeEvidenceTest`、`DockerCounterTests` 全通过；其中 DockerCounter 全部使用 fake executor，没有运行 Docker。
- `uv lock --check` 通过；ready 独立复跑为 `ready=true`、`formal_batch_identity.status=not_started`。`just` wrapper 因审查沙箱不能写 `/run/user/1000/just` 而未启动，随后执行了配方内完全相同的底层命令；该环境错误不是项目失败。
- 没有重复全跑执行者的 179 项，也没有重跑 loopback、v6-r2、Rust、Docker 或真实 API。现有绿色测试缺少上述 dedup 与合法交错用例，故不能抵消反例。
- v6-r2 确实是 archive 第二行追加，旧行未覆盖；r2 raw/verdict 与 archive event 对应，七谓词全真。但它只证明当前一次调度下线路可运行，不能关闭本报告的判据反例。
- 正式 v6 ledger、隐藏锁、identity receipt、phase-b-v6 archive、`m5-g1-v6-paid-a1..a6` 与 Gate 2 v6 资产均不存在。旧 `m5-g1-paid-a1..a3` 是不带 v6 前缀的历史测试污染，不与正式 v6 run id 相交。
- 写入本报告前：任务 worktree tracked clean，`HEAD=796eb4e`；主工作区 `main=origin/main=45efac6` clean。未合并、未推送。

## 替用户作出的决策

1. **暂不授权正式 Gate 1/2。** 当前阻断是有效样本判定错误，不是账本保守或审计扩张；固定中转余额不能消除假通过/假失败。
2. **保留 pre-Harbor 自动换槽、Harbor/Docker 残留受监督处理的现有边界。** 不要求无监督删除容器、网络或卷。
3. **继续沿用 v6，不为本次窄改另起 v7。** 正式 v6 从未启动；将下一次通过验收的提交视为最终 preformal v6 冻结点，此后正式运行开始便不得原位改写合同。
4. **修复后新增 append-only `v6-r3` rehearsal identity，不覆盖旧 v6/v6-r2 raw 或 archive 行。** 旧 rehearsal 行只记 lock id、未记 harness commit 的歧义在 preformal 阶段接受，不扩建证据系统。
5. **测试继续单进程串行。** 增加上述少量正反例后，运行三个 M-5 模块（179 加新增用例后的合理计数）、eval-lock、ready、loopback 和一次 v6-r3 即可；无需 Rust、Docker 或真实 API。
6. `doc/WBS/multi-agent-trusted-evidence.md` 仍写 162/162 和旧 v6 rehearsal，应在本次窄修中更新为当前 179/179、v6-r2/后续 r3 与 terminal/Harbor 边界；只替换当前事实，不堆历史。
7. Harbor 已返回但结果 parse 失败时未把已有 Docker evidence 带入 infra 行，保留为 Gate 2 前的 P2 观测性改进；它不会假通过或继续消费，本轮不将其扩大为 Gate 1 阻断。

## 再验收条件

1. deduplicated mutation 不再被计入冻结协议，反例转红。
2. 三个合法跨线程交错转绿，同时原有乱序、错误 actor、错误 Fact、复用首次 Version 和 Direct 反例继续转红。
3. 串行轻量门禁与新的 append-only v6-r3 通过；正式 v6 资产仍为 not_started。
4. 同步次级 WBS 当前口径并再次确认任务树 clean。

满足后再做一次只聚焦 Gate 1 判据的窄复验；通过后才可由用户明确授权真实 API Gate 1。
