# Plan 042 —— Multi M-3 证据锚定实现

日期：2026-08-17 ｜ 分支：`worktree-042-multi-m3-evidence-anchoring` ｜ 基线：`main@0c1a5e4`
提交：`db39e28`（捕获与定位）、`8360bbf`（失败结果与产品纵切）

## 做了什么

让 Version 里的语义判断可以机械回溯到 Codex 当时真正保留的工具结果。

**捕获拆成两步**，因为这两个位置知道的事情不同。工具调用产出终态时，Harness 知道跑的是哪个工具、
它是真的跑完了而不是被放弃、结果是什么形状 —— 在这里**记下**观察。结果进入 conversation history 时，
Harness 才知道它真的被保留了 —— 在这里**铸造** Fact 并分配序号。这样就不存在"还没保留就标成可用"的引用。
两个落点分别是 `ToolRegistry::dispatch_any_with_terminal_outcome` 的两个终态分支和
`Session::record_conversation_items`。

**领域侧**（`codex-team-state`）只拥有 Fact 身份、每个 producer 的发布窗口和读取权限，payload 留在 Codex
那里。`publish` 在同一次 mutation 内取走本作者上次成功发布之后的新 Fact 并推进游标，所以被拒绝的发布不会
消耗证据，按 committed submission 回答的重试也不会漂移到之后的观察上。

**读取**沿 Event 图收敛：Root 读本团队证据，producer 读自己的，其他人只读自己可见 Event 的某个 Version
显式引用的那一条。新增窄工具 `team_evidence` 返回 producer、工具名、类别、可用状态、有界文本和截断信息，
不返回调用参数、相邻结果或 producer 的其他上下文。

首版支持集：**已完成、正式保留、body 为纯文本的工具结果**，成功与失败都算。

## 疑难问题

**失败结果不走 `Ok` 分支。** 退出码非零的 `shell_command` 返回 `Err(FunctionCallError::RespondToModel)`，
被宿主转成 `success: false` 的文本结果。只在 dispatch 的 `Ok` 分支记录观察会让"失败结果"这半个支持集
几乎为空，所以两个终态分支都记录；`Failure` 分支的类别与形状由 payload 直接决定，不必等消息。
dispatch 里更早的几处拒绝（未知工具、PreToolUse 拦截、PostToolUse 拒绝结果）刻意不记录：要么没跑，
要么跑出来的东西被替换掉了。

**"不可得"必须区分两种原因。** producer 当前未加载是暂时的，本次读取报 `unavailable`，但引用不写死；
只有 producer 的 history 确实已经丢掉那一项（compaction / 回滚）才把 Fact 永久降级。Version 的 authored
内容不可改写，所以引用永远留着，靠标注解释。

**发布窗口装的比预期多。** Root 的 `spawn_agent` / `wait_agent` 结果同样是它观察到的文本工具结果，
所以第一次发布会带上它们。这是"机械关联、模型不逐条挑选"的直接结果，行为正确；产品测试相应按
retention 顺序取最后一条断言，并显式记录了这条规则。

**环境坑（非本次改动导致）。** 本机 shell 里有环境代理，`no_proxy` 用的是 `127.*` 这类 glob，reqwest
不认，于是 core 集成测试打向 loopback wiremock 的请求全部被送去代理，12 个既有团队产品测试一起报
"expected 1 request, got 0"。清掉代理变量后同一批测试 0.6 秒全绿。跑这类测试必须显式
`env -u HTTP_PROXY … NO_PROXY=127.0.0.1,localhost`。

## 验收结果

命令均在 `multidev/` 下经共享构建锁执行；集成测试额外清空代理变量。

| 门禁 | 结果 |
|---|---|
| `just test -p codex-team-state` | 99/99 通过（原 78 + 新增 21） |
| `just test -p codex-core suite::team_evidence`（新增 M-3 产品纵切） | 2/2 通过 |
| `just test -p codex-core suite::team_world_state suite::team_routing`（M-1/M-2 回归） | 12/12 通过，无退化 |
| `just test -p codex-core team::evidence`（捕获/分类/解析模块门禁） | 4/4 通过 |
| 合并跑 `suite::team_evidence`+`team_world_state`+`team_routing`+`team::evidence`+`tools::`+`context::` | 538/538 通过 |
| `just clippy -p codex-core`、`just fix -p codex-team-state -p codex-core` | 通过，无告警 |
| `just fmt`、`just fmt-check` | 通过 |

产品纵切覆盖：成功文本结果 → FactRef → Version → Root 下钻；失败文本结果同样可用且被标为
`tool_result_failure`；M-2 route 后目标只读到该 Event 明确引用的他人证据，直接指名的 sibling 证据
被显式拒绝；目标追加的 Version 自动携带自己的新 Fact，Root 随后从多作者 chain 读到它；每条观察带独立
marker，断言返回里只出现目标 marker。团队工具与证据读取自身不产生 Fact —— 第二次发布的 `evidence_refs`
为空即是证据。

领域与模块门禁覆盖：同一轨迹重放得到相同的 observation-to-publication 关联；未被记下的结果在 retention
时不铸造任何东西（这是媒体结果、流式增量、被放弃调用、嵌套 code-mode 步骤和团队工具的统一排除机制）；
非文本 body、模型消息、tool-search 结果均不入支持集；发布失败不消耗窗口；重载成员不回退游标；后加入的
参与者不继承既有证据；跨实例引用报 reset；投影里的引用有上限并计数余量；history 被替换后下钻诚实报
`Gone`；超长观察被截断并报告真实长度。

未运行：全 workspace 测试、Docker、真实 API、本地模型、付费测评。功能默认关闭
（`features.multi_agent_v2.team_state_enabled = false`），关闭时不注册 `team_evidence`，新增路径全为空操作。
