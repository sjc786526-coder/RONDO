# Plan 042 / Multi M-3 补充整改独立复验

日期：2026-08-17 ｜ 复验基线：`95ef17d` ｜ 被验收 HEAD：`f16bdf3`

## 结论

**验收通过；任务目标完成。**

`eb53218` 已完整关闭上轮报告的三项残余缺陷：并行重复 `call_id` 现在以 Harness 预留的唯一 output item
identity 精确配对；Version 中超过单次输出预算的 refs 可经 `team_history` 有界分页完整取得；pending 不再按固定
条数逐出。复验未发现新的 P0/P1/P2 正确性或功能性缺陷。

本结论只覆盖 Plan 042 / Multi M-3 的工作树交付。分支尚未合入或推送，因此“任务目标完成”不等于“已进入
`main`”。

## 复验结果

### 1. 并行重复 `call_id` 已精确闭合

- `core/src/tools/parallel.rs:82-101` 在直接调用 dispatch 前为每次 invocation 预留独立 `ResponseItemId`，并把同一
  identity 写入最终 retained `ResponseItem`。
- identity 经 router/registry 传到成功、普通失败与 `PostToolUse` 拦截后的 completion note；host 丢弃结果时也按
  本 invocation 的 identity 撤销，而不是按模型可复用的 `call_id` 撤销。
- `team-state/src/store/evidence.rs:35-93` 的 note、discard、confirm 均以 producer + item identity 配对；Fact 序号
  仍在 retention confirmation 时分配。因此 completion 与 `FuturesOrdered` retention 顺序相反时，metadata、类别、
  locator 和正文也不会串配。
- `core/src/team/evidence.rs:63-74,139-180,278-289` 继续统一排除团队工具/证据读取，并只按目标 item identity
  确认和解析。团队工具、取消 filler 或另一个同 `call_id` 调用都不能消费普通工具的 pending note。

新增产品纵切真实发出 33 个本地文本工具调用，前两项并行复用同一 `call_id` 且一成一败，随后分别下钻到各自正文；
领域测试另覆盖 metadata 与 retention 反序配对。该组合足以证明原缺陷已被实质修复。

### 2. refs 第 33 条以后已可有界取得

- canonical Version 继续保存发布窗口的全部 refs；32 条上限只约束一次模型可见输出。
- `core/src/tools/handlers/team_tools/history.rs:32-102` 在完成既有 Event 可见性检查后，对每个不可变 Version 的 refs
  应用 `evidence_refs_offset`，返回本页起点、下一页 offset 与剩余数量。
- `core/src/tools/handlers/team_tools/spec.rs:138-176` 向模型说明了分页参数和续页方式。新增真实产品纵切从 publish 的
  32 条预览继续取得第 33 条，Agent 不再需要猜 Fact ID。
- 读取权限仍由 `TeamStore::history` 的 Event 可见性与 `read_fact` 的实例、producer、Event 引用关系决定；分页只暴露
  已获准查看 Version 的 authored refs，没有扩大 sibling 或跨实例权限。

### 3. pending 固定截断已取消

- `team-state/src/store/evidence.rs:35-93` 不再按全团队或单 producer 固定条数逐出 note；正式保留的支持集结果不会
  因暂存计数漏铸 Fact。
- pending 只保存 item ID、call ID、类别和工具名等轻量 metadata，不复制输出正文。正常结果在有序 retention pass
  中 confirm 后移除，被 host 丢弃的结果按 identity 撤销，团队 root tree 生命周期结束时整体释放。
- 领域测试确认同一 producer 超过 256 条 pending 仍能全部形成 Fact。当前不需要为此增加 artifact store、持久化
  队列、审计 gap 或新的可信设施。

## 代用户作出的决策

1. 接受 session 内 `ResponseItemId` 同时作为 pending 配对键与 observation locator；不要求不同 replay 生成相同
   locator 值。重放稳定性继续以 Fact 顺序及 observation-to-publication 窗口关联为准。
2. 接受 canonical Version 保存全部 refs、publish/history 单页最多报告 32 条并通过现有 `team_history` offset 续页；
   不新增通用 Fact 浏览器或审计接口。
3. 接受移除 pending 固定截断。这里正确性优先于任意经验条数上限；现有对象轻量且生命周期有明确消费/释放路径，
   无需以 warning 代替 Fact 或引入复杂持久化。
4. 接受 `PostToolUse` 已执行后正式保留的失败文本属于支持集；未知工具、`PreToolUse` 等执行前拒绝继续排除。
5. 不要求再补“latch 强制完成反序 + 同 `call_id` 团队工具/取消调用”的组合产品测试。独立 item identity 已从结构上
   关闭这些串配路径，现有领域反序测试和真实并行纵切足以验收；继续加组合设施收益不高。

执行者没有留下其他需要用户确认的产品决策。

## 独立验证

所有 Rust 测试均从 042 worktree 经仓库共享构建锁与 cgroup 看门狗运行；core loopback 测试按已知环境约束清空代理。

| 门禁 | 结果 | 用途 |
|---|---:|---|
| `just test -p codex-team-state evidence` | 23/23 | 发布窗口、权限、重复 ID 配对、超过 256 条 pending |
| 新增 `concurrent_reused_call_ids_and_evidence_ref_paging_remain_exact` | 1/1 | 真实并行重复 ID、成功/失败下钻、第 33 条 refs 分页 |
| `git diff --check 95ef17d..f16bdf3` | 通过 | 补充整改差异检查 |

未重跑执行者已通过的 541 条合并门禁、其余 19/19、全 workspace、Docker、真实 API、本地模型或付费测评；这些不是
本次定点复验的必要证据，未运行不表述为通过。

## 非阻断观察与现场

- 产品纵切没有用 latch 强制两项工具按相反顺序完成，也没有把 excluded team tool/取消调用塞入同一重复-ID 批次；
  这是覆盖选择，不是当前实现缺陷。若将来相关执行管线重构，可补一条轻量确定性 core 回归，无需阻碍本次验收。
- `ResponseItemId` 预留位于通用 direct-tool 路径，但结果在进入 history 前原本就会获得同类 identity；功能关闭时
  evidence note/confirm 仍为空操作，普通 retained 工具结果的正文、类别与 rollout 形状未改变。
- 审查期间未修改主工作区或其他 worktree，未合并、未推送、未归档分支。
