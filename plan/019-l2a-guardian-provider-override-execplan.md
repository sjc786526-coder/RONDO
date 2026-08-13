# L2a Guardian 独立 provider 覆盖 ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

对应路线：`doc/WBS/local-approval-model.md` 的 L2a。适用源码基线为 Codex CLI
`v0.147.0`。本计划分阶段 A/B；阶段 A 已完成，用户随后明确授权并已执行阶段 B。

## 1. 目标

### 最终目标

在不改变主 Agent provider 的前提下，让 `[auto_review]` 可选用已存在于合并后
`model_providers` registry 的独立 provider。Guardian 使用该 provider 的 ID、base URL、鉴权、
headers、query、wire 能力与其他完整配置；随后继续把 Guardian 的 request/stream retry 固定为
现有 `1/1`。未配置 provider 覆盖时保持 P0 后的现有行为。

### 完成/验收标准

**阶段 A：实现待验收**

- `[auto_review].model_provider = "<id>"` 可反序列化，并在运行时 `Config` 中保留已解析的 provider ID。
- provider ID 必须在内置 provider 与用户 provider 合并后的 registry 中存在；未知 ID 在配置加载时
  fail-closed，不能延迟到审批时回退主 provider。
- `build_guardian_review_session_config` 在配置覆盖存在时同时替换 Guardian 的
  `model_provider_id` 与完整 `model_provider`，随后把两种 retry 固定为 `Some(1)`。
- 显式独立 provider 不继承主 Agent 的 provider auth；env/static bearer/command/无鉴权按所选 provider
  自身配置解析。该鉴权继承策略纳入 Guardian session 复用键，策略变化不得复用旧 session。
- 未配置时继续克隆主 Agent provider；主 `Config`、主 Agent 请求端点与现有 Guardian 只读沙箱、
  `approval_policy = never`、MCP/apps/plugins/memory 收缩均不改变。
- 测试代码覆盖：配置反序列化与有效解析、未知 provider、未配置兼容、完整 provider 覆盖和 retry
  收缩、provider auth 隔离与 session 复用失效、项目层 provider 选择被忽略，以及两个 loopback mock
  endpoint 的主/Guardian 请求分流。
- 阶段 A 只做静态审查、`git diff --check`、受影响文件/生成物检查；不得运行格式化、schema 生成、
  Rust 构建或测试，也不得启动 mock server。

**阶段 B：正式运行验收**

- 主智能体先确认 canary 调度器已停止且不会自动重启；Docker、本地模型与其他构建任务均未运行；
  campaign、全部 worktree 和共享结果目录安全；Windows C 盘、build lock、cgroup、资源计数器与
  项目内 `CARGO_TARGET_DIR` 满足仓库门禁。任一事实拿不到即 fail-closed。
- 先通过受锁入口运行
  `just fix -p codex-config -p codex-core -p codex-thread-manager-sample`，再运行格式化与
  `just write-config-schema`，审查生成的
  `mydev/codex-rs/core/config.schema.json` 仅包含本字段对应的预期变化。
- 通过受锁入口运行 config/Guardian 定向测试与双 loopback endpoint 集成验收；两个 mock server
  分别只收到主 Agent 与 Guardian 的预期请求，并检查 Guardian 自定义 header/query 证明完整
  provider 配置生效。
- 定向测试后运行最终 `just fmt-check` 与 `git diff --check`；所有实际执行结果、skip 和未运行项如实记录。
- 阶段 B 验收通过后才可把状态改为 L2a 已验收；合并、提交和推送仍需按用户当时授权执行。

## 2. 范围

### 允许修改

- `mydev/codex-rs/config/src/config_toml.rs`：`AutoReviewToml` 增加 provider ID。
- `mydev/codex-rs/config/src/loader/mod.rs`：保持项目层不能选择 provider/凭据目的地的既有边界。
- `mydev/codex-rs/core/src/config/mod.rs`：合并 registry 后解析并保存 Guardian provider ID。
- `mydev/codex-rs/core/src/guardian/{review.rs,review_session.rs,mod.rs}`：构造 Guardian config 时应用
  provider 覆盖、隔离 provider auth，并导出测试可见 helper。
- `mydev/codex-rs/core/src/{codex_delegate.rs,codex_delegate_tests.rs,thread_manager.rs,session/}`：仅做
  session auth 与 model-provider auth 的最小分流；普通 session 继续传入既有父 auth。
- `mydev/codex-rs/thread-manager-sample/src/main.rs`：同步新增的 `Config` 字段。
- 上述模块的既有相邻测试，以及 `mydev/codex-rs/core/tests/suite/auto_review.rs` 的双端点集成测试。
- 因新增 `Config` 字段必须同步的产品内显式构造点。
- `mydev/codex-rs/core/config.schema.json`：只允许阶段 B 由既有生成器更新，阶段 A 不修改。
- 本 ExecPlan 与一份精炼 `agent_log/` 阶段日志。

### 不允许修改

- `codex-source-code/`、`codex-doc/`、`reference-agent-harness/`。
- provider crate/workspace 依赖、`Cargo.toml`、`Cargo.lock`、`MODULE.bazel.lock`。
- Guardian 模型/effort 既有优先级、policy/prompt、证据格式与 capture 逻辑。
- 主 Agent provider 选择/解析语义；Guardian 以外的 session/provider 行为。
- L3/L4、训练、模型权重、local inference runtime、canary/campaign/eval 共享数据。

### 不允许读取/查看

- `.env.local` 内容、任何真实凭据/API Key、项目外个人文件。
- canary 隐藏输入、paid profile、共享 eval 结果正文。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. 本次阶段 A 不运行 Cargo/Bazel/just 构建、测试、Clippy、fmt、schema 生成、mock server、HTTP
   监听、Docker、本地模型、GPU 或真实 provider 连接。
2. 实现只存在于 `.claude/worktrees/0812-l2a-provider`；不修改、合并或推送 `main`，不接触其他
   worktree、canary/campaign lock、结果目录或共享环境。
3. 不新增 provider crate。只复用合并后的 `HashMap<String, ModelProviderInfo>` 与现有
   OpenAI-compatible provider/session 构造链。
4. `[auto_review].model_provider` 是 provider 选择轴；`model` 与 `reasoning_effort` 保持独立且优先级不变。
   provider 覆盖本身不暗改模型 slug，也不改模型 catalog。
5. 未配置 override 时不得重建或替换 provider；必须保持现有克隆父 provider 的行为。
6. 配置了 override 时必须复制 registry 中完整 `ModelProviderInfo`，不能只改 base URL；复制后仅允许
   Guardian 现有的 `request_max_retries = 1`、`stream_max_retries = 1` 收缩覆盖 provider 原值。
7. 显式独立 provider 不得收到主 Agent auth；所选 provider 的 env/static bearer/command/无鉴权语义
   保持既有 provider 机制。该选择必须参与 Guardian session 复用失效。
8. 未知 provider 在配置加载时返回 NotFound；不得 fallback、忽略或继续使用主 provider。
9. 项目局部 `.codex/config.toml` 中的 `auto_review.model_provider` 必须被忽略并产生与既有 denylist 一致的
   startup warning，避免仓库内容改变凭据/上下文目的地；同表其他已允许字段不受影响。
10. 双端点测试只使用测试进程内 loopback mock；阶段 B 运行前仍须完整通过用户指定的资源与 canary
   授权门，不能用瞬时 Docker 为空代替。
11. 不手改 schema。阶段 B 由 `just write-config-schema` 生成并审查。
12. 任何未运行项都标为 `not run`；阶段 A 最终状态只能是“实现待验收”。

## 4. 软性建议

- `Config` 只新增可选 Guardian provider ID，继续复用其已有的完整 `model_providers` registry，避免
  冗余保存第二份 provider 对象。
- provider 存在性校验与主 provider 使用同一合并后 registry 和错误风格；legacy provider 的现有
  帮助信息也应保持一致。
- 在 `build_guardian_review_session_config` 中先选择 provider，再统一设置 retry，避免自定义 provider
  的 retry 值覆盖 Guardian 固定值。
- 双端点集成测试放进既有 `auto_review.rs`，复用 `TestCodexBuilder`、`MockServer`、
  `mount_sse_sequence` 和 `ResponseMock`；静态 config/build helper 测试留在相邻既有模块。
- 阶段 B 在 `mydev/` 按当前状态章节冻结的顺序调用
  `just fix -p codex-config -p codex-core -p codex-thread-manager-sample`、`just fmt`、
  `just write-config-schema`、精确 core/sample 测试和最终 `just fmt-check`；所有 Cargo 型入口由
  `with-build-lock.sh` 间接执行。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已阅读根与 `mydev/` 规则、README、当前 WBS、L2a 路线、P0/相关 P1 历史计划与日志、冻结官方文档
  及关键源码/测试入口。
- 阶段 A 收口后、提交交接前再次复核，主 `main@fea01f8` 与 `origin/main` 对齐且干净；并行
  `0811-plan014-post-audit` worktree 有已有源码/计划/锁文件修改，其余非本任务 worktree 干净。所有
  并行状态均只读核对、未触碰。
- 已从 `main@98717160d7503fa29fe0299e2df715eccf29b589` 创建独立
  `.claude/worktrees/0812-l2a-provider` / `0812-l2a-provider`。
- 已定位运行链：`ConfigToml.auto_review` → `Config` → `guardian_review_session_config` →
  `build_guardian_review_session_config` → 新 Guardian `Session`；当前只收缩父 provider 的 retry。
- 已定位 schema 入口 `mydev/justfile:write-config-schema`、config fixture 与 Guardian/WireMock 设施。
- 已实现 `[auto_review].model_provider`、合并 registry 后的 fail-closed 解析、项目层过滤、完整 provider
  克隆与 retry `1/1` 收缩；同步了唯一的产品内显式 `Config` 字面量。
- 已把 session auth 与 model-provider auth 分离：未配置覆盖时保持父 auth；独立 provider 的 env key、静态
  bearer、command auth 由 provider 自己解析；真正无鉴权的本地 provider 不再收到父凭据；Bedrock 与
  `requires_openai_auth = true` 保留其现有受控继承路径。
- 已把 model-provider auth 继承策略纳入 Guardian session 复用键；即使显式覆盖与父配置恰好使用相同
  provider ID/info，鉴权继承策略变化也会使缓存 session 失效。
- 已准备 config/Guardian/双 WireMock endpoint 三层测试；双端点测试使用无鉴权 Guardian，断言主端点
  `2` 个请求仍带主 Bearer，Guardian 端点 `1` 个请求没有 Authorization/account header，并校验独立
  model/effort/header/query。
- 首轮独立静态审查发现并推动修复了无鉴权 provider 泄漏父 auth 的缺口；另一项审查指出了 sandbox
  early-return false-green 与空 ID 边界，后者已显式拒绝，前者已纳入阶段 B 证据要求。
- 第二轮独立静态审查确认 Session/delegate 调用点完整，并发现鉴权继承策略未进入 Guardian session
  复用键；已补行为键及同 provider ID/info 下的失效回归测试。测试/计划末轮复审指出的命令范围与
  sample crate 验证也已统一。
- 执行期间并行任务把 `main` 前进到 `21bcf18` 并占用 `plan/015-*`；其源码变更仅涉及方向 2 模型冻结文档，
  与本实现文件不重叠。为避免计划编号冲突，本计划改为 `plan/016-*`；未 rebase、merge 或触碰并行 worktree。
- 阶段 B 开始前合入 `main@73b0503` 后，main 已交付另一份 `plan/016-*`，且 Plan 018 已由 Plan 017
  明确预留给 CUDA runtime。为保留两份权威计划并消除编号歧义，本计划最终改为 `plan/019-*`。
- 阶段 B 资源门禁通过后，受锁完成首次三 crate `just fix`、`just fmt`、`just write-config-schema`；生成
  schema 只增加 `auto_review.model_provider` 及关联描述。11 项 config/Guardian/schema/安全收缩精确回归
  全部通过；sample crate 无测试目标，首次 nextest 因 zero tests 返回 4，随后以 `--no-tests pass` 明确完成
  编译验收。
- 首次 loopback 运行没有触发 skip，但宿主 HTTP 代理截获 `127.0.0.1` 请求并返回 502，WireMock 因而收到
  0 请求。测试补充终态错误与精确请求计数后，验收命令为当前进程显式设置
  `NO_PROXY/no_proxy=127.0.0.1,localhost`；最终两项出站测试真实执行并通过，主端点/Guardian 端点分别
  精确收到 `2/1` 个请求。
- 诊断修改后再次受锁执行 `just fix -p codex-core`、`just fmt`、`just fmt-check` 和最终双端点复验；
  看门狗均 `stop=none`、`cleanup=none`，`git diff --check` 通过。

### 当前工作

- L2a 阶段 B 已验收，正在收口计划、WBS、阶段日志与本地工作树提交。
- 最新 `main@73b0503` 已以 merge commit `1593ecf` 无冲突合入；独立重叠审查确认 main 与 L2a 源码路径
  零交集、双方语义均完整保留。

### 后续计划

- 本工作树保持待交付状态；未经后续明确授权，不合并到 `main`、不推送，也不启动 L3/L4/L7。
- 阶段 B 非 loopback 定向测试使用过下面的精确 filter（命令中的括号用于 nextest `-E` 表达式，不是
  shell 进程并发）：

  ```bash
  just test -p codex-core -E 'test(/load_config_resolves_auto_review_model_provider_without_changing_main_provider/) or test(/load_config_rejects_unknown_or_empty_auto_review_model_provider/) or test(/project_layer_ignores_unsupported_config_keys/) or test(/config_schema_matches_fixture/) or test(/guardian_review_session_config_keeps_bedrock_provider_for_bedrock_gpt_5_4/) or test(/guardian_review_session_config_uses_complete_provider_override_without_mutating_parent/) or test(/guardian_review_session_config_rejects_provider_missing_from_runtime_registry/) or test(/guardian_provider_auth_inherits_only_when_selected_provider_requires_it/) or test(/guardian_review_session_auth_inheritance_change_invalidates_cached_session/) or test(/guardian_review_session_config_preserves_parent_network_proxy/) or test(/guardian_review_session_config_disables_mcp_apps_plugins_and_memories/)'
  ```
- sample crate 使用 `just test -p codex-thread-manager-sample --no-tests pass`，明确把零测试目标作为编译
  验收，不把 nextest 的 zero-tests 退出码误报成编译失败。
- auto-review 出站验收使用：

  ```bash
  NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost just test -p codex-core --no-capture -E 'test(/auto_review_config_overrides_guardian_model_and_reasoning_effort/) or test(/auto_review_model_provider_routes_main_and_guardian_to_distinct_endpoints/)'
  ```

  运行前已确认 `CODEX_SANDBOX_NETWORK_DISABLED` 不存在且 `CODEX_SANDBOX != seatbelt`，输出没有两个
  skip 宏的文案。显式 loopback `NO_PROXY` 是为了排除宿主代理，不改变产品 provider 配置或真实网络。

### 阻塞项

- 无阻塞。

### 当前验收状态

- 阶段 A：功能与测试代码、静态检查与两轮独立复审已完成。
- 阶段 B：资源门禁、受锁 fix、格式化、schema 生成、精确定向测试、sample 编译与双端点验收均已通过；
  L2a 状态为“已验收、待合并”，不代表已合入或推送 `main`，也不代表 L7 本地模型端到端已完成。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | `[auto_review].model_provider` 保存 provider ID，完整配置从 `Config.model_providers` 取 | 与顶层 `model_provider` 的 registry 引用语义一致，且避免双份状态漂移 | 配置/运行时 | 已采纳 |
| 002 | provider 选择与 model/effort 选择保持正交 | L2a 只补运输/provider 能力，P0 的模型优先级已经验收 | 行为兼容 | 已采纳 |
| 003 | 未知 Guardian provider 在 Config load 时 fail-closed | 避免审批发生时才失败或静默泄回主端点 | 失败语义 | 已采纳 |
| 004 | 复制完整 provider 后最后写死 retry `1/1` | 同时满足 headers/auth/base URL 等完整覆盖与 Guardian 现有重试收缩 | Guardian session | 已采纳 |
| 005 | 项目层忽略 `auto_review.model_provider`，但保留同表其他既有字段 | provider 目的地属于 machine-local 安全边界，仓库内容不得重定向凭据/上下文 | 配置安全 | 已采纳 |
| 006 | 阶段 A 不提交实现 | 初次收口时未获提交要求；用户后续明确要求在本工作树提交后合入最新 main | 交接 | 已废弃 |
| 007 | L2a 不处理无鉴权 custom provider 的父 auth 隔离 | 首轮实现曾认为假 key 合同足够；独立审查证明该决定会让无鉴权 endpoint 收到主凭据，且 WBS 明确把无鉴权列为现实形态 | 范围/鉴权 | 已废弃 |
| 008 | Session spawn 分离 session auth 与 model-provider auth，仅在 Guardian 显式覆盖时按 provider 语义隔离 | 不改主 Agent provider，也不扩张通用 auth factory；无鉴权 endpoint 得到 `None`，provider 自带 env/bearer/command auth 仍自解析，Bedrock/`requires_openai_auth` 保持现有路径 | Guardian/session auth | 已采纳 |
| 009 | 双端点正式验收必须在非 sandbox 环境以 `--no-capture` 运行并确认无 skip 文案 | 两个既有 skip 宏会 early-return `Ok(())`，仅看 nextest passed 会产生 false-green | 阶段 B 证据 | 已采纳 |
| 010 | provider auth 继承策略是 Guardian session 复用键的一部分 | 显式覆盖和继承可能有相同 provider ID/info 但不同 auth manager；复用旧 session 会违反隔离语义 | Guardian session cache | 已采纳 |
| 011 | 阶段 A 实现可本地提交并接纳最新 main，但不因此改变验收状态 | 用户明确授权该 Git 交接，同时重申不授权阶段 B；提交不等于格式化、schema、构建、测试或双端点通过 | 交接 | 已采纳 |
| 012 | L2a ExecPlan 从冲突的 016 改号为 019 | 最新 main 已有不同任务的 Plan 016，Plan 018 又有明确后续用途；019 是当前首个未占用且无已知预留的编号 | 计划交接 | 已采纳 |
| 013 | loopback 验收进程显式设置 `NO_PROXY/no_proxy=127.0.0.1,localhost` | 宿主代理会截获 loopback 并返回 502；进程级绕过使两个 WireMock endpoint 直接可达，不改变产品配置 | 阶段 B 测试环境 | 已采纳 |
