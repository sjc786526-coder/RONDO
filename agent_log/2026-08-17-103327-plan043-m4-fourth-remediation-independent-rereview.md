# Plan 043 / Multi M-4 第四轮整改后独立复验

日期：2026-08-17 ｜ 审查对象：`worktree-043-multi-m4-coordination-closure@def76b6` ｜ 前次复验：`c3e9563` ｜ 基线：`main@af1063d`

## 结论

- **验收不通过**：跨 await 的 store-transition token、取消收口、Root 退休拒绝和 midpoint fail-closed 均已正确实现；但 token 的
  active 计数与 availability generation 仍以两次独立原子写更新，而 snapshot 不取得同一 availability gate。线程可在两次写之间
  观察到“新分类、旧 epoch”，同一 dump cursor 因而仍可能续接不同 availability 内容。
- **任务目标失败（当前提交尚未完整实现预期）**：`def76b6` 已消除整个删除区间内的 recoverable/unavailable 双义，但没有消除 begin/end
  两个原子边界上的同 epoch 双义，确定性状态转储与 availability state version 合同仍未闭合，不能按当前提交合并或宣称 M-4 完成。
- 这是现有同步接缝内的一个窄 correctness 缺口。让 snapshot 在分类前后短持现有 gate 原子采样 `(generation, active)` 即可；不需要事务、
  审计设施、签名、持久化或新的可信体系。

## 已确认整改有效

- `StoreTransitionGuard` 能跨 `await` 保持 active；显式 `finish` 与 `Drop` 都只收口一次。错误或任务取消会走 Drop，多 token 通过计数器
  保持“任一仍存即 active”。
- `delete_stored_thread` 与正式 app-server `thread/delete` 都持有 token 覆盖真实 store 删除，没有发现绕过路径。
- transition 已完整开始且尚未结束的期间，classify/snapshot 统一返回 `unknown`；Root 退休持同一 gate 检查 active，期间拒绝退休，结束后
  旧 snapshot 又由 live epoch CAS 拒绝。当前反例不会导致错误退休。
- 上轮已通过的 explicit-resume recoverability、dead-resident 清理、VersionFact 有界分页、TeamInstanceId cursor、裸 offset 拒绝、
  ThreadId 身份字段、lifecycle no-op、observe generation、退休元数据与 publication stats 均未回退。

## 唯一验收阻断

### P1：snapshot 可在 active 与 generation 两次原子写之间发布双义 epoch

`ThreadManagerState::begin_store_transition` 在 `core/src/thread_manager.rs:1324-1327` 持 gate 执行 `active++`，随后才 `generation++`；
`end_store_transition` 在同文件 `:1329-1334` 先 `active--`，随后才 `generation++`。这能保护同样取得 gate 的 Root retirement，却不能把两次
原子写合成对无锁读者不可分割的一次状态切换。

`AgentControl::producer_availability_snapshot` 在 `core/src/agent/control/availability.rs:34-68` 不取得 gate，只分别读取 generation 与 active。
即使所有原子使用 `SeqCst`，另一 OS worker 仍可在相邻两次原子操作之间运行，因此存在两个可达时序：

1. begin 前已经合法发布 `recoverable_unloaded/E0`；begin 完成 `active++` 但尚未 `generation++` 时，snapshot 两次读到 E0 且 active，返回
   `unknown/E0`；
2. transition 中已经合法发布 `unknown/E1`；end 完成 `active--` 但尚未 `generation++` 时，snapshot 读取删除后的 store，返回
   `unavailable/E1`。

Team-state dump cursor 在 `team-state/src/store/observe.rs:37-53` 校验 instance、revision、availability epoch 与 observe generation；上述切换
不改变后三者中的其他项，所以旧 cursor 会被接受并静默拼接不同 availability 页面。新增 midpoint barrier 测试只在 begin 已完整返回后、
finish 尚未调用时观测，正确覆盖长删除区间，但没有也无法排除这两个边界窗口。

同类窗口也存在于 loaded map mutation 与其 post-bump 之间：writer 虽持 gate，snapshot 无锁复验仍可读到新 map 与旧 generation。因此只交换
active/generation 的写入顺序不够。

处理要求：增加一个短临界区读取 helper（或等强轻量实现），在现有 availability gate 下同时读取 generation 与 active。snapshot 开始和
分类后的最终复验都用该 coherent marker；active 时直接返回全员 unknown，非 active 时仅在前后 generation 一致且最终仍非 active 才返回，
否则重试。锁只包同步读取，不跨 `await`。这样会同时线性化 token 边界与现有 map mutation，不引入新设施。

## 替用户作出的决策

1. 保留 `def76b6` 的 RAII token、active 期间 unknown、Root retire 拒绝以及两条真实删除路径；下一轮不重做 producer availability 架构。
2. 采用“snapshot 短持现有 gate 取得 coherent marker”作为优先最小修法；不接受仅交换两次原子写顺序，因为仍有可观察窗口。执行者可采用
   其他等强轻量方案，但不得扩展为事务、审计或可信设施。
3. 增加一条小回归验证 snapshot 的 marker 读取确实走 gate，并保留现有 midpoint 测试；随后只跑 team-state、availability/resume 与
   M-4 产品纵切，M-1—M-3 仅在接缝确实受影响时定向回归，不跑全 workspace。
4. 继续在 043 工作树窄修并提交；当前不进入 M-5，不合并、不推送。

执行者没有留下必须由用户另选的产品决策；上述取舍由本轮审查直接作出。

## 独立验证与现场

| 项目 | 结果 | 说明 |
|---|---|---|
| `git diff --check c3e9563..def76b6` | 通过 | 第四轮整改差异无 whitespace error |
| `just test -p codex-team-state --lib` | 125/125 通过 | 共享构建锁与资源看门狗；run `801521b0-49d7-4161-9aa6-8e69e3de3e33` |
| `just test -p codex-core --lib agent::control::availability` | 5/5 通过 | 2206 skipped；run `b9257eba-9cb0-4f66-afee-5fe588feef91` |
| `just test -p codex-core --lib resume_agent_restores_closed_agent_and_accepts_send_input` | 1/1 通过 | 2210 skipped；run `530215d7-4840-4c7a-a353-7f21aead8bbd` |
| M-1—M-4 产品套件 | 本轮未重跑 | 采用执行日志的 17/17 结果；避免重复较重门禁 |

首次组合过滤表达式没有匹配当前 nextest 测试名，得到 0 tests / exit 4；随后拆成上表两条命令并实际运行 6/6，故该次命令错误不计为实现
失败。未运行全 workspace、Docker、真实 API、本地模型、付费资源或测评。

复验前 043 工作树干净，`main = origin/main = af1063d` 且主工作区干净。本报告是本轮唯一产品仓库受跟踪改动；未修改实现、Plan/WBS，
未合并、未推送、未归档分支。当前 Plan/WBS 中“第四轮整改待再审查”不构成验收通过；M-5 仍未开始。
