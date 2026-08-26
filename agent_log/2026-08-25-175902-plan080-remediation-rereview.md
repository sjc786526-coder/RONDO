# Plan 080 / M4-C2 整改复验报告

时间：2026-08-25 ｜ 被审整改：`4b50891682fc6093b92c308c2eefe090febed45d`

## 结论

首次报告的 2 High、5 Medium、1 Low 已按其原场景实质整改；owner incarnation、Team/close 线性化点、parented child、Delete
显式 recovery、TUI preview/target、control-only attachment 与关闭态回归的主体方向正确。执行者追加发现的 post-teardown Team close
completion 失败也已在其显式分支正确收口。

但本轮复验发现 2 个仍会影响正式控制行为的 Medium、1 个关键验收覆盖 Medium 和 1 个 Low。当前结论仍为：**验收不通过 + 任务目标失败
（针对 `4b508916`，均可在原授权和现有架构内窄修）**。已有 45/45、17/17、47/47、fresh、整改 29 项、3/3、schema、fix/clippy
等证据在各自覆盖范围继续有效，本次未重跑重型测试。

## Findings

### Medium 1：query availability 与 server admission 对 Archive/Delete 不一致

- `app-server/src/request_processors/durable_session_query_projection.rs:212-279` 对 active Session 的 Archive 固定投影为 `Available`，Delete
  也不区分 residency 而固定 `Available`；archived Delete 同样如此。
- `app-server/src/request_processors/durable_session_control.rs:208-217,283-293` 却只接受
  `ObservedOwnerHere | NotObservedHere`，明确拒绝 `OwnerUnavailableHere | Unknown`。
- 正式可达场景是 canonical Root 未加载、同 Session descendant 仍加载；`observed_runtime` 会投影 `OwnerUnavailableHere`。此时整改后的
  TUI 按权威 query 正常展示 Archive/Delete 确认，server 随后确定性拒绝，重读又继续显示可用。

应统一 query policy 与 server admission：对 `OwnerUnavailableHere` 投影明确 unavailable，对 `Unknown` 保持 unknown；active/archived 的
Archive/Delete 都按其实际 admission 对齐。补一个 Root 不在、descendant 仍加载的 projection 或 public read→control 窄回归即可。

### Medium 2：accepted formal shutdown 的异常 loop 终止仍可能留下 dead mapped Root

- `core/src/session/mod.rs:951-976` 已将 formal handoff 成功发送并 commit；但之后 completion sender 丢失，或 session loop 先终止，仍统一
  返回普通 `ShutdownHandoff`。
- `app-server/src/request_processors/thread_processor.rs:1030-1044` 只对显式 `ShutdownTerminatedWithError` 做 replacement-safe
  `remove_thread_if_same`；普通 `ShutdownHandoff` 保留 mapping。
- 若 loop 在领取 pending handoff 前异常终止，或领取后 teardown future panic/取消，提交 channel 已关闭、Root 已不可运行，但 ThreadManager
  仍可持有该 CodexThread。query 又在 `durable_session_query.rs:455-492` 忽略非 running Root 并把它当冷态，形成半关闭 dead resident。

handoff 已被接受之后，loop termination 或 completion sender dropped 都应分类为 terminal unknown，并复用现有 exact-owner removal；仍返回
typed Unknown，不自动重放。显式 `RetainedError` 继续保留 owner，replacement 继续不得被旧结果移除。

### Medium 3：两个关键编排分支仍缺少直接回归

1. team-state 的 4 个直接测试已证明 snapshot/owner gate 本身正确，Close/active Archive/Delete 也静态复用同一 helper；但没有按首次审查要求
   受控注入“app-server preflight 已通过、随后 Team commit 先赢”，因此 public Close 加至少一个破坏性 lifecycle 的编排窗口仍未被测试命中。
2. 整改日志称 app-server exact-owner cleanup 邻接 `1/1`，实际 watchdog `20260825-173353-1000-1431720` 运行的是
   `source_unavailable_stays_distinct_from_an_unreadable_record`，与 `thread_processor.rs:1030-1042` 的 terminal exact-owner
   remove/preserve-replacement 分支无关。core 的 post-teardown fault test 本身真实有效，但 app-server 分支仍只有静态推断。

不需要新增测试平台。补现有层级中的受控 hook/fixture 或等强直接测试即可；日志应把该旧 `1/1` 如实称为编译/普通邻接，不再称 exact-owner
行为证据。

### Low：replacement owner 的入口错误原因仍归类为 StalePrecondition

`app-server/src/request_processors/durable_session_control.rs:101-117` 的 proof mismatch 只区分 storage/residency，其余一律
`StalePrecondition`，所以仅 owner incarnation 变化时与领域线性化点的 `NotCurrentOwner` 分类不一致。虽然已经 fail closed，但正式错误反馈
应在可明确识别时统一为 `NotCurrentOwner`；现有 replacement RPC 回归可直接收紧断言。

## 最小整改与复验

1. 对齐 Archive/Delete 的 query availability 与 server residency admission，并覆盖 loaded descendant/no Root。
2. 将 accepted handoff 后的 loop termination/completion channel loss 归为 terminal unknown；直接覆盖 app-server exact old owner 清理与
   replacement 保留。
3. 在 app-server/control 编排层受控让 Team commit 赢在 preflight 与 close barrier 之间，证明 Close 与至少一个 active Archive/Delete
   reject/unknown 语义正确且新事实保留。
4. 将明确的 owner incarnation mismatch 归类 `NotCurrentOwner`。
5. 只运行上述直接测试、受影响小范围邻接、必要 scoped fix/clippy/fmt/diff；无需重跑 45/17/47、full workspace、Docker、真实 API/模型、
   CI/PR，也无需新增 registry、relay、自动 retry、审计或可信设施。若协议/生成物没有变化，不重复跑 schema generator。

## 代用户作出的决定

- `4b508916` 暂不接受合并；整改仍属于 Plan 080 原一次性授权，不需要追加请示。
- 首次报告已闭合的 owner proof、Delete recovery 与 TUI 等部分不要求重做，也不为复验重复宽门禁；只修上述接缝与直接证据。
- lifecycle/handoff 的具体内部实现由执行者自主选择，但必须保持 RetainedError 可回滚、terminal unknown exact-owner 清理、replacement-safe 与
  no-replay；不引入第二套控制状态。
- 旧 app-server `1/1` 证据标签应诚实更正；这不否定该测试本身通过，只是不把无关测试当作 exact-owner 行为证明。

## 仓库状态

复验开始时 080 分支位于 `4b508916` 且 clean；main 仍为 `0d842e0`、origin/main 为 `305f904`，未读取或修改 079，未合并或推送。
本报告是复验者在 080 工作树中的唯一变更，提交后交回执行者继续窄修。
