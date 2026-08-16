# Plan 038 / Multi M-1 审查整改

日期：2026-08-16 ｜ 工作树：`.claude/worktrees/039-multi-m1-team-world-state` ｜ 被审查提交：`f974af0`
｜ 审查报告：`agent_log/2026-08-16-040832-plan038-m1-independent-acceptance-review.md`

## 结论先说

审查报告列出的 5 个阻断项和 3 个窄修项，**逐条核对源码后全部属实**，没有误报。已全部修复。
其中第 3 项（member 可向不可见 Event 追加从而获得整条 chain 的读权限）是真实越权，影响最重。

## 逐项修复

### 1. 投影硬预算与近窗口语义（阻断）

**确认**：`render.rs` 的削减循环在"只剩一个 Event 的一条 Version"时 `break` 并原样返回，超预算；
authored 字段无长度上限，单条超长内容即可突破 4k cap；预算低于阈值时对非空活动视图直接返回 `None`，
该次采样完全看不到团队状态。我原来的 `a_request_with_almost_no_room_left_skips_the_projection_entirely`
把这个错误行为固化成了通过用例 —— 这是最糟的一类测试，已删除。

**修复**：
- authored 内容在**写入时**就有界（title 200 / summary 2000 / handoff 1000 字符，超出截断并留可见标记），
  所以 store 里不存在无界字段，投影与历史因此是构造性有界，而不是靠每个消费方各自记得裁剪。
- 削减循环不再 `break` 放弃：削无可削时改渲染固定尺寸的省略通告。
- 取消"预算不足就返回 None"。活动视图非空时**永远**输出内容；极端预算下退化为一条不可再缩的通告，
  说明有多少事项被省略、去哪里取回。

**这里我改了审查报告建议的做法**：报告倾向于"硬 clamp 到预算内"。我先按此实现，但新加的集成用例立刻
暴露出后果 —— 极小预算下 clamp 会产出 `<team_active_world_index></team_active_world_index>` 这样的
空块。空块比超预算更糟：它等于告诉模型"团队没事发生"，而模型无从分辨真假。所以最终把这条通告定为
**不可再缩的下限**，允许它在病态小预算下略微超出，并在代码注释里写明理由：通告只有几十 token，不可能
把请求顶爆；真正到了那一步，回收空间的是已有的 compaction 路径，不是投影。

**新覆盖**：单条超长内容在各档预算下都不破 cap；近窗口时活动视图不消失且必须给出去处；写入时有界。

### 2. `team_history` 有界性与下钻（阻断）

**确认**：列表模式只限制 Event 数量，每个 Event 仍返回完整 chain；`HistoryQuery` 只有 `event_id + limit`，
没有游标，超过上限的更老内容永远取不回来 —— 投影报告的 omitted 成了死信。

**修复**：加 `before` 游标与 `next_before` 返回值，两种模式都可向前翻页；列表模式每个 Event 只预览最新
2 条并如实报告 `omitted_versions`，完整 chain 由 event 维度查询获得，后者本身也可翻页。工具 schema 与
输出同步加了 `before` / `next_before`。

**新覆盖**：领域层"每页 3 条一路翻到最老一条，全部 12 条都能取回"；列表模式不再拖出全部 Version；
以及一条**真实产品链**集成用例 —— 上下文窗口压到 10k，投影被迫丢弃旧条目并给出去处，模型随即用真实
`team_history` 工具把被丢弃的内容取了回来。

### 3. Member 可通过 append 自行扩权（阻断）

**确认**：`publish` 对 `ExistingEvent` 只校验引用存在。Event ID = 实例 tag + 递增小 ordinal，而实例 tag
在每个参与者自己的投影 header 里就能看到，因此 member 可以拼出 sibling/root 的 Event ID，先追加、再因
"成为作者"读到整条 chain。同一个 store 的 history 拒绝规则与之直接矛盾。

**修复**：可见性同时决定可读与可贡献（与设计合同第 21 条一致，第一版本就是这个语义）。
`is_readable_by` 更名 `is_visible_to` 并同时用于读与写；append 前先校验可见性，越权返回 `NotPermitted`。

**测试整改**：原并发用例让 8 个互不可见的 worker 追加同一个 Event，**正是依赖这个越权**才能通过。已改为
两个真正有资格的 actor（Event 作者 + Root）各自并发提交并重试，仍然覆盖并发与幂等；另加一条 sibling
拒绝回归，并断言拒绝之后读权限也没有被顺带打开。

### 4. Root 终态可原地重开（阻断）

**确认**：`SetRootState` 允许 `resolved -> pending/tracking`，与"已进入终态的 Version 不原地重开，
重新相关时追加新 Version"冲突，会把旧 Version 原地拉回活动视图，破坏追加式历史语义。

**修复**：`resolved` 成为 Root 侧终态，任何离开它的转换返回 `RootAttentionResolved`，错误信息直接告诉
模型"要重新相关就发新 Version"。加回归用例。

### 5. 产品身份边界（阻断）

**确认**：原实现把所有非 SubAgent source（含 `Internal`、review、compact）登记为 **Root**，缺 agent path
的 SubAgent 还回退成 `/root`。即便这些会话目前拿不到团队工具，登记政策本身与 fail-closed 标准不符。
实例 tag 只有 8 个 hex（32 bit），不是完整实例身份。

**修复**：
- 新增 `team_participant_identity`，只承认两种可核验形态：用户面 root 线程（Cli/VSCode/Exec/Mcp/Custom）
  → Root；带 agent path 的 V2 `ThreadSpawn` → Member。其余（Internal、Review、Compact、
  MemoryConsolidation、Other、无 path 的 spawn、Unknown）一律不登记，因而拿不到任何团队能力。
- 对外引用改携带**完整 UUID**，实例归属成为可精确校验的事实而非概率判断。代价是引用字符串变长、投影
  略占更多 token；正确性优先。

**新覆盖**：`only_verifiable_sessions_get_a_team_identity` 逐个断言上述可核验/不可核验形态。

### 窄修项

- **幂等未绑定请求内容**：同一 `request_id` 配不同 payload 会被静默当作重试，第二份内容丢失。现在记录
  请求指纹，内容不一致返回 `RetryIdentityReused`，并有用例断言第一份内容没有被破坏。
- **开关不一致**：协议前缀/投影/wait 只看 `team_state_enabled`，工具注册还受 Collab/MultiAgentV2 约束，
  组合配置下会出现"模型看到协议和投影却没有工具"。现在四处共用同一个 `team::team_state_enabled`，
  它内部同时检查三者。
- **Bazel lock**：按用户本轮明确指示，**不作为验收门禁**，也不为此安装 Bazel。见下文未验证项。

## 测试结果

全部经共享构建锁与看门狗，未直接调用 cargo，代理变量已剥离。

| 命令 | 结果 |
|---|---|
| `just test -p codex-team-state -p codex-features` | **76/76 通过**（team-state 43，较修复前 +7） |
| `just test -p codex-core -E 'team_world_state + only_verifiable_sessions'` | **7/7 通过**（集成 6 + 身份单测 1） |
| `just test -p codex-core -p codex-rmcp-client` | 3541 跑，**3456 通过**，85 失败，13 skip |
| `just fmt` / `just fmt-check` / `just fix -p codex-core -p codex-team-state` | 通过，fix 无改动 |
| `git diff --check` | 干净 |

**85 个失败与修复前逐条比对，失败集合完全一致**（`comm` 双向差集为空），通过数由 3454 升到 3456，
即新增的两条用例。也就是说本轮整改没有引入任何新失败。这 85 条仍是环境限制（code-mode host 的 V8
预编译包下载 404、package 范围外的 `codex`/exec-server 二进制、真实网络），按审查报告口径记为
"环境归因、未独立确认"，不作为验收依据。

## 未验证项（不阻断）

- `BUILD.bazel` 与 `MODULE.bazel.lock`：**当前环境未验证**。本机没有安装 Bazel，按用户指示不为 M-1 安装、
  不触发额外下载。`MODULE.bazel` 与 `MODULE.bazel.lock` 均未变化（本次只新增工作区内 path 依赖，没有新
  外部依赖），依赖正确性由 Cargo lock、定向 Rust 测试与 diff 审查兜底；将来环境具备 Bazel 时再顺手验证。
- 未跑全 workspace 测试；未使用 Docker、真实 API、真实本地模型、付费测评。

## 顶层文档

L6 仍有未合并提交且改动 `doc/WBS.md` 与 `doc/WBS-COMPLETED.md`，继续不动这两份共享文档。
M-1 子 WBS 状态按审查要求改为"已按独立审查整改，待复验"，不冒充验收通过。
