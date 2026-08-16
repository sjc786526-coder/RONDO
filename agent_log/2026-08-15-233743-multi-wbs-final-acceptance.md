# RONDO Multi WBS 最终验收与缓存布局裁决

日期：2026-08-15 ｜ 验收对象：`worktree-038-multi-wbs-restructure@bce789b`

## 最终结论

**验收通过；本次 WBS 重构任务目标完成。**

`bce789b` 已实质关闭上一轮 6 项阻断与 1 项清理，未发现新的状态语义、权限、阶段依赖或可空过验收问题。
架构、29 条合同和 M-1 → M-5 主顺序可以接受。用户补充的缓存建议方向正确，但需按真实源码收窄为
“最后一个协议安全位置”，不能把“绝对尾部必然命中缓存”写成跨 provider 的正确性承诺。

本轮只读核对 WBS、整改日志、`multidev` 请求组装与缓存复用源码，并新增本报告；没有修改 WBS 或源码，
没有构建、测试、Docker、真实 API、合并或推送。

## 七项整改复验

1. **整次请求预算：通过。** 合同 16 与 M-1 完成标准已要求 projection 计入整次请求上下文余量，包含 near-limit
   用例，超限时先显式省略或走已有 compaction，不得由 projection 顶爆请求
   （`doc/WBS/multi-agent-trusted-evidence.md:76-78,158-161`）。
2. **M-5 真实工作流：通过。** 第一道门同时要求冻结工作流达到自身预冻结完成标准、协作功能真实发生；
   功能关闭、没有调用团队工具或工作流失败均不能通过。orphan 留在 M-4 定向验收，不强迫正常工作流制造异常
   （`:213-223`；顶层 `doc/WBS.md:189` 已同步）。
3. **生命周期词汇：通过。** producer `open/closed`、独立 Root 退休终态、Root `pending/tracking/resolved` 的含义，
   普通参与者默认 pending 与 Root 自建默认 tracking 均已冻结（`:48-53`）。
4. **团队实例与历史：通过。** 历史已限定在当前团队实例存续期内追加式保留；同一存活 Root 树的 residency reload
   保持原实例，只有无对应 TeamState 或实例不匹配才 reset（`:38-44,162-164`）。
5. **M-2：通过。** assignment 结束已成对验 active 保留与退出；running/idle 三类投递意图完整，`end_assignment`
   做成空操作不能通过（`:174-181`）。
6. **M-3：通过。** 非空支持类别、每类正常下钻、真实 Version-Fact 关联、全部 Unavailable 禁止冒充成功，
   以及 sibling 越权拒绝均进入完成标准（`:190-197`）。
7. **实时 WBS 清理：通过。** 候选池中的修订历史括注已删除，只保留当前触发条件（`:226-244`）。

## 缓存建议的源码判断

### 可以采纳的原则

OpenAI 官方文档说明，缓存命中依赖完全一致的 prompt prefix；静态 instructions、tools、schema 与共享上下文应稳定，
变量内容应放在可复用前缀之后：<https://developers.openai.com/api/docs/guides/prompt-caching>。
本仓库也把“避免频繁修改上下文造成 cache miss”列为模型上下文规则（`multidev/AGENTS.md:92-101`），并已有测试
要求后一请求保留前一请求的完整稳定前缀（`core/tests/suite/prompt_caching.rs:500-543`）。

因此应把两类内容分开：

- **稳定协议**：Event/Version 含义、生命周期、mutation 使用规则和工具契约，放在参与者稳定、版本化的
  instruction/prefix 层；未登记的 helper 不获得该能力。
- **动态数据**：本轮 Active World Index、team instance/revision、overflow manifest，保持 request-only，
  放在本次完整正常输入之后的最后一个**协议安全位置**，使变化尽量只影响末尾动态后缀。

### 对当前源码的精确落点

源码的正常路径先把已接纳的 pending input 记录进 history（`session/turn.rs:276-286`），每次 sampling/retry 再通过
`for_prompt` 生成并规范化历史（`:1339-1345`；`context_manager/history.rs:325-336` 保证 call/output 配对），随后
`attach_pending_to_prompt` 为已有工具输出附加 prompt-only metadata（`:1346-1352`），最后才 `build_prompt`。

因此 M-1 plan 应采用以下约束，而不是只写“放末尾”：

1. 每次逻辑 sampling 只捕获一次不可变 projection snapshot。
2. 每个 provider retry 都在 history 规范化、call/output 配对和工具输出 metadata 附加完成后，追加同一 snapshot，
   再进入 `build_prompt`；不能只挂在外层首次 input，否则 retry 会丢失。
3. projection 不得越过尚未接纳的 pending input，不得插入或重排 tool call/result，不写 conversation history/rollout。
4. projection 继续服从整次请求预算、显式 overflow 和 participant fail-closed。

具体函数、消息 role 和渲染类型留给 M-1 plan，不写死在长程 WBS。

### 必须接受的缓存取舍

“动态后缀”有利于服务端最长公共前缀缓存，但**不能保证所有缓存/传输路径都命中**。当前 WebSocket 的
`previous_response_id` 增量复用要求“上一请求 input + 上一响应 items”严格等于下一请求前缀
（`core/src/client.rs:1184-1225`）。request-only projection 在上一请求中位于 history 与响应之间，下一轮又不在 history，
所以该严格增量复用通常会失败。

**本轮代为裁决：**

- 正确性优先，不为保住 WebSocket 增量复用而把旧 projection 持久化、重复携带或改成累积 patch；旧投影不能残留
  在模型上下文中冒充当前状态。
- 保持现有 session-scoped `prompt_cache_key`，不要把 team revision 编进 key；revision 只属于动态 projection 内容。
- 缓存命中率、`cached_input_tokens`、延迟与成本只作后续真实运行的观测指标，不作为 M-1 正确性门，也不提前引入
  provider-specific explicit breakpoint。若真实数据证明 WebSocket 增量损失显著，再单独优化，不能反向破坏
  request-only、snapshot 新鲜度、retry 一致性和总预算语义。

## 状态判定

- **验收：通过。** `bce789b` 的设计与整改正确，可以进入合并交付流程。
- **任务目标：完成。** WBS 已达到预期的宏观阶段规划、稳定语义与可执行完成边界。
- **缓存裁决：非阻断的 M-1 工程约束。** 采纳稳定前缀/动态后缀原则，并按上述源码安全边界落地；
  不把实际 cache hit 或 WebSocket transport reuse 伪装成设计已保证的能力。
- **交付边界：** 本报告是本轮唯一新增文件；执行者分支仍未合并、未推送。
