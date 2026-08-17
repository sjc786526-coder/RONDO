# Plan 039 / Multi M-2 独立验收审查

## 结论

- 验收对象：`worktree-040-multi-m2-selective-routing` 的实现提交
  `0c92b59cd40bcd37b061272ea56c17dc5779832c`（父提交 `531297c`）。
- **验收状态：不通过。** canonical-first 主链、三类投递与多作者 Event chain 已经真实跑通，但通知恢复路径仍有
  三项会破坏幂等、权威状态或 fail-closed 的功能缺陷。
- **任务目标：失败。** 这里的“失败”表示 M-2 尚未达到既定完成标准，不是否定已完成的主体实现；三项阻断均可在
  现有领域 store 与产品 handler 内窄修，无需新增审计、可信、调度或通信设施。
- 成果与本报告仍只在专用工作树；未合并、未推送、未删除工作树。当前 `main` 与 `origin/main` 均为
  `8852273fb15ba56f9f98dc600b48f1ef5fa056c0`，主工作区干净。

## 已确认正确的主体能力

- route 先 canonical 提交可见性和所需指派，再尝试发送通知；投递失败不会回滚 route。
- route grant 挂在同一 Event 上并在指派结束后保留；目标可从 canonical history 读取完整 chain，并在同一 Event
  追加 Version。活动视图按“自己的未终态 Version、自己的进行中指派、Root 未解决协调”三个理由计算。
- 真实产品测试确实经过 Agent/session/team tool/既有 communication/sampling/wait 接缝；工作指派唤醒空闲目标、
  运行中目标并入既有 turn、信息通知只排队三个执行分支均有直接证据。
- 非 Root route、未知 actor/target、跨实例引用均 fail-closed；没有引入第二套团队状态、调度器或通信协议。

## 验收阻断

### 1. 活动指派去重没有占用新的 retry identity

`team-state/src/store/route.rs:74-90` 在同一 Event/target 已有进行中指派时返回既有 route，却没有把本次
`(actor, request_id)` 写入 `committed`。因此：

1. `r1` 创建指派 A；
2. 新 identity `r2` 被成功返回为 A；
3. A 结束；
4. 原样重放 `r2` 会创建指派 B，而不是重放第一次 `r2` 的结果。

`r2` 还可被 publish 或另一种 route 内容复用，实际打破了共享 retry namespace。当前实现还会把同
Event/target 但不同 `note` 的新指令静默当作旧指派成功，目标收不到新内容。现有测试只验证第 2 步当下没有新增
对象，未覆盖结束后的原样重放和不同内容。

### 2. 精确 route 重放返回过期的 `pending`

`team-state/src/store/route.rs:59-71` 从 route 提交时缓存的 `RouteOutcome` 返回精确重放结果；该缓存建立在通知前，
delivery 固定为 `Pending`。`record_delivery`（同文件 `146-181`）只更新 canonical `TeamRoute`，没有刷新该缓存。
产品 handler 又在 `core/src/tools/handlers/team_tools/route.rs:76-82` 对 deduplicated 结果跳过投递并直接报告缓存值。

所以 canonical 已为 `delivered` 或 `failed` 的 route，在相同 request/call id 重放时都会错误报告 `pending`；尤其会
隐藏本应明确可见且可重试的失败状态。这直接违反 Plan 039 的通知失败与幂等恢复合同。

### 3. 目标 Agent 可先产生未授权重发副作用，随后才因无权记账失败

`team-state/src/store/route.rs:242-255` 允许 routed-by 或 target 取得 retry dispatch；产品
`team_route_update(action=retry_notice)` 随即先调用发送链。发送成功后，`record_delivery` 又只允许 routed-by，导致
目标 Agent 可以给自己发送重复 route 通知，随后 canonical 记账才报 `NotPermitted` 并保持旧状态。Root 后续重试
还会再投一份通知。

这是产品权限与领域权限不一致造成的真实副作用，不是审计设施缺失。`retry_notice` 必须在发送前完成权威鉴权。

## 窄修建议与复验范围

1. 精确 route 重放应按 retry 账本定位原 route，再从 canonical `TeamRoute` 生成当前 dispatch；不要把可变 delivery
   永久冻结在提交时的缓存结果里。
2. M-2 保持“同一 Event/target 同时最多一项进行中指派”。对内容相同的新 identity，可以返回同一 route，但必须把
   identity 稳定绑定到该 route；对 `note` 等内容不同的新请求，明确拒绝为“已有进行中指派”，不要静默吞掉新指令。
3. `retry_notice` 只允许 Root/original router，且必须在任何发送或加载目标的副作用前拒绝其他身份；目标仍可结束
   自己的指派并读取 Event。
4. 只需补三组聚焦回归：delivery 更新后的精确重放、去重 alias 在 assignment 结束后的重放与跨类型复用、target
   重试在消息入队前被拒绝。无需扩大到全 workspace 或新建审计/可靠投递系统。
5. 同批可顺手收紧两个低风险输出问题：信息型 notice 不应无条件要求目标追加 Version；首次 route 返回的 revision
   应与返回的最终 delivery 属于同一 canonical 快照。两项不单独构成本轮失败原因，也不值得引入新设施。

## 替用户作出的决策

1. 接受执行者按 duty 推导 `trigger_turn`，由既有 `active_turn`/pending-work 执行面原子决定“并入运行中 turn”或
   “空闲时起下一轮”；不增加基于 `AgentStatus` 快照的竞态分支。
2. 接受同一 Event/target 最多一个进行中指派的轻量策略，但不同内容不能被静默合并；相同内容的业务去重必须稳定
   绑定 retry identity。
3. 接受 publish 与 route 共用 `(actor, request_id)` 命名空间，跨类型复用继续拒绝。
4. 将 `retry_notice` 决定为 Root/original-router-only；target 可 `end`，不可重发 Root 发起的通知。
5. 接受清除测试子进程的 `HTTP(S)_PROXY`/`ALL_PROXY` 后访问 loopback wiremock；不修改宿主代理或测试框架。
   接受通过 mock server 完整请求日志断言多 Agent 请求，不围绕 `ResponseMock::single_request()` 扩建计数设施。
6. 本轮不为 route 的 stale revision 增加新冲突协议或审计体系；只要求现有返回值自洽并修复上述核心恢复语义。

没有遗留事项需要用户另行选择；整改可按以上决定直接执行。

## 独立验证

- `UV_CACHE_DIR=/home/sjc/desktop/RONDO/.uv-cache just fmt-check`：通过。
- 清除大小写 `HTTP(S)_PROXY`/`ALL_PROXY` 后，`just test -p codex-team-state`：**75/75 通过**，run
  `ac4a9020-327b-4591-ac0f-e748111ad4a4`。
- 同样环境下，`just test -p codex-core --test all -- suite::team_world_state suite::team_routing`：
  **12/12 通过**，1135 skipped，run `e463a69e-1a23-4796-8429-b39482548995`。
- 两组 Rust 测试均通过仓库共享构建锁、cgroup 与资源看门狗；stop/cleanup 均为 `none`。未重跑执行者已报告的
  415 项 tools、99 项 context、9 项 team，也未运行全 workspace、Docker、真实 API、本地模型或付费测评。
- 现有门禁通过只能证明已覆盖链路没有回归；本报告三项阻断对应的场景尚无测试，因此不会被 75/75 与 12/12 捕获。

## 交付状态

本轮只新增本审查报告，未修改实现、Plan 039、WBS、WBS-COMPLETED、main 或其他工作树。实现提交
`0c92b59` 保持未合并、未推送；M-2 应在上述窄修与定向复验通过前保持未验收，且不提前进入 M-3。
