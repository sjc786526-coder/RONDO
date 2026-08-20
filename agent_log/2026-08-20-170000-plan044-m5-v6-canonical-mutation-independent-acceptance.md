# Plan 044 / M-5 v6 canonical mutation 独立验收

- 日期：2026-08-20
- 验收对象：`ae3fc86b49381a8e171ca0c12d14d6e2bff40da9`
- 范围：15:00 审查提出的 deduplicated 假绿、跨线程 wrapper 假阴、批量 `team_update` P2，以及关联合同/资产回归
- 边界：未修改有效代码；未调用真实 API、Docker 或重型 Cargo；未重跑正式 Gate 或 rehearsal

## 结论

**GO。验收通过；本轮“完成正式付费门前整改”的任务目标完成。**

上一轮两项阻断均已关闭：被计入协议的 publish/route 必须是 completed 且 `deduplicated is False`；canonical mutation 的跨线程顺序改由产品 change log revision 证明，wrapper start/end 只承担同 actor 顺序和 wait 区间边界。未发现剩余 P0/P1，也未发现对 resume、Gate 2、正式 namespace 或 runtime-v4 的回归。

这只表示**可以申请并启动正式 Gate 1**，不表示 Gate 1、Gate 2 或 M-5 已通过。真实 API 仍须用户按项目边界明确授权；Gate 2 继续等待同一 v6 Gate 1 正式通过并单独获得 Docker 授权。

## 关键验收

### deduplicated 假绿已关闭

- first member publish、Root publish、second member publish 和 Root route 统一经过 `_committed_mutation`。
- 只有结果字段 `deduplicated` 为字面量布尔 `False` 才可计入；`True`、字段缺失、`0`、`None` 及其它类型均拒绝。
- “evidence 前已经真实创建 v3，evidence 后只对 v3 做 deduplicated retry”的上一轮反例已转红。
- v6-r3 原始 trace 中四个被计入的 publish/route 均实际返回 `deduplicated=false`。

### canonical mutation 与并发 wrapper 已分层

- 产品 fresh publish/route 会创建唯一 change-log revision；deduplicated retry 不创建新 mutation/log。
- first publish < Root publish < route < second publish < Root update 使用精确 actor/thread/target 的唯一 revision 链证明。
- 同一 actor 的依赖仍要求前一调用 end 后后一调用 start；跨线程 wrapper end 不再冒充 store commit 时钟。
- wait 与首次成员 publish 使用区间重叠、精确 `member_publish` wake log、manifest Root thread 和 TeamActivity 返回共同绑定。
- 上一轮三个合法跨线程 wrapper 交错均转绿；明确的同线程乱序、错误 actor、错误 Fact、复用首次 Version、dedup retry、Direct 和非明文边界继续转红。

### 批量 team_update

- 请求与返回中必须唯一匹配一个成功 resolve 的成员 Version；两个成员 resolve、重复同 ID、错误状态或错误版本拒绝。
- 其它不相关目标不会再使合法批量调用假失败。
- 新增正例中“Root 关闭成员 v1 的 producer 轴”在真实产品权限下不可达，因为只有作者能关闭 producer。这是合成测试样例不够真实的 P2，不会造成正式假通过：正式 trace 来自产品，产品会原子拒绝该调用；matcher 对可达批量结果本身正确。后续触碰该测试时改用 Root 自有 Version 的 producer 更新即可，本轮不阻断。

## 独立验证

- 精确窄回归：105/105 通过，包含 `MultiM5PredicateTests`、`MultiM5ResumeTests`、`CodeModeEvidenceTest`、`DockerCounterTests`；DockerCounter 使用 fake executor，没有运行 Docker。
- 三个 M-5 模块实际执行 183 项：一次串行运行中 182 项通过，唯一失败是审查沙箱不能写 `/run/user/1000/just`，使测试内 `just` 子进程在项目代码启动前返回 1，而预期为授权拒绝码 78。给该子进程配置可写、私有的 `XDG_RUNTIME_DIR` 后，原用例单独通过。因此 183 个用例均已有通过证据，该失败不属于项目或产品回归；未为此修改测试或宿主配置。
- `uv lock --check` 独立通过；ready 独立为 `ready=true`、formal identity=`not_started`，provider 固定为 `https://www.cctq.ai/v1`、`gpt-5.6-terra/medium`。
- 执行者报告的 loopback 通过已由代码/资产复核接受；runtime-v4 未变化，本轮没有重复运行 loopback。
- v6-r3 为 rehearsal archive 第三行追加；前两行和 r1/r2 raw 哈希未变化。r3 为 23 requests、20/20 code-cell completed dispatch、0 Direct/failed、七谓词全真、明文 9、dump 7 页/log 2 页，raw event 与 archive 对应。
- 未运行 Rust、Docker、真实 API或正式 Gate；费用为零。

## Git 与正式资产

- 写入本报告前，任务 worktree tracked clean，`HEAD=ae3fc86`；主工作区 `main=origin/main=45efac6` clean，未被本任务修改。
- runtime-v4 产品源码/锁未变，冻结产品仍为 `0eee6dc`。
- 正式 v6 ledger、隐藏 lock、identity receipt、phase-b-v6 archive、`m5-g1-v6-paid-a1..a6` 和 Gate 2 v6 资产均不存在。
- 旧 `m5-g1-paid-a1..a3` 不带 v6 前缀，是历史测试产物，不与正式 v6 run id 相交。
- 正式运行必须从包含本次修复的任务 worktree `ae3fc86` 启动；当前 main 尚不包含该提交。

## 替用户作出的决策

1. **接受 `ae3fc86` 为最终 preformal workflow-v6 冻结点。** v6 在正式运行前曾原位修订，旧 rehearsal 行只记同一 lock id；鉴于正式 v6 从未启动、三套 raw/行次均独立保留，此 preformal 歧义接受，不扩成 v7。正式启动后不得再原位改 v6。
2. **接受 route 的轻量并发语义。** 判据要求 fresh route 先发起、最终 `delivery=delivered`、精确 canonical route revision 早于第二成员 Version，且 evidence 与第二 publish 都真实完成；不再追踪 handler 内部“resolve target → store commit → delivery → wrapper end”的不可观测微时刻。即使极端调度下 evidence 在 route commit 前结束，route 仍已发起、最终交付并位于最终成员追加之前；对本项目的功能测评足够，不为此新增 commit-clock 设施。
3. **接受 wait/publish 必须区间重叠为 Gate 1 的偏保守合同。** 产品本身支持 publish 先发生、wait 后消费 pending wake，但受控模板要求 Root 尽快 wait，且有 6 次尝试。该边界可能产生极少量假阴，不会假阳；先不继续放宽。若正式 Gate 1 实际只因该模式失败，再按原 raw 证据窄判定，不预建更多设施。
4. **保留 pre-Harbor 自动换槽、Harbor/Docker 残留受监督精确处理。** 不实施无监督自动删除。
5. **批量 update 合成正例和 Harbor parse 后 Docker evidence 缺失均作为 P2 接受。** 前者下次触碰测试时换成产品可达样例；后者在 Gate 2 前可窄修或接受为观测性限制，均不阻断 Gate 1。
6. **技术上允许进入正式 Gate 1 授权流程，但本报告不替代付费授权。** 建议正式授权范围仅为：CCTQ Responses `https://www.cctq.ai/v1`、`gpt-5.6-terra/medium`、最多 6 次、无 Docker、计入共享 `$120` 硬上限。Gate 2 不一并授权。
7. 不要求再增加 v6-r4、重跑 Rust/Docker 或扩建审计设施；现有 v6-r3 足以作为门前线路证据。

## 当前项目状态

- 正式付费门前准备：**完成并验收通过**。
- Gate 1：未启动、未通过。
- Gate 2：未启动；必须等待 Gate 1 通过。
- M-5 总目标：尚未完成，也不能称失败；结论取决于后续两道正式门。
