# P0 共享地基：Guardian 审批模型覆盖 + 审批证据包快照

> 本计划是任务的稳定约束文档。
> 除"当前状态"和"关键决策记录"外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

对应 WBS：`doc/WBS.md` §5（P0 / S1 / S2）。完成后解锁方向 0 的 P1 与方向 2 的 L1~L2。

适用基线：Codex CLI `v0.147.0`，只读上游 `rust-v0.147.0` /
`be6e8eac029b183056b7e4402879f15d2c85f61b`。官方 `Cargo.lock` 中 135 个 workspace package
仍写作 `0.0.0`；RONDO 产品树为 `--locked` 构建做的 `0.147.0` 规范化不属于上游事实。

## 1. 目标

### 最终目标

交付方向 0（测评基准）与方向 2（本地审批模型）共用的两块地基，使两条线可以真正并行开工：

- **S1**：Guardian 审批模型与 reasoning effort 可由 `config.toml` 显式覆盖，并在真实发出的请求中生效。
- **S2**：每一轮 Guardian 审批可产出一份**规范化幂等、可离线复用、与该审批轮明确关联**的证据包 `E_final`。
  这里的确定性边界是“同一份已构造请求重复规范化得到相同字节”；Guardian 原始自由文本含父会话 id
  等运行态语义，P0 不承诺两个新会话的整包字节相同。跨运行分桶使用规范化待审批动作指纹，而不是
  整份 `E_final` 哈希（见 `doc/eval-data-layout.md`）。

**S1 的能力边界（重要）**：本任务**只覆盖模型名与 effort，不覆盖 provider**。
`build_guardian_review_session_config`（`core/src/guardian/review_session.rs`）克隆父会话配置；provider
字段中只改写 `request_max_retries` / `stream_max_retries`，provider id 与 base_url 原样继承。
`v0.147.0` 的 provider/auth 默认模型分流没有改变这一点。因此 P0 可以把 Guardian 钉在同一
OpenAI provider 的 `gpt-5.6-luna + low`，但**不足以切到本地模型**；独立 provider 覆盖属于
方向 2 的 **L2a**，是 L7 的前置。

### 完成/验收标准

**S1**

- 配置 `[auto_review] model = "gpt-5.5"` / `reasoning_effort = "high"` 后，Guardian 实际发出的
  请求体中 `model` 与 `reasoning.effort` 与配置一致（用 `ResponseMock` 断言出站请求体）。模型特意
  选为不同于 API-key 默认 Luna 的值，避免 override 失效时测试仍误通过。
- 未配置时，RONDO 自定义层回退到官方链：`ModelInfo.auto_review_model_override` →
  `turn.provider.approval_review_preferred_model()`。后者在 configured provider + API key 下默认
  `gpt-5.6-luna`，ChatGPT/无 API key 时为 `codex-auto-review`，Bedrock 使用自身模型 id；回归至少
  覆盖 API-key 与非 API-key 两类。若 provider 候选不在 catalog 且无 metadata override，官方逻辑
  回退主模型；不得把 provider 候选写成无条件最终模型。
- 运行 `just write-config-schema`，并确认 `core/config.schema.json` 的差异只包含三个新增字段与
  `[auto_review]` 表说明更新。
- 不改动 provider 解析路径（本任务显式不做，留给 L2a）。

**S2**

- 配置证据输出目录后，一轮 Guardian 审批若到达 transport send point，则产出 1 份
  `E_final.json` + 1 份 `meta.json`（`review_id`、source baseline tag/peeled commit、决策、耗时、模型、effort、token、
  结束原因）。Unix/WSL
  目录/文件权限为 `0700`/`0600`；Windows 继承配置目录 ACL。0.147 的 permission hook
  在 Guardian/user 之前运行；hook 直接 resolve 时不创建 Guardian 轮，也不产证据包。
- **关联正确性**：产出的 `E_final` 必须归属到发起它的 `review_id`；并发审批（trunk 忙时会 fork
  ephemeral 会话）互不串档。并发关联由确定性的模块级测试覆盖；集成测试覆盖串行复用与主 Agent 不捕获。
- **只捕获真正的审批请求**：判定用
  `matches!(responses_metadata.request_kind, Some(CodexResponsesRequestKind::Turn))`，把预热、压缩、memory
  请求一并排除。`build_responses_request` 没有 `warmup` 布尔，但已有 `responses_metadata`，够用。
  需有**开启 websocket** 的测试覆盖"预热不产生证据包"。实现时确认 Guardian 审批请求确实匹配
  `Some(Turn)`；若观察到 `None`，须查明原因，**不得**放宽为“只排除 Prewarm”。
  注：测评配置关闭 websocket 时 `schedule_startup_prewarm` 只跑 `prewarm_auth()` 就返回（`session_startup_prewarm.rs:185`），预热在测评主路径上本就不触发；但压缩请求会。
- **不捕获主 Agent 请求**：需有测试直接覆盖。
- 规范化**幂等**：同一请求规范化两次逐字节一致；被剥离的字段清单由测试锁定。
- 标准 Responses 与 Responses Lite 的规范化都必须被测试。前者使用顶层 `instructions` / `tools`；
  Lite 把 policy 与 `additional_tools` 编码进 `input` 的 developer items，顶层字段缺席。实际证据集成
  覆盖默认 Lite 路径；standard 由出站 wire 集成测试与 evidence normalizer 单测分层证明，不声称
  已有一次 standard Guardian `E_final` 端到端样本。
- `ResponseItem::FunctionCall.encrypted_function_args` 是 `v0.147.0` 新增的 provider-private 运输字段，
  必须从规范化证据中剥离；不得把它当作 Guardian 语义输入或跨 provider 的稳定字段。
- 规范化后**工具调用与其结果仍能正确配对**（`call_id` 保留或成对重映射），由单测断言，不新增设施。
- 未配置时不产生任何文件，且不引入可测量开销（快照路径在开关判定前不做任何分配）。
- 已建立 Guardian 轮但未到 transport send point 即结束（预取消、prompt 构造失败、WebSocket
  建连失败）时，**不得**把上一轮或预热的陈旧请求固化为本轮 `E_final`；此类轮次只写
  `meta.json` 并标记 `evidence: none`。一旦到达 send point，即使随后的发送/流读取失败或超时，
  仍可保留该次已尝试发送的 `E_final`，不把它误写成 `none`。
  hook 提前 resolve 或在 Guardian 轮建立前失败则不产 meta；两类边界均由测试覆盖。
- 证据写入失败**不得影响审批决策**：只记 warn，审批照常 fail-closed。

**通用**

- P0 的 `codex-core` 精确过滤集全部通过；新增集成测试放进 `core/tests/suite/` 的既有相关文件，
  不新建散落测试文件。package-only 无过滤整包运行只作诊断，完整兼容门禁用 workspace `just test`。
- 两个开关都不开启时，guardian 既有测试全绿，行为与上游一致（不退化项）。
- 运行 `just fmt` 与 `just fix -p codex-core`，并确认结果干净。
- 合并前跑一次全量 `just test`（见 §3 约束 11 的口径），结果如实记录。

## 2. 范围

### 允许修改

- `mydev/codex-rs/config/src/config_toml.rs` —— `AutoReviewToml` 增加字段
- `mydev/codex-rs/core/src/config/mod.rs` —— `Config` 增加字段与解析（照抄 `guardian_policy_config` 路径）
- `mydev/codex-rs/core/src/guardian/review.rs` —— `model_override` 优先级链、审批轮起止处的槽注册
- `mydev/codex-rs/core/src/guardian/review_session.rs` —— `GuardianReviewSessionParams` 加
  `evidence_round`，选定会话后注册捕获槽
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
- 0.147 集中审批的 precedence（permission hook → Guardian/user）与 approval/retry reason 注入
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
3. 快照点必须位于 **Guardian 完整逻辑 Responses request 已构造、transport 即将发送处**。WebSocket
   仍保存可离线复用的完整逻辑请求，不保存依赖 `previous_response_id` 的增量 transport delta；但必须
   等连接建立成功后再提交候选，连接前失败不得留下 `E_final`。捕获资格由两个条件
   **同时**成立决定：`matches!(request_kind, Some(Turn))`，且该请求所属会话当前登记着已开启的审批轮槽。
   用 `matches!(..., Some(Turn))` 而不是 `!matches!(..., Some(Prewarm))`：`CodexResponsesRequestKind` 还有 `Compaction` / `Memory`，
   Guardian 会话保留了压缩路径，放宽会让压缩请求覆盖真正的审批请求。槽的登记与注销必须由
   RAII guard 保证，覆盖所有提前返回、超时与 panic 路径。
4. 规范化必须**确定性且幂等**，剥离清单为**结构性字段**（见 §4），且被测试锁定。
5. **不得对外承诺内容级脱敏**。`ResponsesApiRequest` 的 policy/input 承载任务上下文、命令输出与
   文件内容；标准 Responses 的 policy 在顶层 `instructions`，Responses Lite 则在 `input` 的
   developer item，其中可能出现任何敏感信息。因此：
   - 证据包**视同原始会话记录**对待，默认输出到 git-ignored 目录；Unix/WSL 目录权限 `0700`，
     Windows 继承配置目录 ACL。
   - 剥离的只是结构性字段，不是正文内容；文档与代码注释里不得写成"已脱敏"。
   - 把证据包外发给 Luna / Sol 等云端模型属于**数据外发**，必须单独授权，并在首次外发前人工抽查一批样本。本任务只落盘，不外发。
6. 不得为凑测试通过而弱化审批逻辑或放宽 fail-closed；证据写入失败只 warn，绝不改变审批结果。
7. **不引入新的第三方依赖**（避免 `Cargo.lock` → `MODULE.bazel.lock` 连锁，本机未装 Bazel 无法验证）。
8. 变更规模目标 **≤500 行**（不含测试与生成的 schema）。若超出，停下拆分为可独立验收的阶段。
9. 单个新 Rust 模块 <500 LoC；新测试模块用 `#[path = "..._tests.rs"]` 侧挂，不写内联大测试块。
10. **Bazel 相关门禁本次不运行也不声称通过**（本机未安装，见 `doc/development-environment.md` §8）。
11. **测试门禁口径**（解决上游 `mydev/AGENTS.md:68` 与根 `AGENTS.md` §6 的冲突，不留给执行期临场判断）：
    - 开发过程中只跑 `just test -p codex-core <P0 filter>` 等精确过滤集；不把缺少 workspace helper
      binaries 的 package-only 无过滤运行当作 hermetic 全绿门禁。
    - 本任务改动 `core` 与 `config`，属于上游要求跑全量的范围，因此**合并前跑一次全量 `just test`**，作为 P0 的一次性阶段门禁。
    - 全量运行前先告知用户（上游 AGENTS.md 亦要求 ask before full suite），不在开发循环中反复跑全量。
    - 未运行或跳过的项如实标注，不表述为通过。
12. 本任务全程离线：不调用真实 API、不拉 Docker 镜像、不产生费用、不外发任何证据包。

## 4. 软性建议

以下是基于现有代码的执行建议，不是固定约束。AI 可依据实际代码与测试结果采用更优方案。

- **S1 复用既有配置链**：以 `[auto_review].policy` → `Config.guardian_policy_config` →
  Guardian session 的路径为模板，新字段不另设计配置面。引用实现时使用符号名，避免把 RONDO
  自定义行号误写成纯上游行号。
- **优先级链分层描述**：RONDO `[auto_review].model` > 官方
  `ModelInfo.auto_review_model_override` > 官方 `provider.approval_review_preferred_model()`。
  effort 配置了就覆盖；官方原本没有 auto-review effort override，未配置时须完整保留
  `preferred_reasoning_effort(...)` 的计算结果。
- **S2 挂钩点**：HTTP 与 WebSocket 各自的 transport send 前。判定所需数据全部来自已有
  `responses_metadata`（`request_kind`、`thread_id`），不新增下传参数；两条路径都保存标准
  Responses / Responses Lite 分支汇合后的完整逻辑请求，而不是 WebSocket 增量 delta。

- **捕获载体：按 guardian 会话 `thread_id` 登记的审批轮槽**。把 `Arc<EvidenceSlot>` 从 Config →
  Session → ModelClient 一路下传是侵入式改动；挂钩点已有 `responses_metadata.thread_id`，足以关联：

  1. `GuardianReviewSessionParams` 补 `evidence_round`（其中含 `review_id` 与输出配置）。
  2. `run_review` 选定 trunk 或 ephemeral fork 后，以该会话 `thread_id` 登记
     `thread_id → 槽{review_id, 最后一次请求}`，返回 RAII guard，drop 即注销。
  3. 挂钩点按 `thread_id` 查表，命中就**覆盖写**（retry 天然取最后一次，符合"最终请求"语义）。
  4. 轮结束（allow / deny / timeout / abort 皆同）原子 take 并固化，take 后槽失效。
  5. 槽为空（未到 transport send point 就结束）只写 `meta.json` 并标 `evidence: none`。

  这个 key 之所以成立，是因为 trunk 上有 permits=1 的 `review_lock: Semaphore`：一轮审批拿到 guard
  后持有到整轮结束，拿不到就退回 `run_ephemeral_review` 新建会话。因此同一 trunk 同时只有一轮审批，
  并发轮落到不同会话；每次 `Session` spawn 都生成新的 `ThreadId`，所以可安全用 `thread_id` 关联。

- **配置契约**（不留给实现期临场决定）：
  - 键 `[auto_review].evidence_dir`，类型 `Option<AbsolutePathBuf>`；复用 `log_dir` / `sqlite_home`
    与 `AbsolutePathBufGuard` 的既有惯例，不新增第三方依赖。
  - 未配置 = 完全关闭。相对路径继续由 `deserialize_config_toml_with_base` 按配置目录解析，
    **不另造校验**；想落到仓库内 `eval-data/` 就直接写绝对路径。
  - 输出 `<evidence_dir>/<review_id>/E_final.json` + `meta.json`；Unix/WSL 目录 `0700`、文件 `0600`，
    Windows 继承配置目录 ACL。
  - 写入原子：先写 `*.tmp` 再 `rename`，避免读到半截文件。
  - 默认位置建议 `eval-data/evidence/raw/`（见 `doc/eval-data-layout.md`），由 `.gitignore` 的 `/eval-data/` 兜住。
- **测试复用**：用 `core_test_support::responses` 的 `mount_sse_once` + `ResponseMock::requests()` 断言出站请求体；断言整对象而非逐字段（上游 AGENTS.md 要求）。
- 规范化剥离清单：`prompt_cache_key`、`client_metadata`、`store`、`stream`、`stream_options`、
  时间戳、逐项随机 `id`，以及 `FunctionCall.encrypted_function_args`。最后一项是 provider-private
  运输数据，必须同时覆盖标准/Lite 输入中的 FunctionCall item。
  **`call_id` 不属于"随机 id"，必须保留**——它是 `ResponseItem::FunctionCall` 与
  `FunctionCallOutput` 之间唯一的关联键。为减少服务端随机 id 带来的结构性漂移，只对
  `input[*].call_id` 按出现顺序做**成对确定性重映射**（如 `call_0`、`call_1`），不得递归修改工具
  schema/参数中恰好同名的业务字段，也不得单边删除。`input[*]` passthrough `turn_id` 同样保留等价关系
  后重映射；自由文本不做脆弱的 UUID 正则替换。
- 保留：Guardian policy、任务轨迹、工具调用与结果、待审批动作。
- 0.147 的 approval/retry reason 是 Guardian prompt 的有意义输入（retry 优先、否则 approval，
  上游限长 512 tokens），必须保留。RONDO 不覆写 0.147 policy/template；证据元数据要记录 Guardian
  source baseline tag/peeled commit，跨 0.146.1/0.147 比较时先分层。源码身份只标识 Guardian 源码基线，不代表
  自定义 requirements/config/catalog 后的有效 policy 身份；后者由 P1 从 `E_final` 提取并哈希。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息。

### 已完成

S1 与 S2 的主体实现已在 `v0.146.1` 基线上落地，随后随产品源码导入 `v0.147.0`。

- S1：`AutoReviewToml` 加 `model` / `reasoning_effort`（并顺带 `evidence_dir`），`Config` 加
  `guardian_model_config` / `guardian_reasoning_effort_config` / `guardian_evidence_dir`，
  `review.rs` 的 model 优先级链与 effort 覆盖已按契约实现。provider 解析未动。
- S2：新增 `core/src/guardian/evidence.rs`；HTTP/WS transport send 前各设一个捕获点；
  `GuardianReviewSessionParams` 加 `evidence_round`，`run_review_on_session` 绑定 / 解绑；
  固化收口在 `track_guardian_review`（见决策 013）。meta 中记录 `guardian_source_baseline` 与
  `guardian_source_commit`；有效
  policy 指纹待 P1 从 `E_final` 提取。
- `.gitignore` 追加 `/eval-data/`；`just write-config-schema` 已运行，schema 差异只含三个新字段与
  `[auto_review]` 表说明更新。
- 非测试、非生成物改动约 444 行，未超 500 行闸；未新增第三方依赖。

`v0.147.0` 首轮只读审计曾把 request builder 汇合点误判为充分；2026-08-09 复验确认捕获还必须贴近
transport send，避免 WebSocket 建连前的候选被当成已发证据。provider 继承边界未变，首轮还
发现两项必须随升级适配的细节：S1 的 API-key 默认模型已变为 Luna，原先用 Luna 证明 model
override 的测试失去区分度；S2 需要剥离新增的 `encrypted_function_args`，并覆盖 Responses Lite
逻辑形态。升级工作树完成了兼容适配，本轮继续补足捕获时点与规范化边界。

### 当前验收状态

- 产品源码已整体升级到 `v0.147.0`，S1/S2 完成 Responses Lite、新 FunctionCall 字段和非默认
  override 断言适配。
- `cargo fmt --all -- --check`、`just fmt-check`、`just fix -p codex-core` 和 schema 生成门禁通过。
- P0 精确回归 8/8、Guardian/auto-review 相关集 10/10、config/schema 相关集 6/6 通过；
  `codex-core` 冷编译通过。
- 004 指出的产品边界已关闭：permission hook 提前 resolve 不产证据；关闭 evidence 时一次原子读取
  后返回，不进入全局捕获表；证据写失败不影响审批。新增精确测试 3/3 通过。
- 最新完整 workspace：14,077 run，13,996 passed / 81 failed / 0 timed out / 23 skipped，27 项首轮
  失败后重试通过。81 项中没有 Guardian evidence / override 回归；完整归因和清单见
  `agent_log/2026-08-08-233753-p0-strict-acceptance.md`。
- `just test -p codex-core` 无过滤诊断产生 216 项失败，根因是 package-only 缺少 workspace helper
  binaries 与项目内 `TMPDIR` 注入根 `AGENTS.md`，不具备 hermetic 全绿含义；没有修改产品或快照凑绿。
- 2026-08-09 独立复验发现并修复三项缺口：捕获从共享 builder 后移到 HTTP/WS 实际 send 前，避免
  WebSocket 建连失败产生伪 `E_final`；`call_id` 从全树递归改为 input item 定点重映射，避免修改工具
  参数/元数据中的同名业务字段；passthrough `turn_id` 纳入结构规范化，并把跨新会话字节稳定承诺收窄
  到真实可保证范围。新增 builder-before-send、预取消轮 `evidence:none`、standard/Lite 形态和
  source baseline 回归；本轮门禁结果见 `agent_log/2026-08-09-020200-baseline-p0-test-audit.md`。
- 本轮 schema generator、`just fix -p codex-core`、`cargo fmt --all -- --check`、`just fmt-check` 均在
  看门狗下通过；
  精确选择 evidence/send-point/预取消/Guardian/override 的 16 项回归最终 16/16 通过。
- **P0 定向功能复验收口；不等价于完整 workspace 全绿，改动仍待审查/合并。**
- Bazel 门禁与 `just argument-comment-lint` 未运行（本机未装 Bazel）。

### 历史交接（不是当前规划）

> 以下记录只反映本计划结束时的交接判断；当前路线以 `doc/WBS.md` 为准。

本轮改动经审查/合并且用户确认对应草稿后，才按 `doc/WBS.md` 进入 P1/L1/L2；`E_final` 首次用于
跨侧对比前，仍需人工抽查 standard Responses 与 Responses Lite 样本的正文边界，并为有效 policy
生成结构化指纹。

### 阻塞项

无 P0 定向实现或测试阻塞。Bazel 门禁因本机未安装而未运行；本 worktree 尚待外部审查。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | evidence 模块放在 `codex-core` 的 guardian 子模块内，不新建 crate | 上游 AGENTS.md 要求"resist adding code to codex-core"，但该能力与 guardian 强耦合；新建 crate 会连锁 `BUILD.bazel` + `Cargo.lock` + `MODULE.bazel.lock`，而本机未装 Bazel 无法验证 | `core/src/guardian/` | 已采纳 |
| 002 | 用单个 `evidence_dir` 字段同时表达开关与输出位置 | 不加多余 bool，未配置即完全关闭，符合轻量偏好 | config schema | 已采纳 |
| 003 | P0 只做 `E_final`，不做 `E0` | `E0` 只在研究"取证调查本身值多少分"时才需要，现在做属于提前扩大范围 | 方向 2 | 已采纳 |
| 004 | 不引入新的第三方依赖 | 避免 lock 文件连锁与无法验证的 Bazel 漂移 | 构建 | 已采纳 |
| 005 | Bazel 门禁本次不运行、不声称通过 | 本机未安装 Bazel，项目不使用 CI，以 cargo/nextest 本地测试兜底 | 验收口径 | 已采纳（需用户知悉） |
| 006 | 捕获资格 = `matches!(request_kind, Some(Turn))` **且**该会话登记着已开启的审批轮槽 | 只按会话来源过滤会把陈旧请求错认成本轮证据；`build_responses_request` 没有 `warmup` 布尔，改用已有的 `responses_metadata.request_kind` 并收紧为白名单。枚举还有 `Compaction` / `Memory`，只排除 Prewarm 会让压缩请求覆盖审批请求 | `core/src/client.rs` | 已采纳（外部审查修正） |
| 007 | S1 只覆盖 model + effort，**provider 覆盖拆到方向 2 的 L2a** | `build_guardian_review_session_config` 克隆父 provider；仅改模型名会把本地模型名发往父 provider 端点。测评场景父子同为 OpenAI provider，P0 需求成立；本地模型切换另立任务，避免 P0 膨胀 | `doc/WBS.md`、`doc/WBS/local-approval-model.md` | 已采纳（外部审查修正） |
| 008 | 撤回"P0 完成即可一键切换本地审批模型"的表述 | 与 007 同因，原表述不成立 | 全部规划文档 | 已采纳（外部审查修正） |
| 009 | 槽以 guardian 会话 `thread_id` 登记，由 RAII guard 管生命周期；`GuardianReviewSessionParams` 补 `review_id` | 原设计未定义 key 与生命周期，且下传 `Arc<EvidenceSlot>` 需穿透 Config/Session/ModelClient，过于侵入；`thread_id` 在挂钩点已有，串行复用 + 并发 fork 的语义天然可用 | `core/src/guardian/`（含 `review_session.rs`） | 已采纳（外部审查修正） |
| 010 | 证据包不做内容级脱敏承诺，按原始会话记录对待 | `instructions` / `input` 承载任意任务上下文，结构性字段剥离无法保证正文无敏感信息；改为限定输出位置与权限，并把外发单列为授权动作 | 验收口径、安全边界 | 已采纳（外部审查修正） |
| 011 | 测试门禁：开发期定向、合并前全量一次，全量前先告知 | 上游 `mydev/AGENTS.md:68` 要求 core 改动跑全量，根 `AGENTS.md` §6 要求不扩大化；两者在"开发循环 vs 阶段门禁"上可以调和，明确写死避免执行期临场判断 | 验收口径 | 已采纳（外部审查修正） |
| 012 | 并发不串档由模块级测试覆盖，集成测试覆盖串行复用与主 Agent 不捕获 | 真实并发审批要求 trunk 忙时 fork ephemeral，在集成测试里难以稳定触发，做出来大概率是 flaky 测试；模块级测试可以确定性地同时绑定两个轮并交错投递请求，直接验证关联键这一唯一失效点 | 验收口径 | 已采纳（执行期细化） |
| 013 | 证据固化收口在 `track_guardian_review`，meta 直接复用 `GuardianReviewAnalyticsResult` | `run_guardian_review` 有 5 条终止路径，逐条插入易漏；这 5 条都经过 `track_guardian_review`，且它拿到的正是最终决策。复用 analytics 还避免在 evidence 模块里重写一份 outcome→decision 映射造成漂移 | `core/src/guardian/review.rs` | 已采纳（执行期细化） |
| 014 | `GuardianReviewSessionParams` 传 `evidence_round`（含 review_id）而非裸 `review_id` | 与决策 009 等价但更省：轮对象本身携带 review_id 与输出目录，关闭时该字段为 `None`，无需再从 `spawn_config` 二次取配置 | `core/src/guardian/review_session.rs` | 已采纳（执行期细化） |
| 015 | 只对 `input[*].call_id` 采用成对确定性重映射 | `call_id` 由服务端生成且必须保留调用/结果配对；全树递归会误改工具 schema、参数或 warehouse 元数据中的同名业务字段。它只减少结构 id 漂移，不承诺两个新会话的整包字节相同 | `core/src/guardian/evidence.rs` | 已修正（2026-08-09 复验） |
| 016 | S1 集成测试用 `gpt-5.5/high` 证明显式覆盖 | effort 的 `high` 区别于既有默认计算；`v0.147.0` API-key 默认已是 Luna，所以 model 也必须选非默认值，否则覆盖失效仍可能误通过 | 验收口径 | 已采纳（0.147 调整） |
| 017 | 默认模型写成 RONDO 自定义层 > 官方 metadata override > provider/auth 派生默认 | 官方 0.147 configured provider + API key 默认 Luna，ChatGPT/无 key 默认 auto-review，Bedrock 另有默认；不能继续写死 `codex-auto-review` | `review.rs`、文档 | 已采纳（0.147 调整） |
| 018 | `E_final` 保留完整 standard/Lite 逻辑形态，消费端再提取统一逻辑 payload | Luna 使用 Responses Lite，policy 与工具位于 `input` developer items；强行只读顶层字段会漏语义。WebSocket transport delta 不属于该证据形态 | evidence、eval | 已修正（2026-08-09 复验） |
| 019 | 规范化剥离 `encrypted_function_args` | 该字段是 0.147 新增的 provider-private 运输数据，会破坏跨 provider 与离线重放稳定性，不属于 Guardian 逻辑证据 | `evidence.rs` | 已采纳（0.147 调整） |
| 020 | 独立方案审查后的严格验收以测试事实为准，不用已有定向通过替代 hook 边界与关闭态开销 | 004 方案补足了原执行计划未明确验证的产品边界；两项均已补回归 | P0 验收 | 已采纳并完成 |
| 021 | 不把无过滤 `just test -p codex-core` 的 package-only 结果当作 hermetic 全绿门禁 | 实测缺少 workspace helper binaries，且受监控项目内 `TMPDIR` 会改变 fixture 的 AGENTS/project 语义；强行凑绿会弱化真实测试。改用 P0 精确过滤集 + 完整 workspace | P0 验收 | 已采纳并完成 |
| 022 | `E_final` 保存完整逻辑 request，捕获点贴近 transport send；WS delta 不落盘 | delta 依赖 `previous_response_id` 且可能缺 policy/历史，无法独立离线复用；共享 builder 又早于 WS 建连，会把未发出的候选误记为证据 | `client.rs`、evidence 语义 | 已修正（2026-08-09 复验） |
| 023 | 跨运行分桶使用规范化动作指纹，不使用整包字节哈希 | 原始 Guardian 自由文本包含父会话 id 等运行态语义；在 evidence 副本中全局正则替换 UUID 会误伤用户内容，P0 不做脆弱伪规范化 | P1 数据布局 | 已采纳（2026-08-09 复验） |
