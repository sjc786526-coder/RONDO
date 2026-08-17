# Plan 039 / Multi M-2 最终验收

## 结论

- 验收对象：整改提交 `3da5412`（父提交为首轮审查报告 `b2a9fe6`，主体实现为 `0c92b59`）。
- **验收状态：通过。** 首轮发现的三项通知恢复缺陷均已在领域源头闭合，新增回归准确复现原失败场景；未发现新的
  M-2 功能阻断。
- **任务目标：完成。** Root 选择 Event、canonical 可见性/指派先成立、紧凑通知经三种既有投递语义到达目标、
  目标读取并扩展同一多作者 chain、Root 再获协调机会、指派按活动谓词结束，以及通知失败可见和幂等恢复的完整纵切
  均已实现。
- 成果仍只在专用工作树，未合并、未推送、未删除工作树；这不影响本次实现与验收完成，集成需用户另行批准。

## 三项阻断复验

1. **业务去重已稳定绑定 retry identity。** 同 Event/target/相同指令的新 identity 会写入共享 `committed` 并指向
   既有 route；原 assignment 结束后重放仍返回该 ended route，不创建新对象，且该 identity 不能再用于 publish。
   不同 note 返回 `AssignmentInProgress`，不再静默丢掉 Root 的新指令。比较前使用与 canonical 写入相同的 clamp。
2. **精确重放读取当前 canonical delivery。** route 账本只保存 `RouteId`，重放在同一 store 锁内重新取得当前
   dispatch 与 revision；`Pending -> Failed -> replay` 直接回归证明失败不会再被旧 `pending` 覆盖。
3. **未授权重发在任何副作用前拒绝。** `route_dispatch` 与 `record_delivery` 统一为 original-router-only；产品
   handler 必须先取得授权 dispatch 才能进入加载/发送链。真实成员 Session 的产品测试断言 target 调用后通知数不变，
   同时确认 target 仍可读取 Event、结束自己的指派。

首次 route 现在从同一 `DeliveryOutcome` 返回 delivery 与 revision；信息型 notice 明确“没有要求你做什么”，贡献仅为
可选能力，只有 assigned 分支要求 publish/end。两项首轮低风险建议也已正确收紧。

## 替用户作出的决策

1. 接受 route retry 账本只保存 `RouteId`、重放时读取 canonical route；这比同步两份可变快照更小、更稳，不增加
   outbox、持久化或可靠投递设施。
2. 继续采用“同一 Event/target 最多一个进行中指派”：相同 canonical 指令可作为 alias 幂等复用，不同 note 明确
   拒绝；不为此引入多重同目标 assignment 或指令更新协议。
3. `retry_notice` 最终确定为 Root/original-router-only；target 保留读取、贡献和结束自己指派的权限。
4. 接受 duty 推导 `trigger_turn`，运行中/空闲由既有 `active_turn`/pending-work 路径裁决；不增加竞态的 status 快照。
5. 接受 notify 文案保留“可以自愿贡献”的能力说明，只要明确没有任务要求且不唤醒、不进入活动视图。
6. 当前领域回归已直接覆盖 delivery/revision 重放，产品 handler 回归已覆盖发送前拒绝；不再为同一事实复制更多产品
   测试，也不重跑 416 项 tools、99 项 context 或全 workspace。

没有遗留事项需要用户在 M-2 实现层面另行决定。

## 独立验证

- `UV_CACHE_DIR=/home/sjc/desktop/RONDO/.uv-cache just fmt-check`：通过。
- 清除大小写 `HTTP(S)_PROXY`/`ALL_PROXY` 后，`just test -p codex-team-state`：**78/78 通过**，0 skipped，
  run `687f8595-18b5-43dd-a409-8f00efd4ec68`。
- 同样环境下，`just test -p codex-core --test all -- suite::team_world_state suite::team_routing`：
  **12/12 通过**，1135 skipped，run `bde905bc-d6bf-4cf5-a675-beaa3fe48d39`。
- 新增关键产品回归
  `tools::handlers::team_tools::route::tests::a_target_cannot_resend_its_own_notice_and_nothing_is_sent`：
  **1/1 通过**，run `93fecfca-e6db-4a00-93fb-62d65514f25a`。
- 三组 Rust 测试均经仓库共享构建锁、cgroup 与资源看门狗，stop/cleanup 均为 `none`。未重跑执行者已报告通过的
  416 项 tools、99 项 context 和 package fix；未运行全 workspace、Docker、真实 API、本地模型或付费测评。

## 交付状态

本轮只新增本验收报告并窄同步 Multi 子 WBS 当前状态；未修改实现、Plan 039、顶层 `doc/WBS.md`、
`doc/WBS-COMPLETED.md`、main 或其他工作树。验收时 `main` 与 `origin/main` 均为 `8852273f` 且主工作区干净。
工作树将在提交本报告后停止，等待用户决定合并与推送；M-3 仍按 WBS 在 M-2 集成后串行进入。
