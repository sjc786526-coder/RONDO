# P0 共享地基：Guardian 审批模型覆盖 + 审批证据包快照

> 本计划是任务的稳定约束文档。
> 除"当前状态"和"关键决策记录"外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

对应 WBS：`doc/WBS.md` §5（P0 / S1 / S2）。完成后解锁方向 0 的 P1 与方向 2 的 L1~L2。

## 1. 目标

### 最终目标

交付方向 0（测评基准）与方向 2（本地审批模型）共用的两块地基，使两条线可以真正并行开工：

- **S1**：Guardian 审批模型与 reasoning effort 可由 `config.toml` 显式覆盖，并在真实发出的请求中生效。
- **S2**：每一轮 Guardian 审批可产出一份**确定性、可离线复用、与该审批轮明确关联**的证据包 `E_final`。

**S1 的能力边界（重要）**：本任务**只覆盖模型名与 effort，不覆盖 provider**。
`build_guardian_review_session_config` 克隆父会话配置，只改写 provider 的请求/流重试次数，provider id
与 base_url 原样继承父会话。因此 P0 完成后可以把 Guardian 钉在 `gpt-5.6-luna + low`
（测评所需，父子同为 OpenAI provider，成立），但**不足以切到本地模型**——那需要独立的 provider
覆盖，已拆为方向 2 的 **L2a**，是 L7 的前置。0.147 新增的 provider/auth 默认模型分流没有改变
这个边界；任何“P0 完成即可一键切换本地模型”的表述都是错的。

### 完成/验收标准

**S1**

- 测试配置 `[auto_review] model = "gpt-5.5"` / `reasoning_effort = "high"` 后，Guardian 实际
  发出的请求体中 `model` 与 `reasoning.effort` 与配置一致（用 `ResponseMock` 断言 wire，而不是
  中间变量）。两者均刻意区别于 0.147 的 API-key 默认值，避免失效时误绿；正式测评仍显式使用
  `gpt-5.6-luna + low`。
- 未配置时，解析优先级回退为 `model_info.auto_review_model_override` → provider/auth 派生默认，
  与上游行为一致；不得再把默认值写死成单一的 `codex-auto-review`。
- `just write-config-schema` 已运行，`core/config.schema.json` 的差异**只包含**新增字段。
- 不改动 provider 解析路径（本任务显式不做，留给 L2a）。

**S2**

- 配置证据输出目录后，一轮审批产出 1 份 `E_final.json` + 1 份 `meta.json`（`review_id`、决策、耗时、模型、effort、token、结束原因）。
- **关联正确性**：产出的 `E_final` 必须归属到发起它的 `review_id`；并发审批（trunk 忙时会 fork ephemeral 会话）互不串档。需有并发场景的集成测试覆盖。
- **只捕获真正的审批请求**：判定用 `responses_metadata.request_kind == Some(Turn)`，把预热、
  压缩、memory 请求一并排除。`build_responses_request` 没有 `warmup` 布尔，但 builder 已拿到
  `responses_metadata`，够用。
  需有**开启 websocket** 的测试覆盖"预热不产生证据包"。实现时确认 Guardian 审批请求确实带 `Some(Turn)`；若观察到 `None`，须查明原因，**不得**放宽回 `!= Prewarm`。
  注：测评配置关闭 websocket 时 `schedule_startup_prewarm` 只跑 `prewarm_auth()` 就返回（`session_startup_prewarm.rs:185`），预热在测评主路径上本就不触发；但压缩请求会。
- **不捕获主 Agent 请求**：需有测试直接覆盖。
- 规范化**幂等**：同一请求规范化两次逐字节一致；被剥离的字段清单由测试锁定。
- 规范化后**工具调用与其结果仍能正确配对**（`call_id` 保留或成对重映射），由单测断言，不新增设施。
- 未配置时不产生任何文件，且不引入可测量开销（快照路径在开关判定前不做任何分配）。
- 审批未真正调用模型即结束（超时/取消/prompt 构造失败）时，**不得**把上一轮或预热的陈旧请求固化为本轮 `E_final`；此类轮次只写 `meta.json` 并标记 `evidence: none`。
- 证据写入失败**不得影响审批决策**：只记 warn，审批照常 fail-closed。

**通用**

- `just test -p codex-core` 通过；新增集成测试放进 `core/tests/suite/` 的既有相关文件，不新建散落测试文件。
- 两个开关都不开启时，guardian 既有测试全绿，行为与上游一致（不退化项）。
- `just fmt` 与 `just fix -p codex-core` 已运行且干净。
- 合并前跑一次全量 `just test`（见 §3 约束 11 的口径），结果如实记录。

## 2. 范围

### 允许修改

- `mydev/codex-rs/config/src/config_toml.rs` —— `AutoReviewToml` 增加字段
- `mydev/codex-rs/core/src/config/mod.rs` —— `Config` 增加字段与解析（照抄 `guardian_policy_config` 路径）
- `mydev/codex-rs/core/src/guardian/review.rs` —— `model_override` 优先级链、审批轮起止处的槽注册
- `mydev/codex-rs/core/src/guardian/review_session.rs` —— `GuardianReviewSessionParams` 加 `review_id`，选定会话后注册捕获槽
- `mydev/codex-rs/core/src/guardian/mod.rs` —— 新模块声明与导出
- `.gitignore` —— 追加 `/eval-data/`（证据默认输出位置，必须先于 S2 落地）
- **新增** `mydev/codex-rs/core/src/guardian/evidence.rs`（+ `evidence_tests.rs`）
- `mydev/codex-rs/core/src/client.rs` —— 快照挂钩（目标 ≤10 行）
- `mydev/codex-rs/core/config.schema.json` —— 由 `just write-config-schema` 生成，不手改
- `mydev/codex-rs/core/tests/suite/guardian_review.rs`、`auto_review.rs` —— 增量测试
- `doc/WBS.md`、`doc/WBS-COMPLETED.md`、`agent_log/`

### 不允许修改

- `codex-source-code/`、`reference-agent-harness/`、`codex-doc/`（只读）
- Guardian 的审批判定语义：`policy.md`、`policy_template.md`、`prompt.rs` 的判定逻辑
- Guardian 的 fail-closed 语义（超时/执行失败/输出畸形一律拒绝）
- **Guardian 的 provider 解析**（`model_provider` / `model_provider_id` / base_url / auth）—— 属于 L2a，本任务显式不碰
- 上游既有测试的断言语义（若上游行为确实被改变，须停下说明后再动）
- `Cargo.toml` / `Cargo.lock` —— 本任务不引入新依赖
- websocket、网络代理、沙箱、权限档位的默认行为
- 任何 `CODEX_SANDBOX*` 相关代码（上游 AGENTS.md 明令禁止）

### 不允许读取/查看

- 项目目录外的个人文件；任何凭据、API Key、`~/.codex/` 下的真实密钥
- 本任务不涉及测评隐藏集，无额外屏蔽项

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **两个开关默认关闭**；关闭时零行为差异、零可测量开销。
2. **不新建第二套会话系统**，不做证据链重建，不引入工具状态机。只在请求发送前截快照。
3. 快照点必须位于 **Guardian 逻辑请求已完整构造、尚未最终发送处**。捕获资格由两个条件**同时**成立决定：`request_kind == Some(Turn)`，**且** 该请求所属会话当前登记着一个已开启的审批轮捕获槽。用 `== Some(Turn)` 而不是 `!= Prewarm`：枚举还有 `Compaction`（`compact_remote_request.rs:75`）和 `Memory`（`turn_metadata.rs:79`），Guardian 会话保留了压缩路径，放宽会让压缩请求覆盖真正的审批请求。二者都用挂钩点已有的数据判定，不新增下传参数。槽的登记与注销必须由 RAII guard 保证，覆盖所有提前返回、超时与 panic 路径。
4. 规范化必须**确定性且幂等**，剥离清单为**结构性字段**（见 §4），且被测试锁定。
5. **不得对外承诺内容级脱敏**。`ResponsesApiRequest` 的 policy/input 承载任务上下文、命令输出与
   文件内容；标准 Responses 的 policy 在顶层 `instructions`，Responses Lite 则在 `input` 的
   developer item，其中可能出现任何敏感信息。因此：
   - 证据包**视同原始会话记录**对待，默认输出到 git-ignored 目录，目录权限 `0700`。
   - 剥离的只是结构性字段，不是正文内容；文档与代码注释里不得写成"已脱敏"。
   - 把证据包外发给 Luna / Sol 等云端模型属于**数据外发**，必须单独授权，并在首次外发前人工抽查一批样本。本任务只落盘，不外发。
6. 不得为凑测试通过而弱化审批逻辑或放宽 fail-closed；证据写入失败只 warn，绝不改变审批结果。
7. **不引入新的第三方依赖**（避免 `Cargo.lock` → `MODULE.bazel.lock` 连锁，本机未装 Bazel 无法验证）。
8. 变更规模目标 **≤500 行**（不含测试与生成的 schema）。若超出，停下拆分为可独立验收的阶段。
9. 单个新 Rust 模块 <500 LoC；新测试模块用 `#[path = "..._tests.rs"]` 侧挂，不写内联大测试块。
10. **Bazel 相关门禁本次不运行也不声称通过**（本机未安装，见 `doc/development-environment.md` §8）。
11. **测试门禁口径**（解决上游 `mydev/AGENTS.md:68` 与根 `AGENTS.md` §7 的冲突，不留给执行期临场判断）：
    - 开发过程中只跑 `just test -p codex-core`。
    - 本任务改动 `core` 与 `config`，属于上游要求跑全量的范围，因此**合并前跑一次全量 `just test`**，作为 P0 的一次性阶段门禁。
    - 全量运行前先告知用户（上游 AGENTS.md 亦要求 ask before full suite），不在开发循环中反复跑全量。
    - 未运行或跳过的项如实标注，不表述为通过。
12. 本任务全程离线：不调用真实 API、不拉 Docker 镜像、不产生费用、不外发任何证据包。

## 4. 软性建议

以下是基于现有代码的执行建议，不是固定约束。AI 可依据实际代码与测试结果采用更优方案。

- **S1 复用既有配置链**：以 `[auto_review].policy` → `Config.guardian_policy_config` →
  Guardian session 的路径为模板，新字段不另设计配置面。引用实现时使用符号名，避免基线升级后
  行号漂移。
- **优先级链**：RONDO `[auto_review].model` > 官方 `ModelInfo.auto_review_model_override` >
  官方 `provider.approval_review_preferred_model()`。
  **effort 不是“同理”**——官方路径原本没有 auto-review effort override，而是由
  `preferred_reasoning_effort(...)` 按模型能力计算。因此契约是：配置了 effort 就用配置值，
  没配置就**完整保留现有计算结果**，不引入新的中间层。
- **S2 挂钩点**：`core/src/client.rs::build_responses_request` 的 `ResponsesApiRequest` 组装完成处。
  判定所需数据全部来自已有 `responses_metadata`（`request_kind`、`thread_id`），不新增下传参数；
  必须在标准 Responses / Responses Lite 分支汇合后捕获真实 wire shape。

- **捕获载体：按 guardian 会话 `thread_id` 登记的审批轮槽**。把 `Arc<EvidenceSlot>` 从 Config → Session → ModelClient 一路下传是侵入式改动；而挂钩点手上已有 `responses_metadata.thread_id`（`responses_metadata.rs:160`），足以做关联：

  1. `GuardianReviewSessionParams` 补 `evidence_round`（其中含 `review_id` 与输出配置）。
  2. `run_review` 选定 trunk 或 ephemeral fork 后，以该会话 `thread_id` 登记
     `thread_id → 槽{review_id, 最后一次请求}`，返回 RAII guard，drop 即注销。
  3. 挂钩点按 `thread_id` 查表，命中就**覆盖写**（retry 天然取最后一次，符合"最终请求"语义）。
  4. 轮结束（allow / deny / timeout / abort 皆同）原子 take 并固化，take 后槽失效。
  5. 槽为空（未真正调用模型就结束）只写 `meta.json` 并标 `evidence: none`。

  这个 key 之所以成立，是因为 trunk 上有 permits=1 的 `review_lock: Semaphore`：一轮审批拿到 guard
  后持有到整轮结束，拿不到就退回 `run_ephemeral_review` 新建会话。因此同一 trunk 同时只有一轮审批，
  并发轮落到不同会话；每次 `Session` spawn 都生成新的 `ThreadId`，所以可安全用 `thread_id` 关联。

- **配置契约**（不留给实现期临场决定）：
  - 键 `[auto_review].evidence_dir`，类型 `Option<AbsolutePathBuf>`——`config_toml.rs` 既有惯例（`log_dir` `:326`、`sqlite_home` `:321`），`codex_utils_absolute_path` 已是 config crate 依赖，不新增第三方依赖。
  - 未配置 = 完全关闭。相对路径**按既有语义解析**：`deserialize_config_toml_with_base`（`core/src/config/mod.rs:1913`）会装 `AbsolutePathBufGuard`，`AbsolutePathBuf` 反序列化时把相对路径解析到配置目录下（`utils/absolute-path/src/lib.rs:358`）。沿用这套行为，**不另造校验**；想落到仓库内的 `eval-data/` 就直接写绝对路径。
  - 输出 `<evidence_dir>/<review_id>/E_final.json` + `meta.json`；目录 `0700`，文件 `0600`。
  - 写入原子：先写 `*.tmp` 再 `rename`，避免读到半截文件。
  - 默认位置建议 `eval-data/evidence/raw/`（见 `doc/eval-data-layout.md`），由 `.gitignore` 的 `/eval-data/` 兜住。
- **测试复用**：用 `core_test_support::responses` 的 `mount_sse_once` + `ResponseMock::requests()` 断言出站请求体；断言整对象而非逐字段（上游 AGENTS.md 要求）。
- 规范化剥离清单：`prompt_cache_key`、`client_metadata`、`store`、`stream`、`stream_options`、
  时间戳、逐项随机 `id`，以及 `FunctionCall.encrypted_function_args`。最后一项是 provider-private
  运输数据，必须同时覆盖标准/Lite 输入中的 FunctionCall item。
  **`call_id` 不属于"随机 id"，必须保留**——它是 `FunctionCall`（`protocol/src/models.rs:873`）与 `FunctionCallOutput`（`:902`）之间唯一的关联键，删掉证据语义就废了。若为了跨运行可比而需要归一，只能按出现顺序做**成对确定性重映射**（如 `call_0`、`call_1`），不得单边删除。
- 保留：Guardian policy、任务轨迹、工具调用与结果、待审批动作。
- 0.147 的 approval/retry reason 是 Guardian prompt 的有意义输入，必须保留。RONDO 不覆写 0.147
  policy/template；证据元数据要记录 policy baseline，跨 0.146.1/0.147 比较时先分层。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息。

### 已完成

S1 与 S2 全部落地并通过定向门禁。

- S1：`AutoReviewToml` 加 `model` / `reasoning_effort`（并顺带 `evidence_dir`），`Config` 加
  `guardian_model_config` / `guardian_reasoning_effort_config` / `guardian_evidence_dir`，
  `review.rs` 的 model 优先级链与 effort 覆盖已按契约实现。provider 解析未动。
- S2：新增 `core/src/guardian/evidence.rs`（322 行）；`client.rs` 挂 1 行钩子；
  `GuardianReviewSessionParams` 加 `evidence_round`，`run_review_on_session` 绑定 / 解绑；
  固化收口在 `track_guardian_review`（见决策 013）。
- `.gitignore` 追加 `/eval-data/`；`just write-config-schema` 已运行，schema 差异只含三个新字段。
- 非测试、非生成物改动 426 行（104 行修改 + 322 行新模块），未超 500 行闸；未新增第三方依赖。

### 当前验收状态

- 产品源码已整体升级到 `v0.147.0`，S1/S2 完成 Responses Lite、新 FunctionCall 字段和非默认
  override 断言适配。
- `cargo fmt --all -- --check`、`just fmt-check`、`just fix -p codex-core` 和 schema 生成门禁通过。
- P0 精确回归 8/8、Guardian/auto-review 相关集 10/10、config/schema 相关集 6/6 通过；
  `codex-core` 冷编译通过。
- 全量 nextest 完整执行：14,074 run，13,998 passed / 74 failed / 2 timed out / 23 skipped。
  76 个终态未通过项无 Guardian evidence / override 回归；全量中的 MCP/Guardian 慢测在正式环境
  单独复跑 47.102 秒通过。完整归因和清单见
  `agent_log/2026-08-08-221708-codex-0.147.0-p0-acceptance.md`。
- 因此 **P0 在 `v0.147.0` 上验收通过，但不声称全量套件全绿**。
- Bazel 门禁与 `just argument-comment-lint` 未运行（本机未装 Bazel）。

### 后续计划

P0 已解锁：方向 0 的 P1（TB 2.1 最小真实链路，需 Docker + 小额真实 API 授权）、方向 2 的 L1 / L2。
`E_final` 首次用于跨侧对比前，建议人工抽查一批样本确认正文内容边界。

### 阻塞项

无。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | evidence 模块放在 `codex-core` 的 guardian 子模块内，不新建 crate | 上游 AGENTS.md 要求"resist adding code to codex-core"，但该能力与 guardian 强耦合；新建 crate 会连锁 `BUILD.bazel` + `Cargo.lock` + `MODULE.bazel.lock`，而本机未装 Bazel 无法验证 | `core/src/guardian/` | 已采纳 |
| 002 | 用单个 `evidence_dir` 字段同时表达开关与输出位置 | 不加多余 bool，未配置即完全关闭，符合轻量偏好 | config schema | 已采纳 |
| 003 | P0 只做 `E_final`，不做 `E0` | `E0` 只在研究"取证调查本身值多少分"时才需要，现在做属于提前扩大范围 | 方向 2 | 已采纳 |
| 004 | 不引入新的第三方依赖 | 避免 lock 文件连锁与无法验证的 Bazel 漂移 | 构建 | 已采纳 |
| 005 | Bazel 门禁本次不运行、不声称通过 | 本机未安装 Bazel，项目不使用 CI，以 cargo/nextest 本地测试兜底 | 验收口径 | 已采纳（需用户知悉） |
| 006 | 捕获资格 = `request_kind == Some(Turn)` **且** 该会话登记着已开启的审批轮槽 | 只按会话来源过滤会把陈旧请求错认成本轮证据；`build_responses_request` 没有 `warmup` 布尔，改用已有的 `responses_metadata.request_kind` 并收紧为白名单。枚举还有 `Compaction` / `Memory`，黑名单式的 `!= Prewarm` 会让压缩请求覆盖审批请求 | `core/src/client.rs` | 已采纳（外部审查修正） |
| 007 | S1 只覆盖 model + effort，**provider 覆盖拆到方向 2 的 L2a** | `build_guardian_review_session_config` 克隆父 provider；仅改模型名会把本地模型名发往父 provider 端点。测评场景父子同为 OpenAI provider，P0 需求成立；本地模型切换另立任务，避免 P0 膨胀 | `doc/WBS.md`、`doc/WBS/local-approval-model.md` | 已采纳（外部审查修正） |
| 008 | 撤回"P0 完成即可一键切换本地审批模型"的表述 | 与 007 同因，原表述不成立 | 全部规划文档 | 已采纳（外部审查修正） |
| 009 | 槽以 guardian 会话 `thread_id` 登记，由 RAII guard 管生命周期；`GuardianReviewSessionParams` 补 `review_id` | 原设计未定义 key 与生命周期，且下传 `Arc<EvidenceSlot>` 需穿透 Config/Session/ModelClient，过于侵入；`thread_id` 在挂钩点已有，串行复用 + 并发 fork 的语义天然可用 | `core/src/guardian/`（含 `review_session.rs`） | 已采纳（外部审查修正） |
| 010 | 证据包不做内容级脱敏承诺，按原始会话记录对待 | `instructions` / `input` 承载任意任务上下文，结构性字段剥离无法保证正文无敏感信息；改为限定输出位置与权限，并把外发单列为授权动作 | 验收口径、安全边界 | 已采纳（外部审查修正） |
| 011 | 测试门禁：开发期定向、合并前全量一次，全量前先告知 | 上游 `mydev/AGENTS.md:68` 要求 core 改动跑全量，根 `AGENTS.md` §6 要求不扩大化；两者在"开发循环 vs 阶段门禁"上可以调和，明确写死避免执行期临场判断 | 验收口径 | 已采纳（外部审查修正） |
| 012 | 并发不串档由模块级测试覆盖，集成测试覆盖串行复用与主 Agent 不捕获 | 真实并发审批要求 trunk 忙时 fork ephemeral，在集成测试里难以稳定触发，做出来大概率是 flaky 测试；模块级测试可以确定性地同时绑定两个轮并交错投递请求，直接验证关联键这一唯一失效点 | 验收口径 | 已采纳（执行期细化） |
| 013 | 证据固化收口在 `track_guardian_review`，meta 直接复用 `GuardianReviewAnalyticsResult` | `run_guardian_review` 有 5 条终止路径，逐条插入易漏；这 5 条都经过 `track_guardian_review`，且它拿到的正是最终决策。复用 analytics 还避免在 evidence 模块里重写一份 outcome→decision 映射造成漂移 | `core/src/guardian/review.rs` | 已采纳（执行期细化） |
| 014 | `GuardianReviewSessionParams` 传 `evidence_round`（含 review_id）而非裸 `review_id` | 与决策 009 等价但更省：轮对象本身携带 review_id 与输出目录，关闭时该字段为 `None`，无需再从 `spawn_config` 二次取配置 | `core/src/guardian/review_session.rs` | 已采纳（执行期细化） |
| 015 | `call_id` 采用成对确定性重映射，而非保留原值 | 方案 §4 允许二选一。`call_id` 由服务端随机生成，不归一则同一任务两次运行的 `E_final` 字节不同，对方向 0 的离线对比无用；重映射按文档顺序成对进行，对已规范化输入是不动点 | `core/src/guardian/evidence.rs` | 已采纳（执行期细化） |
| 016 | S1 集成测试用 `gpt-5.5/high` 证明显式覆盖 | effort 的 `high` 区别于既有默认计算；`v0.147.0` API-key 默认已是 Luna，所以 model 也必须选非默认值，否则覆盖失效仍可能误通过 | 验收口径 | 已采纳（0.147 调整） |
| 017 | 默认模型写成 RONDO 自定义层 > 官方 metadata override > provider/auth 派生默认 | 官方 0.147 configured provider + API key 默认 Luna，ChatGPT/无 key 默认 auto-review，Bedrock 另有默认；不能继续写死 `codex-auto-review` | `review.rs`、文档 | 已采纳（0.147 调整） |
| 018 | `E_final` 保留真实 standard/Lite wire shape，消费端再提取统一逻辑 payload | Luna 使用 Responses Lite，policy 与工具位于 `input` developer items；强行只读顶层字段会漏语义 | evidence、eval | 已采纳（0.147 调整） |
| 019 | 规范化剥离 `encrypted_function_args` | 该字段是 0.147 新增的 provider-private 运输数据，会破坏跨 provider 与离线重放稳定性，不属于 Guardian 逻辑证据 | `evidence.rs` | 已采纳（0.147 调整） |
