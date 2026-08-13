# 教师 Harness 性能优化铺垫调研

> 状态：只读调研结论，不是实施计划，也不代表任何候选已经验证有效。
> 调研日期：2026-08-12
> RONDO 基线：`73b05035c046c817a5c050faa9803f510856f83e`（Codex CLI v0.147.0 冻结基线）

## 1. 目的与边界

本调研服务于 `doc/WBS/teacher-harness-study.md` 的 T1-T3：比较教师 harness 与 RONDO/Codex
现状，筛出可能提高任务成功率、减少 token/时延/无效动作、且不需要大幅重构的候选方向。候选只是假设，后续是否落地必须由
测评证据决定。

本次只读取 RONDO、冻结 Codex 源码与 `reference-agent-harness/`，没有修改教师源码，没有运行 Cargo、Docker、
本地模型或真实 API，也没有触碰正在开发或积存改动的其他 worktree。教师目录是 git-ignored 的本地参考资产；本文只记录机制，
后续实现应按 RONDO 架构独立重写。Claude Code 材料虽由项目方确认是官方 2.1.88 旧版实现，但本地未附可用许可证，因此同样只学习机制、
不直接复制源码。

## 2. 先给结论

最重要的发现不是“缺少一套新 agent 架构”，而是：RONDO 已继承 Codex v0.147.0 的 compact、prompt cache、
动态工具发现、持久 shell 会话、并行工具调度、multi-agent、approval/sandbox 与重试机制；这些不值得重复实现。
当前更有性价比的真实空位是：

1. **先把已有内部遥测接入 eval**：目前已有 turn、部分 tool timing、compaction、cache 和 Guardian 指标，但没有形成可用于归因的统一测评记录。
2. **让被裁剪的工具输出可恢复**：模型看到的输出应有总预算，但完整输出应能通过安全句柄继续检索，而不是只剩 head/tail。
3. **识别重复与无进展**：先观测重复工具签名、连续同类错误、连续 compact 和无文件变化轮次，再做一次轻量提醒；不要一开始就硬停。
4. **限制成功子智能体回传体积**：现有成功 completion payload 没有真正受 `COMPLETION_MESSAGE_MAX_TOKENS`
   约束；复用可恢复输出设施后的增量改动较小，但收益取决于真实任务中的子智能体使用率。
5. **先测 prompt/cache 与并发结果可见性，再优化**：RONDO 已有 cache key 和并行执行；真正未知的是哪个 prompt 层破坏缓存、
   以及工具完成到按序记录是否存在显著尾巴。
6. **在完整请求边界预检，并只做一次无副作用恢复**：当前 pre-turn compact 尚未估算随后加入的 context diff、user input 和最终请求；
   实际首次采样超窗会直接结束 turn。SSE 层还把不同 `response.incomplete` reason 折叠为普通 stream error。

编辑后诊断、完成证据检查、旧工具结果生命周期和资源级并发也有潜力，但改动面或误判风险更高，应排在上述方向之后。

这些证据足以说明候选有清楚机制、值得做**可证伪实验**，不足以说明它们在 Codex/RONDO 上“大概率高收益”。教师之间独立收敛只能
提高先验可信度；还要依次确认 RONDO 的真实缺口、该缺口在目标轨迹中的发生率、机制指标按预期变化，最后由 exact paired E-B 结果证明
净收益。A4/C4 的把握最高，但产出是定位能力；行为候选中 C1、C2 和长轨迹/异常轨迹下的 C11 最值得优先验证，其余多数是按失败簇触发的
条件候选，而不是默认应实施的功能。

## 3. 证据等级与源码快照

本文按以下等级使用证据：

- **A 级**：本次读取的 RONDO/冻结 Codex 源码，以及来源可确认的官方教师源码；版本、提交和许可证信息分别如实记录，许可证未确认时
  仍只允许机制研究、不能复制代码。
- **B 级**：论文和 AI 公司官方工程文章。它们可支持机制合理性，但不能证明迁移到 RONDO 后会提高 Terminal-Bench 分数。
- **C 级**：社区重建项目。只用于交叉提示，不采用其内部数字，也不复制代码。

教师快照如下：

| 教师 | 本地快照 | 来源与许可 | 使用方式 |
|---|---|---|---|
| Kimi Code | `4ac7240fff595b41a94a63c4b4ca74840ad95cf8`，tag `@moonshot-ai/kimi-code@0.32.0` | [MoonshotAI/kimi-code](https://github.com/MoonshotAI/kimi-code)，MIT | A 级 |
| OpenCode | `a105350812f05f914c768e468559dbd6bd508d8e`，tag `v1.18.13` | [anomalyco/opencode](https://github.com/anomalyco/opencode)，MIT | A 级 |
| OpenHands SDK | `2f27653959f7596769427ee4657247b32c94504e`，tag `v1.40.0` | [OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk)，MIT | A 级 |
| Claude Code | 项目方确认对应官方 2.1.88 旧版实现；本地目录没有独立 git 元数据 | Anthropic 官方旧版实现；本地未发现可用 LICENSE | A 级机制证据；版本限定，只研究不复制 |

定向比较还确认：本次涉及的 context/history/compact、turn loop、工具并发与截断、multi-agent control、plan、
hooks、approval/sandbox、world-state 等抽样文件，在 `mydev/` 与冻结 `codex-source-code/` 中一致。RONDO 在相关链路的
主要差异是 Guardian 配置、证据和 `E_final` 捕获，而不是通用 harness 机制重写。

## 4. RONDO 当前基线：已有能力与真实空位

### 4.1 已有能力，不应重复造轮子

| 能力 | 现有实现证据 | 判断 |
|---|---|---|
| 自动 compact 与近期用户消息保留 | `mydev/codex-rs/core/src/compact.rs`；`prompts/templates/compact/prompt.md`；`context_manager/history.rs` | 已有结构化摘要、初始上下文重注入、call/output 配对和历史归一化 |
| Prompt cache 与连接复用 | `mydev/codex-rs/core/src/client.rs`；`core/src/tasks/mod.rs` | `client.rs` 已有稳定 `prompt_cache_key` 和 WebSocket 复用条件；token/cache 统计在 task/协议指标链路 |
| 动态工具发现 | `mydev/codex-rs/core/src/tools/handlers/tool_search.rs` | 已有 handler cache、BM25 搜索和工具规格合并 |
| 并行工具执行 | `mydev/codex-rs/core/src/tools/parallel.rs` | parallel-safe 工具共享读锁，非并行工具持写锁；属于粗粒度但完整的安全基线 |
| 持久 shell 与软 yield | `mydev/codex-rs/core/src/tools/handlers/shell_spec.rs`；`runtimes/unified_exec.rs` | 已有 session/chunk id、`write_stdin` 轮询、退出码和耗时 |
| 输出 cap 与 head/tail | `mydev/codex-rs/utils/output-truncation/src/lib.rs`；`tools/context.rs`；`unified_exec/head_tail_buffer.rs` | 已有模型可见预算和稳定截断，但缺少通用的完整输出续读句柄 |
| Multi-agent 基础设施 | `mydev/codex-rs/core/src/agent/control/`；`tools/handlers/multi_agents_v2/` | 已有 spawn/wait/mailbox/followup、fork、并发限制和驻留管理等基础 control-plane primitives |
| Retry、approval 与 sandbox | `mydev/codex-rs/codex-api/src/sse/responses.rs`；`core/src/tools/orchestrator.rs`；`tools/approvals.rs` | 已有有限重试、Retry-After、用户 session 审批缓存和一次升级重试；Guardian 决策不进入该 session cache，仅 strict-auto-review 的无沙箱升级强制重新 review，其他已批准路径可在本次调用内跳过重复审批 |
| 内部 timing/token 指标 | `mydev/codex-rs/core/src/turn_timing.rs`；`tools/parallel.rs`；`tasks/mod.rs`；`compact.rs`；`guardian/metrics.rs` | 已有 turn phase、部分 direct 工具 timing、token/cache、compact before/after、Guardian duration/TTFT 等原始指标 |

### 4.2 当前更值得研究的空位

- `eval/rondo_eval/terminal_bench/results.py` 尚未汇总大部分 core 内部指标；已有任务级 token 记录仍可能为 0。
- 通用截断保留模型可见 head/tail，但超出收集上限或对象生命周期后的中段内容不能稳定续读。
- 主 turn loop 未见通用的重复工具签名、连续失败、no-progress 或连续 compact 门禁。
- `mydev/codex-rs/core/src/session_prefix.rs` 中成功子智能体最终消息直接 `clone()`；现有 1000-token 常量没有约束成功 payload。
- `FuturesOrdered` 中的工具 future 会并发启动，但按发射顺序记录结果；下一模型步本来就要等待整批完成，因此它更可能影响已完成结果的
  记录/可见时刻，而不应预设会让墙钟时间超过最慢工具。目前没有完成到记录的滞后、队列深度和真实重叠指标。
- `update_plan` 主要产生 UI 事件，描述中的“最多一个 `in_progress`”没有在 handler 中形成强语义状态；
  但这不一定是当前性能瓶颈。
- 没有通用 LSP/增量诊断链路；增加它可能提高修复反馈质量，也可能带来进程、语言和噪声成本。
- pre-turn compact 明确留有 TODO：它发生在 context update 和本轮 user message 之前，未估算这些 pending items；首次正常采样得到
  `ContextWindowExceeded` 后直接返回并结束 turn。SSE parser 还会读取 `response.incomplete.incomplete_details.reason`，但把所有 reason
  映射为同一类 `ApiError::Stream`，随后只走通用可重试重放。
- 工具参数当前直接由 `serde_json` 严格反序列化，错误会回灌模型；这是正确的安全基线，但尚无“schema 明确且意图无歧义”字段的
  窄类型归一化。是否值得增加，取决于真实参数错误及下一轮修复成功率。
- 共享 Responses stream retry helper 当前只区分 Sampling/RemoteCompactionV2 以便记录，两者仍由调用方传入同类 retry budget；
  尚未表达“用户阻塞/安全关键/明确可丢弃后台工作”的关键度。需先盘点各类请求的实际调用路径，不能据此假定所有后台工作都在多次重试。

## 5. 按主题比较四类教师 Harness

| 主题 | Kimi Code | OpenCode | OpenHands SDK | Claude Code 2.1.88 | 对 RONDO 的有效启示 |
|---|---|---|---|---|---|
| Context/compact | 用户输入首尾保留 + 单摘要；过大文本工具结果在产出边界落盘预览；旧结果 micro-compaction 在本快照禁用 | 独立 pruning 在后续模型投影中隐藏旧工具结果；LLM compact 另行保留 recent tail | 固定保留最早事件与预算内近期后缀，裁剪不切断原子事件单元 | 强调消息总输出预算、compact 恢复边界与 cache-break 诊断 | RONDO 已有 compact；优先补旧工具结果生命周期、可恢复输出和 compact/no-progress 指标 |
| 工具输出 | 过大结果落盘，返回预览、路径和下一步 | 2000 行/50KB 后保存完整结果并给 head/tail 与检索提示 | 结构化 observation 和输出截断 | 按最终 API message 聚合预算，并冻结已被模型看到的替换决定 | “模型可见小、原始结果可检索”值得独立实现；阈值不能照抄 |
| 工具设计与错误 | tool schema 渐进披露、结构化错误、资源访问声明 | edit/write 后附带有界错误诊断 | action/observation 类型明确 | 异步 LSP 与工具结果存储 | RONDO 已有 tool search 和结构化 exec；真正新增点是有界、增量、可关闭的编辑后诊断 |
| 并行与子智能体 | 资源访问调度和同一步重复合并 | 会话/工具并行机制较完整 | 默认并发上限为 1；启用后用 FIFO 资源锁，未声明资源的已知工具按工具名互斥 | 子任务和工具并发机制 | RONDO 已有粗粒度并行和基础 control-plane；先测结果可见性，不默认扩大子智能体 |
| 自纠错与停滞 | 3/5/8 次提醒、12 次终止；同一步精确重复可共享结果 | 依赖工具反馈和 session lifecycle | 检测重复 action/observation/error、独白和 ABAB 循环；有 schema 感知的参数修复 | 有界处理 prompt-too-long/max-output，API error 不进入 Stop-hook 续跑 | 机制可迁移，但阈值必须由 RONDO 轨迹学习；恢复原因与语义重复必须分开计数 |
| 终止 | 重复上限和 step lifecycle | session stop/compaction hooks | stuck detector 可直接结束 loop | 结束前自检思路 | RONDO 可复用 Stop hook 做有证据的完成检查；避免通用硬 step cap 误杀长任务 |
| Prompt/cache | 分层 prompt 与动态工具上下文 | provider/session cache 配置 | system prompt、skills 与 condenser 配置 | 专门分析 cache break | RONDO 已有稳定 cache key、prompt 分层和 world-state diff；应先归因哪一层变化，而非重写 assembler |
| Sandbox/approval | 有工具权限边界 | 权限规则和外部目录检查 | security analyzer/confirmation | 权限与沙箱提示 | RONDO 的 Guardian/approval/sandbox 更接近项目目标；教师机制不能成为放松安全的理由 |

### 5.1 关键教师源码入口

- Kimi 重复检测（成熟引擎）：`reference-agent-harness/kimi-code/packages/agent-core/src/agent/turn/tool-dedup.ts`。
- Kimi 输出保存（成熟引擎）：`reference-agent-harness/kimi-code/packages/agent-core/src/agent/turn/tool-result-budget.ts`。
- OpenCode 输出续读：`reference-agent-harness/opencode/packages/opencode/src/tool/truncate.ts`。
- OpenCode 编辑后诊断：`reference-agent-harness/opencode/packages/opencode/src/tool/edit.ts`、`write.ts`、`lsp/diagnostic.ts`。
- OpenHands 停滞检测：`reference-agent-harness/openhands-sdk/openhands-sdk/openhands/sdk/conversation/stuck_detector.py`。
- OpenHands 资源级并发：`reference-agent-harness/openhands-sdk/openhands-sdk/openhands/sdk/agent/parallel_executor.py`、
  `conversation/resource_lock_manager.py`。
- OpenHands condenser：`reference-agent-harness/openhands-sdk/openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py`。
- OpenHands 参数修复与错误回灌：`reference-agent-harness/openhands-sdk/openhands-sdk/openhands/sdk/agent/utils.py`、
  `agent/agent.py`。
- Claude Code 2.1.88 的聚合输出与 cache 稳定决策：`reference-agent-harness/claude-code/utils/toolResultStorage.ts`；
  cache-break 归因：`services/api/promptCacheBreakDetection.ts`；分因恢复与重试预算：`query.ts`、`services/api/withRetry.ts`；
  窄类型转换：`utils/semanticNumber.ts`、`utils/semanticBoolean.ts`。

Kimi 仓库将 `agent-core` 定义为统一成熟引擎、`agent-core-v2` 定义为 WIP port；本文以上述成熟路径为主，v2 只作实现一致性的旁证。
OpenCode 的 V2 目录也存在未完成痕迹，本文不把目录名或 TODO 当成成熟度证据。

## 6. 测评前置与候选优先级

优先级综合考虑：问题是否在 RONDO 中真实存在、预期影响范围、实现与维护成本、安全风险、能否被现有 eval 清楚归因。
规模 `S/M/L` 是相对估计；“收益把握”只是研究排序，不是效果承诺。以下 `C1-C13` 是调研候选编号，**不是 WBS 的
P0/P1/P2/P3 阶段**；A4 是 M2 测评建设的一部分，也不是方向 1 的算法候选。

| 顺序 | 候选 | 类型 | 收益把握 | 规模 | 验证轨道 | 候选优先级 |
|---:|---|---|---|---|---|---|
| 前置 | A4：接出已有内部遥测 | 行为保持型 | 归因价值高 | S-M | E-A/离线 | 共同前置 |
| C1 | 可恢复的聚合工具输出预算 | 行为改变型 | 中高 | M | E-A 机制 + E-B 结果 | 高 |
| C2 | 停滞观测 → 单次纠偏提醒 | 观测为保持型；提醒为改变型 | 中高 | S-M | E-A → E-B | 高 |
| C3 | 成功子智能体 completion envelope 与硬预算 | 行为改变型 | 中，取决于子智能体使用率 | 复用 C1 后 S；独立做 M | E-A 机制 + E-B 结果 | 中高 |
| C4 | Prompt/cache 分层归因 | 行为保持型 | 归因价值高 | S | E-A/离线 | 高 |
| C5 | 并发结果可见性观测 | 行为保持型 | 中低 | S | E-A/时延微基准 | 中 |
| C6 | 有界增量编辑后诊断 | 行为改变型 | 中 | M-L | E-B | 中 |
| C7 | 确定性完成证据检查 | 行为改变型 | 中 | S-M | E-B | 中 |
| C8 | compact 前模型投影清理与状态锚点 | 行为改变型 | 中 | M | E-B | 中 |
| C9 | 资源键并行调度 | 行为改变型 | 低，需先找到真实串行对象 | M | E-A 并发 + E-B | 低/有条件 |
| C10 | 简化任务路由或按需 scout/verifier | 行为改变型 | 低到中 | M-L | E-B | 低/远期 |
| C11 | 完整请求上限预检与分因单次恢复 | 行为改变型 | 中高，仅覆盖长/异常轨迹 | M | E-A 故障注入 → E-B | 高/有条件 |
| C12 | 严格 schema 下的窄参数归一化 | 行为改变型 | 低到中，偏弱/本地模型可能更高 | S-M | E-A → E-B | 中/有条件 |
| C13 | 按工作负载关键度分配重试预算 | 行为改变型 | 低，主要影响过载尾时延 | S | E-A 故障注入 | 低/有条件 |

### 6.1 共同前置：把已有遥测接进 eval

**机制。** 不新建另一套 telemetry，只把当前已经产生的安全聚合值接到 A4/eval 结果：

- input/cache-read/cache-write/output token 与已有 turn profile；
- 当前 direct/direct-plaintext 路径已有的工具 dispatch/handler/total timing；该 timing 依赖 INFO tracing，nested code-mode
  被有意抑制，首版应诚实保留这个覆盖范围；
- `CompactionAnalyticsAttempt` 的 before/after 与 compact 次数；
- Guardian duration、TTFT、token/cache 等已有指标。

Prompt 分层 hash、raw/model-visible 输出大小、续读、重复签名、无文件变化、in-flight 高水位、完成到记录滞后、子智能体回传体积、
完整请求预检误差、overflow/`response.incomplete` 原因与恢复路径、工具参数错误/修复，以及工作负载类别/重试等待都尚需新增探针，
分别归入 C1-C5、C11-C13，不能包装成“只接线”。流式观测还应区分 TTFT、首 chunk 后 stall、用户取消和
watchdog/consumer-drop 到真正退出的延迟。
默认只落任务末安全聚合值，不记录 prompt、命令正文、工具输出、原始参数或密钥。

**公平边界。** Core 内部探针只用于 RONDO 自身版本间归因，不能拿来和未注入同等探针的冻结 Codex 横比；双侧公平对比只能采用
runner/supervisor 外部共同指标。这与 `doc/WBS/eval-benchmark.md` 的 A4 边界一致。

**预期与停止条件。** 直接分数应不变，但后续能区分模型差异、context 浪费、工具等待和 Guardian 成本。若字段不能稳定归属于
task/turn，或采集明显影响运行时，则缩减为任务末汇总。

### 6.2 C1：可恢复的聚合工具输出预算

**机制。** 在单次模型请求层面统一预算多个工具结果，而不是只逐工具截断。模型可见内容保留结构化状态、首个关键错误附近片段、head/tail
和稳定 omission marker；完整内容写入 session-private、git-ignored、有总量上限和生命周期的 artifact，返回可由现有 read/grep 或安全 pager
读取的句柄。同时新增 raw/model-visible 大小、截断和续读计数。

预算应按最终送上 wire 的 user message 聚合并行 `tool_result`。某个 `tool_use_id` 的结果一旦被模型看到，就应冻结“原文/替换”决定，
并把模型实际看到的 exact replacement 随 transcript 持久化，使 retry/resume/fork 保持字节稳定的 cache prefix；落盘失败时保留现有原结果，
不能把持久化故障变成内容丢失。结构化 search pager 可作为该设施的一个消费者，但不为此重做整套 Grep/Glob 工具。

完整输出只能保存本来就允许进入模型的内容，沿用现有脱敏/权限边界；文件权限、TTL、单任务总量和清理责任必须明确。当前统一 exec 还有
1 MiB 收集上限，因此实现时要决定是流式写入有界 artifact，还是诚实标注“只保存已收集部分”，不能把后者称为完整原文。

**预期假设。** 降低大输出挤占 context 的概率，同时减少因为关键错误落在中段而重跑命令。Kimi、OpenCode 和 Claude Code 2.1.88 都出现了
“小预览 + 完整结果引用”的独立实现，这是值得实验的共同模式，但它们的 50KB、2000 行等阈值不能直接迁移。

**风险与停止条件。** artifact 会带来磁盘和敏感输出生命周期风险；若续读率很低、重复运行不降或 I/O 成本上升，则回退到现有截断与
更清楚的 omission marker。

### 6.3 C2：停滞观测，再做一次纠偏

**机制。** 在有限窗口内记录规范化 `(tool, args, result/error class, diff-state)`：

1. 第一阶段只观测；统计同一步精确重复、跨轮重复、相同错误、ABAB、连续 compact 和无文件变化。
2. 有数据后，对跨轮停滞只注入一次短提醒，要求解释新信息或改换策略。
3. 同一步调用合并只允许声明为只读、幂等且参数完全一致的工具；任何写操作、网络副作用或未知工具都不能自动抑制。
4. 首版不复制 Kimi 的 3/5/8/12 阈值，也不让 OpenHands detector 直接硬停；其 context-window loop 检测仍是 TODO，连续 compact
   是 RONDO 新增的观测信号，而不是教师已验证行为。

规范化应允许工具声明窄的 `inputsEquivalent`，消除默认值、路径表示等无意义差异，而不是只比较 raw JSON。progress vector 至少包含新 diff、
新 error signature、新 result fingerprint 和 token delta；transport retry、C11 恢复、compact、Stop-hook continuation 与用户 steer 单独计数，
不能误报成模型语义重复。RONDO 没有专用 Read handler，因此“相同文件范围未变化”首版最多作为可识别 read-like 轨迹的观测，不能靠猜 shell
命令语义去抑制执行。

**预期假设。** 减少重复读、重复测试和失败循环，尤其是模型没吸收工具错误时的无效 token/时延。

**风险与停止条件。** 合理的轮询、分块读取和修复后复测外观上也会重复；fingerprint 必须纳入结果、diff 和时间/会话语义，且提醒最多一次。
误报增加额外轮次或压低成功率时，保留观测并撤销提醒。

### 6.4 C3：成功子智能体 completion envelope

**机制。** 先由 A4/C3 探针确认 Terminal-Bench 轨迹确实使用子智能体且成功回传偏大，再对成功结果执行硬预算。返回确定性 envelope：
`status`、短结论、证据文件/符号、未解决项、建议下一步；不再调用一次模型来“总结总结”。超限原文使用 C1 的 artifact/续读基础设施。

**依赖与规模。** 仅做文本截断是 S，但可能丢失唯一证据，不宜单独落地；复用 C1 后增量是 S，独立建设安全引用、生命周期和读取边界则是 M。

**预期假设。** 避免把共享 worktree 中已可检索的大量内容重复塞回主上下文。只测 token 下降不能算成功，还要检查主 agent 是否增加重复读取；
若实际任务很少使用子智能体，则直接降级，不为理论空位实施。

### 6.5 C4：Prompt/cache 分层归因

**机制。** 在 `build_prompt`/最终 Responses request 边界，对模型实际可见的 base/developer/AGENTS/world-state/history/tool-schema/
output-schema/Guardian 等层记录大小与稳定 hash，只记录“哪层变化”而不记录内容；将其与同一 attempt 的 cached/noncached token、TTFT
及 WebSocket incremental/full fallback 对齐。确认问题后，才考虑减少重复说明、按任务能力隐藏无关工具、稳定高复用前缀。

层 hash 变化本身不等于 cache break；只有同一请求的 cache-read 确实显著下降时，才进一步分类为模型/系统提示/工具 schema/动态 context
变化或未知服务端/TTL 原因。请求与 retry attempt 必须分开，避免把正常重试误归因给 prompt。

**预期假设。** 找到真正破坏 prefix cache 或吞噬输入预算的层。RONDO 已有 `prompt_cache_key`、world-state diff 和 tool search，
因此“新增 prompt cache”或“从头做动态工具加载”都不是候选。

**风险与停止条件。** Prompt 精简会改变行为和安全指令遵循；观测属于 E-A，任何删减都转入 E-B，安全层不作为降 token 的目标。
若 cache miss 与层变化没有稳定关联，就停止在观测阶段。

### 6.6 C5：并发结果可见性观测

**机制。** 在现有有限范围的 tool timing 上增加 in-flight 高水位、实际重叠，以及“工具完成 → 按序记录”的滞后。`FuturesOrdered`
中的工具已经并发启动，下一模型步通常还要等待整个批次，因此这里不预设 ordered drain 会把总等待推高到最慢工具之外。

**预期假设。** 查明是否只有记录/事件可见性延迟，还是在慢工具完成后仍存在可测的顺序处理尾巴。只有出现稳定、可复现且占比显著的尾巴，
才比较完成顺序收集后按 call id 重排等方案；不得破坏模型工具调用/结果配对。若没有该现象，候选到观测即结束。

### 6.7 C6：有界增量编辑后诊断

**机制。** OpenCode 的教师事实是 `edit` 返回当前文件现有 error，`write` 还可能返回少量其他文件 error；Claude Code 2.1.88 进一步展示了
“编辑前抓 baseline、只交付新增诊断”的实现形态。RONDO 可采用更保守的迁移：编辑成功后异步采集被改文件的**新增** error 级诊断，在下一
安全消息边界交付；按内容键跨轮去重、severity 排序，并限制每文件/总条数。语言服务之间故障隔离；不存在、未 ready 或超时都 fail-open，
不阻塞编辑，也不在每次编辑后启动昂贵全仓分析。诊断交付后才推进 baseline。

**预期假设。** 把“编辑 → 很晚才测试发现语法/类型错误”缩短为即时反馈，减少错误传播。

**风险与停止条件。** RONDO 当前没有通用 LSP 生命周期；多语言支持、后台进程、陈旧诊断和噪声可能让它从 M 变成 L。先对已有、便宜、
可增量的诊断源做 capability-gated 原型；若噪声或启动成本抵消收益，就不建全套 LSP 平台。

### 6.8 C7：确定性完成证据检查

**机制。** 复用 Stop hook/turn lifecycle，在模型结束前只核对可验证的显式声明：声称“测试通过”时应有对应 exit code 0；
要求修改且任务未被阻塞时应存在 diff；最后一次同类测试/编译错误后不能没有修复或重新验证。缺证据时最多注入一次具体提醒。

**预期假设。** 降低“做了一半就结束”或把 skip/旧结果表述为通过的失败。

**风险与停止条件。** 纯咨询、文档、无需 diff 的任务很常见；规则必须由任务意图和实际声明触发，不能变成通用完成门禁。若 false positive
造成额外轮次，立即回退到仅记录 finish-gap 指标。

### 6.9 C8：compact 前模型投影清理与状态锚点

**机制。** RONDO 已有成熟 compact，remote compact 也已经会清理连续尾部中可投影的旧输出，不建议换成新的“记忆系统”。真实增量是：
在 C1 之后，把带恢复句柄的旧大结果投影扩展到 local/其他 compact 路径及有数据支持的更早历史，并显式保留当前 diff/已改文件、最近失败测试、
用户约束、未解决错误和工具 call/result 原子边界。Canonical rollout/transcript/history 必须保留原始数据；现有 `CompactedItem` 的
`replacement_history` 已能精确恢复 compact 结果，新增的 exact replacement、anchor 与恢复句柄应进入同类 snapshot，使 retry/resume 稳定
重建；链路不完整时保留完整历史而不是猜测。RONDO 不为此重做 event sourcing。

近期一项预印本在 OpenHands CodeActAgent 上测试单一 GPT-4o 主模型、GPT-5-mini condenser 与 60 个
DiscoveryBench 科学发现任务，报告 LLM condenser 增加 24%-94% token，而简单 mask tool output 节省约 8.6%；
它不是仓库修复或 Terminal-Bench 证据，但足以提醒我们先做确定性清理，再考虑额外 LLM 摘要
([Context Condensation Study](https://arxiv.org/abs/2605.18854))。

**风险与停止条件。** 错误隐藏中间诊断会造成重跑；必须先有 C1 的可恢复句柄，并用长轨迹 E-B 观察成功率和重复调用。关键信息恢复率下降时回退。

### 6.10 C9：资源键并行调度（有条件）

RONDO 当前 parallel-safe 工具已经共享读锁并行，所以给这些工具再加资源键没有收益。只有先找到一个**当前因全局写锁而串行、但可被明确资源键
安全拆分**的具体工具，并由 C5/A4 证明等待显著，才把它升级为正式候选。迁移时不同资源可并行、相同资源按稳定顺序串行；未知工具、写文件、
Git、审批和外部状态继续全局独占。这是比 OpenHands 原行为更保守的 RONDO 方案。

**风险与停止条件。** 资源声明错误会引入竞态和不确定性；找不到上述具体工具时，本候选直接结束，不改调度器。

### 6.11 C10：简化任务路由或按需 scout/verifier（远期）

**机制。** 对能可靠识别的局部修复，可比较固定的 localization → repair → patch validation 路线；对陌生、多文件且可拆分的任务，
才试一个有独立预算的 scout 或 verifier。默认单 agent，不为简单任务增加规划、汇总或第二次模型调用。

**预期假设。** 某些任务可能从更窄工作流或独立验证受益；Agentless、SWE-agent 与教师子任务机制只能说明这个方向值得分型实验，不能证明
RONDO 应默认采用多 agent。

**风险与停止条件。** 路由错误、重复劳动和汇总 token 很容易超过收益。若不能从现有轨迹定义稳定的任务分型，或 paired E-B 没有显示净收益，
就维持现有主 loop。

### 6.12 C11：完整请求上限预检与分因单次恢复

**机制。** 第一层是在 context update、user input、最终 router/tool/output schema 都确定后估算真正待发送请求；预计越过 compact threshold 时，
在首次采样前 compact，而不是只看尚未包含 pending input 的旧 history。第二层只处理 provider 实际拒绝：如果本 attempt 尚未产生有效 assistant
内容、任何工具调用或其他可能副作用，且本 turn 尚未恢复过，允许 compact 后精确重试一次；否则立即上抛。现有 executed-tool metadata
可以帮助重建 prompt，但不能把“不确定是否执行”当作安全重放。

同时把 SSE 已读取的 `incomplete_details.reason` 保留为 typed error。`content_filter`、未知 reason 和协议不允许续接的状态直接终止；
`max_output_tokens` 是否能复用 partial assistant item 或做一次续写，必须先按实际 Responses 协议验证，不能照抄 Claude Code 针对另一 API 的
续写提示。API error 也不应触发会继续扩充上下文的 Stop-hook 循环。

**验证与停止条件。** E-A 覆盖 pending input 估算边界，并注入 context overflow、`max_output_tokens`、`content_filter`、未知 reason 和
transport close；记录 estimate/actual delta、reason、recovery path、attempts、partial items preserved、duplicate tool side effect、terminal outcome、
token 与 wall time。恢复必须 one-shot、只允许预期原因、取消可传播，每个 tool call 最多一个终态。若真实轨迹几乎不发生、预检导致过早
compact/cache 失效、恢复未减少硬失败，或出现重复副作用，本候选停止；健康态不应声称有直接收益。

### 6.13 C12：严格 schema 下的窄参数归一化

**机制。** 先统计 `tool_argument_parse_error`、下一轮是否原样修复成功及浪费的 token/时延。只有 schema 明确要求 number/bool 时，才允许把
严格十进制字符串或精确字符串 `true`/`false` 转为对应类型，并在转换后完整重跑正式 schema 校验。OpenHands 的官方教师源码证明
“schema 感知修复后再验证”是可实现模式；Claude Code 2.1.88 给出了更窄的数值/布尔例子。RONDO 首版不解码任意字符串化对象、不删未知字段、
不猜 enum/工具名/路径，也不接受宽松 JSON。

**验证与停止条件。** 记录 `repair_kind`、字段期望/实际类型、最终 validation/执行结果和是否少了一轮模型修复，不记录原始参数值。
该候选对较弱或本地模型可能更有价值，对严格 structured output 模型可能几乎不触发。发生率低、净成功率不升，或错误调用进入执行的比例上升时，
保留数据并撤销归一化。

### 6.14 C13：按工作负载关键度分配重试预算

**机制。** 先盘点 Responses 及其他模型调用入口，显式标记用户阻塞/安全关键/必要 compact 与可丢弃后台工作。未知类别保守按前台处理；
只有明确 optional 的标题、建议或类似 side work 才能 0/1 次重试或 fail-fast。保留现有 Retry-After、backoff、transport fallback 与取消语义，
不另造重试框架；安全分类和用户主采样不得因“省时”降级。Claude Code 2.1.88 提供了该机制的官方旧版实现证据，但其调用分类和阈值
仍受版本与产品形态限制。

**验证与停止条件。** 用 429/529/timeout 故障注入记录 workload class、error class、budget、Retry-After、wait time、dropped optional 与
foreground success。它主要可能减少过载时的尾延迟和重试放大，不应预测健康态得分提高。若找不到实际 optional 重试路径，或分类影响前台/
安全结果，候选直接结束。

## 7. 外部研究能支持什么，不能支持什么

- Anthropic 的工具工程文章强调高信号返回、分页/过滤/截断和可行动错误，支持优化工具接口而不是单纯加 prompt；但文章没有给出 RONDO
  的可迁移增益：[Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)。
- Anthropic 的 context engineering 文章把 context 视为有限资源，并把清理旧工具结果、结构化笔记和按需多智能体作为不同层级手段；
  它支持“先清理、后摘要、按任务决定多智能体”，不支持默认扩大 agent 数量：
  [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)。
- SWE-agent 说明 agent-computer interface 本身会显著影响端到端表现；其报告的 12.5% SWE-bench 和 87.7% HumanEvalFix 是整套系统结果，
  不能归因给某一个工具设计：[SWE-agent](https://arxiv.org/abs/2405.15793)。
- Self-Debugging 在程序生成任务上报告最高约 12% 改善，支持“执行结果驱动的反馈”值得研究；它不是仓库级 coding harness 证据，
  也不支持每轮增加泛化 reflection：[Self-Debugging](https://arxiv.org/abs/2304.05128)。
- Agentless 表明简单的 localization → repair → patch validation 路线也可能有竞争力；对 RONDO 来说这是远期任务路由实验，
  不是近期架构重写理由：[Agentless](https://arxiv.org/abs/2407.01489)。
- OpenAI 当前 GPT-5.6 官方模型指南中的内部 coding-agent 样例报告，精简 prompt 后 eval 提高 10%-15%、token 减少
  41%-66%、成本降低 33%-67%；模型、harness 和任务分布均与冻结 Codex/RONDO 不同，只能作为“先量 prompt 组成”的弱迁移信号，
  不能拿来预测本项目收益：
  [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model)。
- Terminal-Bench 类测评必须冻结基础设施条件。Anthropic 在同模型、同 harness、同任务下，从严格 `1x` 资源上限到完全
  uncapped 的极端配置观察到 6 个百分点差异（`p < 0.01`）；`1x` 到 `3x` 的得分变化仍在噪声内（`p = 0.40`）。
  因此未来小样本涨跌若没有 exact paired 环境，不应归因给 harness：
  [Quantifying infrastructure noise in agentic coding evals](https://www.anthropic.com/engineering/infrastructure-noise)。

## 8. 建议的探索顺序

以下只是与当前 WBS 对齐的宏观顺序，不越过当前 P2/M2 门禁，也不构成真实 API 测评授权：

1. **把 A4 作为 M2 建设的一部分完成**：先接出已有安全聚合值，确认结果 schema、覆盖边界和开销。
2. **M2 后由方向 1 读取失败轨迹**：看输出截断、重复调用、prompt cache miss、pending-input 估算误差、overflow/`response.incomplete`、
   工具参数错误、重试等待、成功子智能体 payload 和结果可见性各自占比。
3. **一次只改一个机制**：优先可恢复输出、停滞观测/单次提醒；异常响应有实际成本时试 C11。只有子智能体使用率和回传体积有证据时
   才做 completion envelope。
4. **按失败簇选择中优先候选**：若可证明的参数类型错误突出，试 C12；若编辑错误传播突出，试增量诊断；若提前结束突出，试完成证据检查；
   若长轨迹 context 浪费突出，试旧结果清理与状态锚点；只有过载尾时延存在 optional 重试放大时才试 C13。
5. **最后再碰调度与工作流**：只有明确的串行工具或任务类型证据时，才试资源键并行、task router 或 scout/verifier。

每个行为改变型候选都应：

- 先用 E-A 验证 schema、截断、计数、取消和失败语义，再用 E-B/真实 Terminal-Bench 验证结果；
- 固定所有非被测变量，采用 paired 对照；若候选本身改 prompt，则两侧 exact prompt/hash 是唯一自变量并被记录；基础设施异常单独归因；
- 同时看成功率、token、墙钟时延、重复动作、额外测试/读取和 Guardian 指标，不能只优化一个代理指标；
- 保留明确、低风险的 Git 回退路径；只有并行实验或风险较高的改动才增加开关，不强制每个方向长期可插拔；
- Core 内部探针只做 RONDO 版本内归因；冻结 Codex/RONDO 双侧对比只采用双方共同可见的 runner/supervisor 指标；
- 批量真实 API 测评仍需另行明确范围、轮数和预算并取得授权。

### 8.1 零收益和负收益也是正式产出

候选被 valid paired 实验判定为 `neutral` 或 `regressed`，与 `improved` 一样应长期保留；它能界定无效模型/任务域、校准触发阈值并避免
后续重复投入。基础设施失败、控制变量不一致或样本不足只能记为 `inconclusive`，不能伪装成“候选无效”。

未来真正实施候选时，建议在现有 eval 体系内增加一个轻量、只追加的实验结论索引，引用而不复制单次运行记录和原始工件；至少绑定候选编号、
baseline/variant commit、模型与配置身份、taskset/seed、paired run ids、主指标与护栏、机制指标、原始 artifact、判定/停止理由和回退 commit。
`verdict` 可区分 `improved|neutral|regressed|inconclusive`，只有有效受控对照才能得出前三类结论；基础设施失败、样本不足或控制变量不一致只能
记为 `inconclusive`。C11 还应记录请求估算误差、overflow/incomplete reason、恢复路径和重复副作用，C12 记录 repair kind/最终校验，C13
记录 workload/error class/等待与丢弃情况。实现被回退也不删除结果；模型、provider、任务分布或候选实现实质变化时可以重测，但旧结论只在
原 scope 内成立。本段只是本报告的后续建议，不修改或替代当前 `doc/eval-data-layout.md` 数据规范。

## 9. 明确暂缓或排除的方向

- **不重做已有能力**：generic compact、world-state diff、prompt cache、动态 tool search、持久 shell、基础并行调用、
  spawn/wait/residency、通用 retry/backoff/transport fallback、用户 session approval cache、sandbox escalation、prompt hierarchy；Guardian 决策不进入该
  用户 session cache，strict-auto-review 无沙箱升级仍重新 review。
- **不默认扩大 multi-agent**：通讯和上下文成本可能抵消并行收益；先解决回传边界和重复劳动测量。
- **不先建跨任务向量记忆/ReasoningBank**：污染、过时经验、评测泄漏和数据治理成本都高于近期收益把握。
- **不做每轮 critic/reflection 或 MCTS**：token/时延成本确定，增益高度依赖任务；只保留错误或停滞触发的一次反馈。
- **不先做学习型/额外 LLM 压缩**：RONDO 已有 compact，先测试确定性的 tool-output mask 和状态锚点。
- **不做宽松参数猜测、模糊编辑或安全降级**：C12 仅允许 schema 明确、可逆且无歧义的窄类型转换；删字段、猜 enum/路径/工具名、
  更少审批、放宽 sandbox/Guardian 或吞掉错误都不能算性能优化。
- **不做 event-sourcing 或调度器大重构**：除非 A4 数据证明现有架构形成稳定瓶颈。
- **不直接采用 Claude Code 2.1.88 的内部阈值、feature flag 或收益数字**：官方旧版实现可以证明机制存在，但版本、模型、API 和任务分布
  都不同；本地许可证也未确认，只迁移经 RONDO 数据支持的设计并独立实现。

## 10. 后续决策的最小清单

未来挑选候选进入 plan 前，只需回答以下问题：

1. A4 数据是否证明这个问题在 RONDO 中真实出现，频率和成本是多少？
2. 能否通过现有 extension/hook/result schema 窄改，还是需要核心 loop 重构？
3. 是行为保持、行为改变还是 bugfix；对应 E-A/E-B 轨道是什么？
4. 成功判据是否同时覆盖任务成功率、token、时延和副作用，而不是单一代理指标？
5. 是否有明确失败语义和低风险 Git 回退路径；若并行实验或风险较高，是否需要临时开关？
6. 是否保持 Guardian、approval、sandbox、测试强度和真实外部交互边界不变？
7. 无论 improved/neutral/regressed，是否能以 exact scope、run ids 和原始工件引用形成可复用结论？

若第 1 项没有证据，默认先补观测；若第 6 项答案是否定的，该方向直接排除。
