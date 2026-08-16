# Plan 038 / Multi M-1 第三轮审查整改

日期：2026-08-16 ｜ 工作树：`.claude/worktrees/039-multi-m1-team-world-state` ｜ 被复验提交：`19a0318`
｜ 复验报告：`agent_log/2026-08-16-052632-plan038-m1-third-revalidation.md`

## 结论先说

复验报告剩余的 2 项投影接缝缺口**逐条核对后均属实**，已修复。领域层四项与 history 分页在本轮无改动。

## 逐项修复

### 1. `NoRoom` 仍先发一次无投影 sampling（阻断）

**确认**：`request_new_context_window()` 只是置一个标志，而该标志在 `run_turn` 里要等 provider 响应之后
才被消费，并且还要 `needs_follow_up=true` 才会真正压缩。所以模型确实会先在看不见团队状态的情况下做一次
决定；如果它直接给最终答复，压缩根本不会发生，投影一次都没出现过。这直接违反"活动视图必须在模型决定
是否调用团队工具之前进入本次采样上下文"。

**修复**：把投影解析从"采样内部"提到 **provider 调用之前的显式控制流**。
- `capture_team_projection` 不再自己置标志，改为返回 `TeamProjectionOutcome`：
  `Nothing` / `Ready` / `NeedsRoom`。要不要腾地方由调用层决定。
- `run_turn` 在组装完 `sampling_request_input` 之后、调用 `run_sampling_request` 之前解析投影。
  遇到 `NeedsRoom` 就地跑 `run_auto_compact(..., CompactionPhase::PreTurn)`，然后**用压缩后的新
  prompt 重新取历史、重新渲染**，再进入正常采样。
- 渲染结果作为参数传进 `run_sampling_request`，仍在 retry 循环内的协议安全位置追加，所以"同一逻辑
  采样复用同一份投影"不变。
- 压缩后若仍放不下，只 `warn!` 一次并继续，不再压缩第二次。压缩已经把历史换成摘要，再循环下去只会
  死循环；这条退化路径有日志、有边界，如实记录而不是假装不存在。

### 2. 预算漏算 tools / output schema / 投影自身 framing（阻断）

**确认**：`remaining_request_context` 只减了 base instructions 与 `prompt_input`。实际 `Prompt` 还带
`ToolRouter::model_visible_specs()` 与可选 `output_schema`，二者都会真的发出去；动态 MCP/tool schema
可以很大，2k headroom 不能假定覆盖。渲染器估的又是纯文本，实际追加的是带 role/content framing 的
`ResponseItem`。

**修复**：新增 `PromptCost { input, base_instructions, tools }`，预算改为
`window − instructions − input − tools − output_schema − 投影 item framing`。
tools 与 schema 用 `serde_json` 序列化后估算（每次逻辑采样一次），framing 用一个常量。

## 测试

新增两条真实产品链用例，替换掉一条依赖窗口尺寸调参的旧用例：

- `no_room_compacts_before_sampling_instead_of_sending_a_projectionless_request` ——
  把窗口压到 14k 并灌入 6 条大体量 Event，实测请求序列为
  **①团队为空的首次采样（无投影，正确）→ ②压缩请求 → ③带投影的采样**。
  用例显式断言"压缩请求的下标必须早于第一个带投影请求的下标"，并断言**除压缩请求外，团队有活动事项
  之后的每一次采样都必须带投影**。我还确认了这条用例不是空过的：窗口调到 11k/9k 时压缩后仍放不下，
  用例会真的失败（说明断言有牙齿）；14k 才落在"压缩能救回来"的区间。
- `omitted_projection_content_is_retrievable_with_team_history` —— 改为**用团队内容体量**而不是窗口尺寸
  制造挤压（一次响应里开 10 个大 Event，超过 4k 硬上限），因此不再依赖本机 instructions/tool schema
  有多大。断言投影不超上限、仍带 `evt-` ID，并用真实 `team_history` 的 `next_before -> before`
  翻两页取回投影放不下的内容，游标确实前进。

| 命令 | 结果 |
|---|---|
| `just test -p codex-team-state -p codex-features` | **80/80 通过** |
| `just test -p codex-core -E 'team_world_state + only_verifiable_sessions'` | **8/8 通过** |
| `just test -p codex-core -p codex-rmcp-client` | 3542 跑，**3457 通过**，85 失败，13 skip |
| `just fmt` / `fmt-check` / `just fix -p codex-core -p codex-team-state` | 通过，fix 无改动 |
| `git diff --check` | 干净 |

85 个失败与首轮基线**集合逐条一致**（`comm` 双向差集为空），通过数比上轮 +1，即新增用例。
按既定口径，这只证明"无新增宽门禁失败"，不宣称其环境根因已独立证实。

## 仍需诚实说明的边界

- 预算现在覆盖 input、instructions、tools、output schema 与投影 framing，但它是**近似 token 估算**
  （复用仓库既有的 `approx_token_count` 与 `estimate_item_token_count`），不是 provider 的真实分词。
  4k / 2k / 20% 三个常量维持不变、未做测量调参。
- 压缩后仍 `NeedsRoom` 时会带 `warn!` 继续无投影采样。实践中压缩已把历史换成摘要，走到这一步意味着
  instructions + tools 本身就撑满了窗口，投影无力回天；不为此再加一层循环。
- 上一轮那次未复现的 flaky 本轮未再出现，按复验决策记为非阻断观察项，未继续追查。

## 未验证项（不阻断）

- `BUILD.bazel` / `MODULE.bazel.lock`：本机未安装 Bazel，按既定决策不安装、不下载、不冒充通过；
  两个文件均无变化。
- 未跑全 workspace；未使用 Docker、真实 API、真实本地模型、付费测评。

## 顶层文档

L6 仍有未合并提交且改动 `doc/WBS.md` 与 `doc/WBS-COMPLETED.md`，继续不动这两份共享文档。
M-1 子 WBS 保持"已按独立审查整改，待复验"。
