# Plan 020 B7 canary 基线 failed 的归因调研

> 本报告的归因结论和实验约束已固定，分歧全部关闭；它不决定是否或何时重跑。当前实施顺序只见
> `doc/WBS.md` 与 `doc/WBS/eval-benchmark.md`。

> 文档性质：只读归因调研结论，不是实施计划，也不是对 RONDO 能力的评价结论。
> 调研日期：2026-08-13。
> 调研对象：Plan 020 B7 campaign v22（`p2-b7-canary-baseline-v22`）的 `failed` 终态。
> 参与方式：Claude 主调研 + GPT 独立复核，五轮交叉核验后**全部分歧已关闭**；第 1—8 节为双方一致的结论，
> 第 9 节记录分歧的收敛路径，第 10 节记录调研过程中被推翻的中间判断。
> 执行边界：全程只读。读取 lock/结果 JSON/run artifacts/agent transcript/源码，运行文本 diff 与本地概率验算；
> 未运行 Cargo、Docker、真实 API，未修改 v22 任何历史事实，未改动相关 worktree 状态。
> 时效说明：结论绑定 v22 的冻结事实与当时的 harness 代码；后续 harness 或 catalog 改动后需重新核验。

## 1. 冻结结论

> B7 按冻结合同正确形成 `failed`；唯一失败原因是对称一致性子门 `ab_delta_exceeds_aa_sigma`。
> 稳定三败/三过的方向性精确模式未出现，但该子门检验力很低，其未触发不能排除概率性回退。
>
> 未发现 RONDO 产品源码修改能够解释三项差异；生产路径改动在本次配置下休眠或行为等价，产品回退证据很弱。
>
> 本次 A/B 存在 catalog 导致的 161-token prompt 非对称、部分有效记录的 harness/deadline 混杂和非交错时间分块，
> 因而不满足严格等条件；无法在抽样随机性、供应商时变和测评设施影响之间归因。
>
> 机械 delta 本身是九题 9-vs-9 配对；212 vs 15 只是跨 campaign 原始记录量，不应作为 delta 的样本量表述。
>
> `sanitize-git-repo` 反映 verifier/golden 脆弱性，不应作为能力差异证据。
>
> 这是一个真实的机械一致性门失败，不是有效的 RONDO 能力回退结论。

## 2. 环境定位

v22 的四个组件分散在不同 worktree，且构建环境与执行环境不同源：

| 角色 | 位置 | 版本 / 摘要 |
|---|---|---|
| 测评 harness 代码 | `.claude/worktrees/0811-plan014-post-audit` | `eval_harness_commit=ba16cb2`（现 HEAD `1df4262`，ba16cb2 为其祖先） |
| wrapper / 启动 checkout | `.claude/worktrees/0811-plan014-paid-pair` | `14341a1`（detached，`git_dirty=false`） |
| 结果数据 | `.claude/worktrees/0811-p2-b7-results` | `564a602` |
| RONDO 二进制 | 构建 worktree `0810-p1-measurement` **已删除**；同 commit 现 checkout 于 `.claude/worktrees/0811-plan014-v10-measurement` | 源码 `cb652e1`，binary `d2f5063a…` |
| 冻结 Codex 二进制 | 构建源 `eval-data/sources/codex-rust-v0.147.0-be6e8ea…/` **已不存在**；等价只读快照 `codex-source-code/` 仍在同一 commit | 源码 `be6e8ea`（rust-v0.147.0），binary `8bd5f096…` |

限定在 P2 B7 campaign 记录内（`campaign_id` 以 `p2-b7` 开头），212 条 RONDO run 全部同一 binary SHA，
15 条 Codex run 全部同一 binary SHA，无二进制漂移。该限定必须保留：`runs.jsonl` 全量还包含少量
probe / pre-campaign 记录。

要字节级重建 Codex 二进制，需要先恢复 `eval-data/sources/` 下那棵源码树。

## 3. 源码对比：未发现能解释 delta 的产品代码机制

`mydev/codex-rs`@`cb652e1` 与 `codex-source-code/codex-rs`@`be6e8ea` 相比，94 个文件不同，非测试文件约 15 个。

单一"风险等级"轴无法描述这些改动——例如 realtime 的 `LOCAL_FS` seam 既是"生产可达且等价"、又"不在
`codex exec` 路径上"。因此按**四个正交维度**列出：

| 改动 | 编译进生产 | `codex exec` 可达 | 本 campaign 执行证据 | 相比上游的语义差异 |
|---|---|---|---|---|
| Guardian capture hook<br>`client.rs:1470/1674`、`guardian/evidence.rs:301` | 是 | 是 | fast-path 会执行（一次 atomic load 后返回）；capture 未激活 | 未激活时无差异；激活后对请求做规范化序列化并落盘，**不修改 payload** |
| `[auto_review]` model/effort/evidence 配置面<br>`config_toml.rs`、`guardian/review.rs` | 是 | 是 | **RONDO 侧启用，Codex 侧不支持** | 是 5.1 非对称的来源之一，不属于"休眠或等价" |
| DNS `HostLookup` 委托<br>`network-proxy/runtime.rs:55/360` | 是 | 条件可达（受 `profile_allows_configured_network_proxy` 门控，`config/mod.rs:570`） | 未证明三题触发 | 功能结果等价（同一 `lookup_host`）；新增 `Arc<dyn Fn>` + boxed future，微观开销未证明等价 |
| realtime `LOCAL_FS` seam<br>`realtime_context.rs:163/353` | 是 | **否**——唯一调用者是 `realtime_conversation.rs:1283` | 否 | 等价 |
| skills home override<br>`ext/skills/host_service.rs:123/189` | 是（**默认 `None` 分支生产执行**） | 是 | 可能，未取证 | `Some` 分支仅测试可达（setter 为 `#[cfg(test)]`）；`None` 分支等价 |
| `OutboundProxyPolicy::Direct`<br>`outbound_proxy.rs:99-108` | 是（`#[doc(hidden)]` 公开变体，**无 `#[cfg(test)]`**） | 当前产品工厂不产生（`config/mod.rs:3063-3070` 只给 `ReqwestDefault`/`RespectSystemProxy`） | 否 | 新分支仅由测试显式构造。属于"当前产品未选择"，不是编译期门控 |
| doctor probe seam<br>`cli/doctor.rs:1512/2907` | 是 | 否（`codex doctor` 子命令） | 否 | 生产 wrapper 传入真实 probe/client，行为等价；可注入替身仅测试使用 |
| `BrowserLaunch`<br>`mcp_skill_dependencies.rs:188`、`cli/mcp_cmd.rs` | 是 | 条件可达（core 的 MCP skill dependency OAuth 路径） | 三题无关（未配置 MCP server） | `Enabled` 等价于上游 `launch_browser=true`；`Disabled`（`--no-open-browser`）为新增 CLI 行为 |

其余为纯重构或测试模块内改动：`secrets/src/lib.rs` 的 `environment_id_from_cwd_with_repo_root`（等价），
`codex-api/src/files.rs` 的 fixture（位于测试模块内）。

**依赖**：两侧 `Cargo.lock` 各 1347 条目；135 条差异恰为 workspace 包版本归一化 `0.0.0 → 0.147.0`
（与 codex manifest 记录的 `workspace_lock_normalization` 一致），**其余 1212 条第三方依赖完全一致**。

**完全未改动**：prompts、`models-manager/models.json`（两侧 Git blob ID 同为
`fef0db08bd82538130176b0987aa2ece54fb2842`）、tool 定义与 handler、session/turn 循环、sandbox、
apply-patch、exec-server 生产代码。

结论：生产路径确有若干改动，但在本次配置下分别属于不可达、未触发、或功能结果等价；
**未识别出能够解释三题结果的有效行为差异**。

逐行核对的依据是：每一行在三个 delta 题上，RONDO 与 Codex 的差异只能落入三类之一——

- **对 payload 不可观测**：capture hook 未激活时的原子快路径、skills 多一次 `None` 匹配、
  `Direct` 新增的 match 分支。注意 Codex 侧完全没有 capture hook 这段代码，所以它是两个二进制在 exec
  路径上的真实差异，但差异内容仅为一次 `Ordering::Acquire` 原子读后返回，不进入请求内容。
  "等价"在此指行为等价，不是代码相同。
- **本配置下不可达或未触发**：realtime seam、doctor seam、`BrowserLaunch`、条件门控的 DNS 委托。
- **已单独归因**：`[auto_review]` 配置面。它在 RONDO 侧真实生效、Codex 侧不支持，不属于"休眠或等价"；
  其影响已在 5.1 归因（catalog 投影 → 161-token 非对称），且三题两侧 Guardian 请求数均为 0，
  不构成对三题结果的解释。第 1 节冻结结论中的"休眠或行为等价"应按此理解。

因此第 3 节的分类精度修正只影响后续审计的复核成本，**不改变第 1 节的能力归因结论**。

## 4. 结果拆解

四轮成绩：RONDO A/A `5/9`、`5/9`，RONDO A/B `5/9`，frozen Codex A/B `4/9`；`sigma=0`、`delta=3`、共同分母 9。

| task | AA-R1 | AA-R2 | AB-RONDO | AB-CODEX | RONDO 历史有效通过率 | Codex |
|---|---|---|---|---|---|---|
| db-wal-recovery | pass | pass | **fail** | **pass** | 12/21 | 2/3 |
| extract-elf | fail | fail | **pass** | **fail** | 4/17 | 0/1 |
| sanitize-git-repo | pass | pass | **pass** | **fail** | 8/8 | 0/1 |
| 其余 6 题 | 四轮完全一致 | | | | | |

已确认的事实：

1. **三题差异都是真实 verifier 判定**，均无 infra 参与。
2. **Guardian 在三题两侧均未触发**（`api_request_roles.guardian == 0`），因此 RONDO 的 Guardian
   model/effort/evidence 改动不可能解释这三题。
3. **AB-RONDO 轮的 db/extract 两个 run（`380000021`/`380000022`）本身就是 v18 的第三个 RONDO 轮次**，
   与 AA 两轮同二进制、同配置。RONDO-vs-RONDO 三个配对的不一致数分别为 0 / 2 / 2，
   即 delta 中的 2 项是 RONDO 自身跨轮就会翻面的题。
4. **db-wal-recovery 的条件加跑两侧都翻面**：RONDO repeat1 fail / repeat2 pass；Codex repeat1 pass / repeat2 fail。
5. **delta 方向不一致**：三题中 RONDO 赢两题、Codex 赢一题，总分 RONDO 高于 Codex。

### `sanitize-git-repo` 是 golden 脆弱性

从 `eval-data/work/20260812-420000038-tb-codex-r1/.../agent/codex.txt` 的完整 transcript：

- `item_12`：Codex 已产出**逐字节正确**的 golden 内容（`https://<your-github-token>@…`、
  `--token <your-huggingface-token> -y`，均未加引号）。
- `item_15`：Codex 明确推理"尖括号占位符在未加引号时是 shell 元字符，我要给它们加引号以保持示例语法可用，
  同时保留占位符原文"。
- `item_16`：改写 `ray_cluster.yaml` 加引号 → verifier 逐字节比对失败，
  `test_correct_replacement_of_secret_information` 单项失败（另外 2 项通过）。

这是一次有理由的工程判断被字节级 golden 判负，不是随机抖动，也不是能力差异。

## 5. 已确认的实验设计缺陷

### 5.1 161-token prompt 非对称（最重要）

九道 A/B 题的首个 main 请求，RONDO 输入 token **一律**比 Codex 多**恰好 161**：

| task | RONDO in | CODEX in | diff |
|---|---|---|---|
| db-wal-recovery | 14422 | 14261 | +161 |
| extract-elf | 14399 | 14238 | +161 |
| filter-js-from-html | 14383 | 14222 | +161 |
| fix-git | 14301 | 14140 | +161 |
| headless-terminal | 14398 | 14237 | +161 |
| openssl-selfsigned-cert | 14557 | 14396 | +161 |
| polyglot-c-py | 14368 | 14207 | +161 |
| sanitize-git-repo | 14442 | 14281 | +161 |
| sqlite-db-truncate | 14320 | 14159 | +161 |

机制：冻结 catalog 共 8 个模型；`eval/rondo_eval/frozen_model_catalog.py` 的
`_catalog_with_auto_review_override()` 因 main == guardian == `gpt-5.6-sol` 而把 Codex 侧裁剪成**单一模型**，
而 `adapters.py` 的 validator 显式禁止 RONDO 接收 `model_catalog_json`，RONDO 走内置**8 模型** catalog。
`core/src/tools/handlers/multi_agents_spec.rs` 的 `spawn_agent_models_description()` 把 picker-visible 模型
枚举进 `spawn_agent` 工具描述，形成这段常量差。

**权重表述（双方一致）**：这是确定的实验协议违规；**没有证据证明它造成三题翻面，也没有证据允许把它安全忽略。**

已确认的边界事实：

- `spawn_agent` 在全部相关 transcript 中调用数为 0（Claude 抽查 6 份，GPT 扩查 22 份）。
  这只能排除"工具被真实执行改变结果"，**不能**排除"模型读取工具描述后采样轨迹变化"。
- `cached_input_tokens` 无一致侧向规律（RONDO 高 6 题、Codex 高 2 题、`extract-elf` 两侧同为 3840），
  只能证明运行时缓存命中状态不同，**不能**用于支持因果判断。

**该非对称的精确作用域（双方一致的登记表述）**：

> 九题首个 main 请求观测到的固定 +161 input tokens，源码定位为 catalog 裁剪造成的 `spawn_agent`
> 工具描述差异。Responses Lite 将该工具描述作为 developer `AdditionalTools` 前缀插入请求；在同一
> `codex exec` turn 内，每次 main sampling 都会重复包含同一 catalog 派生段。该段的生成不依赖任务正文，
> 但进入模型上下文后仍可能影响采样，因此不构成因果上界。双方加载同一份完整冻结 catalog 可以确定性消除
> 这一特定结构差；是否实现完整请求等价，仍由发送前规范化摘要硬门验证。

源码锚点：`multi_agents_spec.rs:781`（`spawn_agent_models_description`）、
`client.rs:862-870`（`AdditionalTools` 前缀先于 base instructions 压入）、
`turn.rs:1285`/`turn.rs:1319`（`build_prompt` 取 `router.model_visible_specs()`，
每次 sampling 复用同一 `step_context.tool_router`）。

三处必须避免的过度表述：**不能**说"每个请求都是 161-token 差异"（只测了首请求，此后双方历史已分叉，
源码只能证明同一字节段重复出现，不能证明总计费 token 差恒定）；**不能**说"与任务内容不交互"
（准确说法是"该段的生成不依赖任务内容"）；**不能**说"catalog 修复后确定性清零"而不限定对象
（清除的是已定位的 catalog 派生段，不保证完整请求字节相同或总 input token 差为零）。

### 5.2 harness commit 与 upstream deadline 混杂

v22 聚合引用的记录来自多个 harness 版本：

| 侧 | harness commit 分布 |
|---|---|
| RONDO | `ea1563e`×20、`ba16cb2`×17、`14b2bb6`×4、`8ad17cf`×1 |
| Codex | `ba16cb2`×15（100% 单一版本） |

`ea1563e` 的 RONDO 记录不含 `provider_upstream_timeout_seconds` 字段（90 秒时代），Codex 记录为 `180.0`；
lock 以 `timeout_compatibility=monotonic_extension` 接受该单调放宽。

减轻因素：`ea1563e → ba16cb2` 之间 `adapters.py` 与 `runner.py` **零改动**，只改了 `api_budget_proxy.py`（+131 行），
容器命令与 prompt 未变。

未排除的风险：deadline 差异产生**有效性选择效应**——90 秒下超时的 run 变成 infra 出局，180 秒下能存活，
两侧"哪些 run 成为有效结果"的筛选条件不同。

### 5.3 时间分块不交错

| 轮次 | 执行窗口 | campaign 来源 |
|---|---|---|
| AA-RONDO-1 | 23:51 – 00:23 | 全部 v18 |
| AA-RONDO-2 | 00:29 – 00:58 | 全部 v18 |
| AB-RONDO | 01:07 – 04:27 | v18 / v19 / v20 / v22 |
| AB-CODEX | 04:30 – 05:03 | 全部 v22 |

A/A 两轮相邻 32 分钟且同一 identity；A/B 的 RONDO 侧横跨三个多小时与四个 campaign，Codex 侧是单独一整块。
两侧未逐题交错。无 seed、无 backend snapshot、无 system fingerprint，
**供应商侧时变与普通输出随机性在本数据中不可分离**。

### 5.4 样本量的正确口径

这几个数字必须分开陈述，不能混用：

| 口径 | RONDO | Codex | 用途 |
|---|---|---|---|
| campaign-bound 原始 ledger 记录 | 212 | 15 | 跨 campaign 工作量，含 infra / replacement / 已退役 identity |
| 历史 completed 记录（Jeffreys 用） | 105 | 11 | 事后历史率与统计解释 |
| v22 assessment 使用的结果 | 29（27 基础 + 2 条件） | 11（9 基础 + 2 条件） | 本次评估的实际输入 |
| **机械 delta 的配对** | **9** | **9** | ab-rondo-1 vs ab-codex-1 逐题一对一 |

正确表述：**Codex 每题只有一个正式基础样本，而 RONDO 另有两轮 A/A；辅助历史严重侧向不平衡。**
`212 vs 15` 影响的是事后历史率与统计解释，**不影响机械 delta 的一对一计算**，不应列为 delta 的样本量不等。

## 6. 统计参考量（已降权）

以 105 条 RONDO + 11 条 Codex 有效运行（共 116 条）做 Jeffreys 平滑，构造"两侧能力相同"的 plug-in 模型：

- `E[两轮不一致数] = 1.61`
- `P(不一致 = 0) = 0.143`
- `P(不一致 ≥ 3) = 0.192`

**这不是显著性检验。** 叠加第 5 节的 prompt 非对称、harness/deadline 混杂与跨 campaign 时间跨度，
iid 假设被多重违反。该数字仅作数量级 sanity check，不得作为归因证据。

## 7. 判据机制的准确表述

`doc/WBS.md` 的 M2 判据把两条子门写成显式的"且"，两者目的不同、互补，**不构成逻辑矛盾**：

1. `delta <= sigma`：行为一致性 / 可复现性门（对称计数，不区分方向）。
2. `stable_directional_regression`：高特异度回退兜底门（该题触发后 RONDO 三次全败**且** Codex 三次全过）。

`eval/rondo_eval/terminal_bench/baseline.py` 的实现与之一致：
`sigma` 硬编码为 `aa-rondo-1` vs `aa-rondo-2` 的**预注册配对**（不是事后从三个配对中挑最小），
方向性子门单独计算。v22 最终 `reasons` 只有 `ab_delta_exceeds_aa_sigma` 一条。

需要明确的两点（双方一致）：

- 方向性子门未触发只能排除"三败对三过"这一个精确模式，其检验力极低，**不能**解读为"回退检测通过"。
- WBS 的 M2 判据本身命名准确（"A/A 对称性检验"），**定义不需要改**。误称出现在下游：
  `plan/020` 的阻塞项与当前验收状态、`agent_log/2026-08-12-230705` 写作"B7 性能门"，
  且 assessment 只输出统一的 `reasons`、不单列两个子门状态。要调整的是下游表述与 assessment 输出结构。

## 8. 若另行执行时必须满足的实验约束

### 8.1 catalog 字节一致 + provenance 绑定

保留完整 8 模型 catalog，只在目标 entry 上设置 `auto_review_model_override`，两侧加载同一份 catalog 字节。
两侧原始 `models.json` 的 Git blob ID 已确认完全相同（`fef0db08bd82538130176b0987aa2ece54fb2842`），
该方案有明确基础。

catalog 身份从"必须等于各自二进制 source commit"改为**独立冻结的 artifact SHA**。
但仅绑定最终 SHA 只能证明"没漂移"，不能证明"来源正确"，因此 lock 应同时记录：

- 最终投影 artifact 的 SHA-256；
- 上游与 RONDO 两个来源的 commit / path / blob ID；
- 投影算法与 schema 版本；
- main model、Guardian model；
- 被设置 override 的目标 entry。

改动范围不止投影函数：`adapters.py` 显式禁止 RONDO 接收 frozen catalog，并把 catalog source commit
硬绑到各自二进制的 source commit，`runner.py` 在请求层有同样的 fail-closed 约束，这些身份约束需要一并重构并补测试。

### 8.2 发送前的规范化请求硬门

在上游 forward 前比对两侧同题请求剔除任务内容后的 tool-spec / instructions 区块摘要，不一致直接 fail-closed。
token 数只能作第二重报警：不同内容可能产生相同 token 数，且 provider usage 在请求完成后才返回。

现有原语可用但**不足以直接复用**：

- 已有：proxy 在 upstream forward 前读取完整 body（`api_budget_proxy.py:1110`），
  已有 canonical JSON 编码与 SHA（`:1871`），SHA 在发送前即可算出。
- 仍需新增：
  1. **main prompt 分区投影**——现有 `canonical_body_sha256` 对 main 请求是整份 JSON 哈希
     （`:2005`，`canonical_request_sha256(value)`），包含任务输入与动态字段，不是现成的
     tool-spec / instructions 分区摘要；
  2. **跨 run、跨 side 的期望摘要存取状态**；
  3. **无上游 preflight**——若等 Codex 请求到达 proxy 再对照先前的 RONDO 请求，
     虽能在 Codex 发送前阻断，但 RONDO 半边已经产生费用；
  4. 明确的 fail-closed 原因码。

补充可行性说明：preflight 不需要新的付费路径——两侧二进制可以对本地 stub endpoint 零成本驱动，
campaign 已有 wire-canary 与 no-API Oracle 两条无上游执行先例。

### 8.3 执行条件统一

固定同一 harness commit、同一 upstream deadline；逐题交错执行 A/B，两侧重复次数相同。

### 8.4 判据方向性显式化

预先声明检测目标是"方向性回退"还是"行为不一致"，并在 assessment 中分别输出两个子门状态；
条件重复应真正参与最终聚合，而不是只做兜底模式匹配。

### 8.5 重复数由 pilot 预冻结

pilot 后、正式数据前冻结每题重复数；波动题两侧使用相同的奇数重复次数（至少 3 次）；
所有题保留在结果与分母中，**不事后删题**。
pilot 必须在已修复 catalog、harness commit、deadline 与执行顺序的环境下完成；
v22 混杂数据只能作选题线索，不能充当稳定性标定。

### 8.6 不采用"三轮 pairwise max 作为 sigma"

以 116 条历史记录的 Jeffreys plug-in 参数，对九题联合分布直接计算（两方独立计算，3 位有效数字一致）：

| 规则 | E[σ] | P(σ=0) | P(σ>2) |
|---|---|---|---|
| 现行两轮 `Σ_t d₁₂,t` | 1.61 | 0.143 | 0.193 |
| **原提议 全局 pairwise max `max(Σ_t d₁₂, Σ_t d₁₃, Σ_t d₂₃)`** | **2.27** | 0.033 | **0.390** |
| 逐题 union `Σ_t max(d₁₂,t, d₁₃,t, d₂₃,t)` | 2.42 | 0.033 | 0.453 |

原提议把容忍预算抬高约 1.41 倍，且有约 **39%** 概率直接撞上冻结的 `max_sigma=2` 上限
（`aa_sigma_exceeds_frozen_stability_limit`），因此不采用。

注意第三行是**另一条规则**（"九题中有多少题三轮不全相同"），不是原提议的等价形式；
一般情况下 `max(Σd) ≠ Σmax(d)`。它作为"逐题不稳定计数"或许更自然，但若要采用必须重新命名并预注册，
本调研不提议采用。

## 9. 分歧记录（已全部关闭）

四轮交叉核验中出现过的分歧均已收敛，本节保留收敛路径供后续审计：

| 分歧 | 收敛结果 | 落在 |
|---|---|---|
| catalog 身份该绑二进制 source commit 还是独立 artifact SHA | 采用独立 artifact SHA，**并追加 provenance 五项记录**（仅绑最终 SHA 只能证明没漂移，不能证明来源正确） | 8.1 |
| 规范化硬门放离线预检还是代理发送前 | 两者不冲突；现有 proxy 原语可用但不足以直接复用，仍需 main prompt 分区投影、跨侧比较状态与无上游 preflight | 8.2 |
| "B7 性能门"误称该改 WBS 还是下游文档 | WBS 的"A/A 对称性检验"定义准确，不改；调整下游表述与 assessment 输出结构 | 7 |
| 生产路径改动的分类粒度 | 分类原则成立（"生产执行但等价"与"替代行为仅测试可选"风险等级不同），但单轴 A/B/C/D 混合了四个正交维度，改为四维矩阵 | 3 |
| 161-token 非对称的作用域描述 | 观察核心成立，但须收窄三处措辞（首请求 ≠ 每请求；生成不依赖任务正文 ≠ 不影响采样；清零对象限定为已定位的 catalog 派生段） | 5.1 |

## 10. 本次调研中被推翻的中间判断

记录在此以免后续被重新引用。

1. **"两侧配置基本对齐"** —— 错误。已由 5.1 的 161-token 常量差证伪。
2. **"sanitize 是模型输出格式抖动"** —— 错误。transcript 显示是 Codex 主动的、有理由的工程判断（见 4 节）。
3. **"谈不上供应商侧模型能力波动"** —— 越界断言。无 seed / fingerprint，抽样噪声与供应商漂移不可分离。
4. **"sigma 取自三个 RONDO 配对里最小的一对"** —— 措辞不当。该配对是**预注册**的，不是事后选择；
   准确表述是"预注册的这一对事后恰好是三个配对中最稳定的一对，估计量结构性偏乐观"。
5. **"两个子门内部不自洽"** —— 错误。WBS 与实现都写成互补的"且"，逻辑上不矛盾（见 7 节）。
6. **"Cargo.lock 共 1219 个包"** —— 数字错误。1347 条目 / 135 workspace 归一化 / 1212 第三方一致；
   1219 是唯一包名数（同名不同版本的包被折叠）。第三方 0 差异的结论按 multiset 重算后成立。
7. **"116 个 RONDO 有效运行"** —— 数字错误。实为 105 条 RONDO + 11 条 Codex = 116 条。
8. **"三轮 pairwise max 严格优于 n=2"** —— 错误。它抬高容忍预算、降低检出真实小差异的能力，是取舍而非改进。
9. **"三轮 pairwise max 的 E[σ]=2.42、P(σ>2)=45.3%"** —— 计算错误。该数字对应的是逐题 union
   `Σ_t max(d_t)`，不是原提议的 `max(Σ_t d_t)`；正确值为 E[σ]≈2.27、P(σ>2)≈39%（见 8.6）。
10. **"161 token 的根因先验不高"** —— 工程直觉冒充证据。`spawn_agent` 未被调用只排除工具执行路径，
    不排除采样轨迹变化；`cached_input_tokens` 无侧向规律，不支持因果。
11. **"方向性回退检测通过了"** —— 扩大解读。准确表述是该子门在机械意义上未失败，其检验力极低。
12. **"规范化硬门不需要新基础设施，直接复用 proxy 现有原语即可"** —— 低估。现有 canonical hash 是整份
    JSON 哈希，仍需 main prompt 分区投影、跨侧比较状态与无上游 preflight（见 8.2）。
13. **"样本量 212 vs 15"作为 A/B 实验缺陷** —— 口径错误。机械 delta 是 9-vs-9 配对；
    212 vs 15 是跨 campaign 原始记录量（见 5.4）。
14. **"agent 执行路径仅新增 Guardian evidence 落盘"** —— 过窄。生产路径另有 DNS 委托、realtime fs 包装等改动，
    只是在本次配置下行为等价或不可达（见 3 节）。
15. **"capture hook 只克隆 request 做记录"** —— 描述错误。hook 收的是 `&request`；未激活时一次 atomic load
    后返回，激活后执行规范化序列化（`guardian/evidence.rs:301-325`）。不修改 payload 这一点成立，
    但既不是 clone，也不是简单记录。
16. **生产路径改动的单轴 A/B/C/D 分级** —— 不精确，混合了四个正交维度。典型反例：realtime `LOCAL_FS` seam
    同时是"生产可达且等价"与"不在 `codex exec` 路径上"。已改为四维矩阵（见 3 节）。伴随的三处具体错标：
    - `home_dir_override` 归入"仅测试可达"忽略了生产每次都执行的新增 `None` 默认分支；
    - `OutboundProxyPolicy::Direct` 与 `#[cfg(test)]` setter 是**两种不同**的不可达
      （前者编译进生产、只是工厂不选择）；
    - `BrowserLaunch` 整体归为"CLI 专用"错误——`core/src/mcp_skill_dependencies.rs:188`
      的生产路径显式传 `Enabled`，等价于上游 `launch_browser=true`。
17. **"161 token 位于每个请求的稳定前缀、九题恒为 161、与任务内容不交互"** —— 三处过度表述。
    只测了首个 main 请求，此后双方历史分叉，源码只能证明同一字节段重复出现，不能证明总 token 差恒定；
    "与任务内容不交互"应为"该段的生成不依赖任务内容"——它进入模型上下文后仍可能影响采样，
    这正是不能排除其因果作用的原因。修正后的登记表述见 5.1。
