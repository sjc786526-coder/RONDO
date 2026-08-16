# RONDO Multi WBS 缓存合同定向验收

日期：2026-08-16 ｜ 验收对象：`worktree-038-multi-wbs-restructure@6ae15e4`

## 结论

**验收通过；WBS 重构任务目标完成。**

本轮只复验 `6ae15e4` 新增的缓存布局合同及其 M-1 完成门，没有重新扩大审查已经通过的其余设计语义。
合同第 17 条的方向、源码边界与性能取舍均准确，没有新增正确性或功能性阻断项。

## 定向复验

1. **稳定前缀与动态后缀：通过。** OpenAI Prompt Caching 依赖完全一致的 prompt prefix，官方建议把稳定的
   instructions、tools、schema 与共享内容放在前面，把请求特有的易变内容放在其后：
   <https://developers.openai.com/api/docs/guides/prompt-caching>。WBS 据此把稳定、版本化的团队协议与每轮变化的
   Active World Index 分开，避免高频投影变化使其后的整段历史失去前缀复用机会
   （`doc/WBS/multi-agent-trusted-evidence.md:79-84`）。这澄清的是原设计“类似系统提示词”的生命周期语义，
   没有把动态数据错误地固定到请求开头。

2. **挂载位置：通过。** WBS 写的是“最后一个协议安全位置”，不是脱离协议结构的绝对字节尾部。
   当前源码先由 `for_prompt` 规范化 history 并维护 tool call/output 配对
   （`multidev/codex-rs/core/src/context_manager/history.rs:325-336`），再由
   `attach_pending_to_prompt` 附加 prompt-only 工具元数据，随后才进入 `build_prompt`
   （`multidev/codex-rs/core/src/session/turn.rs:1339-1358`）。合同要求投影位于已接纳的本轮正常输入之后，
   不拆配对、不重排历史，和这条真实组装顺序一致；具体函数与消息 role 仍留给 M-1 plan，没有过早锁死实现。

3. **retry 与上下文预算：通过。** 新合同没有削弱既有要求：同一次逻辑 sampling 的全部 provider retry 继续复用
   同一份不可变 projection snapshot，投影仍为 request-only、不写 history/rollout，并计入整次请求余量
   （`doc/WBS/multi-agent-trusted-evidence.md:71-91,171-176`）。因此不能只在首次外层 input 挂一次，
   也不能用缓存优化绕开近窗口 overflow。

4. **两套复用机制的区分：通过。** 服务端 prompt prefix caching 与本仓库 WebSocket
   `previous_response_id` 增量复用不是同一机制。后者要求当前 input 严格扩展“上次 input + 上次响应 items”
   （`multidev/codex-rs/core/src/client.rs:1184-1225`）；上一轮 request-only 投影不会进入下一轮 history，
   所以严格扩展通常会在该位置失败。WBS 已诚实记录此代价，没有承诺“放在尾部就能命中所有缓存”。

5. **正确性优先的取舍：通过。** 不为维持 WebSocket 增量复用而持久化、重复携带或累积旧投影；不把团队 revision
   编入现有 session-scoped `prompt_cache_key`
   （当前默认键见 `multidev/codex-rs/core/src/client.rs:483-487,916`）；缓存命中、延迟与成本只作后续真实运行的
   观测指标，不作为 M-1 或其他阶段的完成门。这是轻量且可逆的选择，没有新增缓存设施。

6. **文档一致性：通过。** 设计合同编号 1–30 连续；新增第 17 条后，M-3 权限引用与候选池并发 mutation 引用已同步
   调整为第 23/19 条，M-1 明确引用第 17 条。`git diff --check bce789b..6ae15e4` 无输出。

## 代为裁决

- **采纳**稳定协议前缀、动态投影置于最后一个协议安全位置的原则，并把它作为 M-1 必验行为。
- **接受**当前 WebSocket 增量复用在启用 request-only 投影后通常失效；第一版不为此改变投影语义。
- **不引入**team revision cache key、旧投影累积、provider-specific breakpoint 或缓存命中硬门。若真实运行证明损失显著，
  再以性能任务单独优化，但不得破坏投影新鲜度、retry 一致性、不可持久化与总上下文预算。
- **无需用户继续确认。** 执行者没有留下尚待拍板的缓存设计问题。

## 验证与交付边界

- 已只读核对官方缓存规则、`multidev` request/retry/WebSocket 组装源码、WBS 差异与交叉引用。
- 纯文档验收；未运行构建或测试，未修改 WBS/源码，未合并、未推送。
- 本报告是本轮唯一新增文件，尚未提交。

## 状态

- **验收：通过。** `6ae15e4` 的缓存新修订正确且边界诚实。
- **任务目标：完成。** Multi WBS 重构已达到预期，可进入提交本报告及后续合并交付流程。
