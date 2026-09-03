# RONDO 配置指南

最后同步：2026-09-03

本文**只写 RONDO 相对冻结上游 Codex CLI `v0.147.0` 新增的配置**。上游本来就有的通用配置项
（`model`、`model_providers`、沙箱与审批策略、hooks、MCP 等）不在这里重复，请看：

- 各产品线的 [`multidev/docs/config.md`](../multidev/docs/config.md) / [`mydev/docs/config.md`](../mydev/docs/config.md)
- 上游官方参考：<https://developers.openai.com/codex/config-reference>

配置文件位置、层级与优先级规则沿用上游，**只有一处例外**：RONDO 把 `auto_review.model_provider` 也加进了
project-local 层的剥离名单。上游本来就会从项目层的 `.codex/config.toml` 里剥掉 `model_provider` /
`model_providers` 等键，RONDO 只是让 Guardian 的 provider 选择遵循同一条规则。被剥离时是**告警而不是报错**：

```
Ignored unsupported project-local config keys in <path>: auto_review.model_provider.
If you want these settings to apply, manually set them in your user-level config.toml.
```

所以凡是涉及 provider 的配置（含 §3.2 的本地推理示例），都要写在**用户级** `~/.codex/config.toml`
（即 `CODEX_HOME` 下那份），写进项目层不会生效。

> **口径**：本文所有字段以当前 `config/src/config_toml.rs`、`features/src/feature_configs.rs`
> 与 `core/src/config/mod.rs` 的解析代码为准。默认 reviewer 是 `user`，四个 Guardian override 默认不设置；
> 本文列出的 Multi 与 Local 专属能力默认关闭或缺省。

---

## 1. 公共 Guardian 配置（两条产品线都有）

Guardian 是 Codex 的 `approve for me` 自动审批子智能体。RONDO 在**两条产品线上一致地**扩展了它的
模型、provider、reasoning effort 与证据落盘配置。

### 1.1 先决条件：谁来审批

```toml
# 上游既有字段，默认 "user"
approvals_reviewer = "auto_review"   # 旧值 "guardian_subagent" 仍兼容
```

`approvals_reviewer = "user"` 时由你本人审批，下面这些 Guardian 覆盖项**仍会被加载，但不会被消费**。
`/status` 会如实区分这两种情况（见 §1.4）。

### 1.2 `[auto_review]` 的 RONDO 增量

上游的 `[auto_review]` 只有 `policy` 一项。RONDO 新增下面四项，全部可选，**不设即保持上游行为**：

```toml
[auto_review]
policy = "..."                         # 上游既有：插入 guardian prompt 的额外策略文本
model = "gpt-5.1-codex-mini"           # RONDO 新增
model_provider = "my-local"            # RONDO 新增
reasoning_effort = "low"               # RONDO 新增
evidence_dir = "/private/guardian-evidence"   # RONDO 新增，必须是绝对路径
```

| 字段 | 不设时 | 设了之后 |
|---|---|---|
| `model` | 依次回退到模型目录的 `auto_review_model_override`、provider 的默认 review model；都没有则用父会话模型 | 作为最高优先级的 review 模型 slug |
| `model_provider` | 继承父会话的 provider | 从合并后的 `model_providers` 注册表里选用该 provider |
| `reasoning_effort` | 按 review 模型的能力推导 | 直接覆盖推导值 |
| `evidence_dir` | **完全不采集证据** | 每轮 review 落盘一份证据 bundle |

几条容易踩的地方：

- **`model` 和 `model_provider` 是独立的两件事。** 只设 `model` 不会换 provider；只设 `model_provider`
  不会换模型。要跑本地推理审批，两个通常都得设。
- **`model_provider` 在配置加载期就校验。** 写了注册表里不存在的 ID 会直接报
  ``Model provider `x` not found`` 并加载失败，不是运行时静默回退。
- **显式 provider 自带认证。** 一旦设了 `model_provider`，Guardian 就不再继承父会话的凭据管理器
  ——除非该 provider `requires_openai_auth` 或是 Amazon Bedrock。这是刻意的：避免把第一方凭据
  漏给一个本来就没配认证的 provider。
- **配置了 `model` 不等于某次审批已经使用了这个模型。** 显式值是最高优先级的 review slug，
  但配置界面不知道某轮 review 是否发生、请求是否成功到达 provider。因此界面只说"配置已加载"，
  不声称"某次 review 用了它"。

### 1.3 `evidence_dir` 的数据敏感性

配置后，每轮 review 会写：

```
<evidence_dir>/<review_id>/E_final.json   # 最终发往模型的审批请求
<evidence_dir>/<review_id>/meta.json      # 该轮的元信息；未触达发送点时只写这一份，标记 evidence: none
```

**这些 bundle 未经脱敏。** 归一化只剥掉结构性和 provider 私有的传输字段，
`instructions` / `input` 里父轮累积的任何任务上下文都会原样留下。

**所以：请指向一个私有、git-ignored 的目录。** 该模块只写本地文件，不向任何地方发送。

### 1.4 在 `/status` 里查看

两条产品线的 `/status` 都会为已加载的覆盖项显示一行 `Guardian config`，语义完全相同：

```
 Guardian config:   loaded for reviewer auto_review (model gpt-5.1-codex-mini, reasoning effort low)
 Guardian config:   loaded, unused by reviewer user (model gpt-5.1-codex-mini)
```

第二种形态表示配置读到了，但 `approvals_reviewer` 是 `user`，所以 Guardian 不会用它。
一项覆盖都没配时不显示这一行。这一行只陈述**当前配置**与**当前 reviewer 选择**，
不代表任何一次审批实际跑过或实际用了哪个模型。窄终端下这一行和卡片其他字段一样会按宽度截断。

### 1.5 相关 feature gate

| feature key | 默认 | 说明 |
|---|---|---|
| `guardian_approval` | **开** | Guardian 审批能力本身，Stable |
| `guardianv2` | 关 | 开发中，未完成，不要在真实工作流里打开 |

---

## 2. RONDO Multi 专属配置（`multidev/`）

方向 3 的能力全部挂在上游既有的 `[features.multi_agent_v2]` 表下。
**`multi_agent_v2` feature 本身默认关闭**，下面所有东西都要先打开它。

```toml
[features.multi_agent_v2]
enabled = true                # 前提：不开这个，下面的都不生效
team_state_enabled = true     # RONDO 新增，默认 false
durable_team_enabled = false  # RONDO 新增，默认 false
```

RONDO 在这张表里新增的三项（其余字段是上游的）：

| 字段 | 默认 | 作用 | 依赖 |
|---|---|---|---|
| `team_state_enabled` | `false` | 暴露 canonical 团队世界状态：`team_*` 工具、team 协议前缀、每次采样的 active world index | `enabled = true` |
| `durable_team_enabled` | `false` | 让 Team State 跨进程持久化 | **硬依赖 `team_state_enabled = true`** |
| `[...publication_critic]` | 不存在 | 启用发布前的 Publication Critic 审查环 | **硬依赖 `team_state_enabled = true`** |

两条硬依赖都是**加载期 fail-closed**，不是静默忽略：

```
features.multi_agent_v2.durable_team_enabled requires team_state_enabled = true
features.multi_agent_v2.publication_critic requires team_state_enabled = true
```

### 2.1 Publication Critic（默认关闭，且判官未获质量资格）

> **先读这一段。** Publication Critic **不是发布门，也不是安全审批**，它是一个有界改写机制：
> 一个 publication cycle 最多三次审查，**第三次即使判 `REWRITE` 也会提交**；判官不可用或输出无效时
> 流程停止本轮审查并尝试提交当前稿。
>
> 更重要的是：**它的判官模型没有通过质量验收。** 本地判官多轮训练均为 `NO-GO`；
> 云端判官虽然 ROC AUC 与 boundary win 过线，但 False PASS `8/21` 超出 `5/21` 上限，
> 整条 operating curve 上不存在同时满足全部质量门的工作点。详见
> [README 的"诚实的结果"](../README.md#诚实的结果) 与
> [`doc/rondo-multi-publication-critic-product-contract.md`](rondo-multi-publication-critic-product-contract.md)。
>
> **下面的配置示例是给想复现实验的人用的，不代表这个能力可用于生产。**

整张子表缺省即为 OFF，publish 路径被完全绕过。要打开必须显式给出全部必填项：

```toml
[features.multi_agent_v2]
enabled = true
team_state_enabled = true          # 强制依赖

[features.multi_agent_v2.publication_critic]
endpoint = "127.0.0.1:8642"        # 必填
expected_descriptor_json = "{...}" # 必填，服务描述符的严格 JSON 编码
call_timeout_ms = 30000            # 可选，默认 30000
startup_timeout_ms = 60000         # 可选，默认 60000
```

| 字段 | 约束 |
|---|---|
| `endpoint` | 必填。必须是**字面量 socket 地址**（不接受主机名），且 IP 必须是 **loopback**。解析失败或非 loopback 一律拒绝 |
| `expected_descriptor_json` | 必填。与实际服务描述符**严格匹配**，不匹配直接 fail-closed，不降级运行 |
| `call_timeout_ms` | 可选，`1..=300000`，默认 `30000` |
| `startup_timeout_ms` | 可选，`1..=300000`，默认 `60000` |

**判官服务不在 Release 产物里，需要自行构建**（`codex-publication-critic-real-service` 或
`codex-publication-critic-cloud-service`），构建命令见 [README](../README.md#判官后端需要自行从源码构建)。
同包里的 `codex-publication-critic-service` 是**仅供测试的受控服务，不是产品判官**。

---

## 3. RONDO Local 专属配置（`mydev/`）

先说结论：**Local 只新增了一个专属配置字段**，就是下面的
`features.exec_command_repeat_guidance`。Guardian 那四项是两条线共用的（见 §1），
除此之外 Local 没有再往 `config.toml` 里加任何产品字段。

### 3.1 `features.exec_command_repeat_guidance`

```toml
[features]
exec_command_repeat_guidance = true   # RONDO Local 新增，默认 false
```

| 项 | 事实 |
|---|---|
| 默认 | `false`，且 Stage 是 `UnderDevelopment`（不进 `/experimental` 菜单，但 `[features]` 里写了就生效） |
| 做什么 | 在 `exec_command` 工具的**描述文本**后追加一段有界提示，劝阻"调用参数完全相同、且不会带来新信息"的重复调用 |
| 生效范围 | 只作用于 unified exec 的 `exec_command`；`shell_command` 恒不带该提示 |
| 不生效 | 子智能体（非 root）会话不带；Guardian 审批会话恒定关闭 |

它**只改工具描述文本**，不拦截、不改写、不阻断任何命令——要不要重复仍由模型自己判断。
提示语本身也写明了轮询/等待、状态变化后、恢复重试、用户明确要求继续等情形属于正常重复。

打开它会照常触发上游的 under-development 警告（提示该类 feature 不完整、行为可能不可预期），
可用上游既有的 `suppress_unstable_features_warning = true` 关掉。

方向 1 已经收口，本项目不再推进这个 feature 的 Stage，也不对外给出它的效果数字
（见 [README 的"诚实的结果"](../README.md#诚实的结果)）。

### 3.2 本地推理审批：接缝存在，资格没有

方向 2 的最终结论是**保留为实验、未采用**。这一节只说明"哪些东西是真的已经存在的"，
避免读成"配上就能用"。

**已经存在的**是一条纯配置路径，而且它用的全是上游既有字段加 §1 的公共 Guardian 增量，
Local **没有**为此新增任何产品配置：

```toml
# 必须写在用户级 ~/.codex/config.toml，不能写进项目层 .codex/config.toml
[model_providers.my-local]        # 上游既有字段，完整字段见开头的上游配置参考
name = "local"
base_url = "http://127.0.0.1:8080/v1"
wire_api = "responses"

[auto_review]                     # §1 的公共 RONDO 增量
model_provider = "my-local"
model = "<该本地服务实际提供的模型 id>"
```

上游本来就内置了 `ollama` 与 `lmstudio` 两个 OSS provider，用它们时不必自己写 `[model_providers]`，
直接把 `model_provider` 填成对应 ID 即可。四个容易踩的运行前提：

- **必须放在用户级配置层。** 这是最容易白忙一场的一条：项目层 `.codex/config.toml` 里的
  `model_providers` 和 `auto_review.model_provider` 都会被剥掉（见本文开头），只留一条告警，
  Guardian 仍然用父会话的 provider。放在 `~/.codex/config.toml` 才生效。
- **本地服务必须讲 Responses 协议。** 冻结基线里 `wire_api` 只接受 `"responses"`；写 `"chat"`
  会得到明确的"已移除"错误，写别的值报 unknown variant。纯 chat-completions 的本地服务接不进来
  （老的 `ollama-chat` ID 同样会得到一条专门的"已不再支持"错误）。
- **显式 provider 不继承父会话凭据**（§1.2 最后一条）。本地服务若需要 key，要自己用
  `env_key` 之类的方式配。
- **`model` 必须是该 provider 真正提供的 slug。** 它是最高优先级的 review 模型名，不会再回退到目录
  或 provider 默认值。

**不存在的**同样要说清楚：仓库不分发模型权重，也不分发推理运行时，更没有"内置本地审批模型"开关。
把上面配上，只表示 Guardian 会把审批请求发到那个地址；**它不表示任何模型已经取得审批用途的质量资格**。
方向 2 的历史结论不因为这条路径可配置而升级。

### 3.3 别和 `rondo.local.toml` 搞混（两条独立链路）

仓库根的两个受跟踪示例文件**不是产品配置，CLI 根本不读**。三个配置面并排看：

| 配置面 | 谁读 | 装什么 |
|---|---|---|
| `~/.codex/config.toml` 及各配置层 | 产品 CLI 本身 | 上游配置面 + 本文列出的 RONDO 增量 |
| 根 `rondo.local.example.toml` → ignored `rondo.local.toml` | `eval/` 测评设施（Python） | 本机测评参数：付费 provider 别名与价格、本地推理服务的启动参数等，**不放任何 API Key** |
| 根 `rondo.secrets.example.env` → ignored `.env.local` | 测评设施的密钥加载器 | 只放 `KEY=VALUE` 形式的密钥 |

也就是说：`rondo.local.toml` 里的 `[local_model]` 描述的是**测评侧**怎么起一个本地推理服务，
和产品的 `[auto_review]` 是两条独立的链路——改前者不会改变 CLI 的任何行为。
数据资产与目录规范见 [`doc/eval-data-layout.md`](eval-data-layout.md)。

### 3.4 Local 没有的东西

- **没有 Local 专属 TUI 面板。** Guardian 随审批流走，`/status` 那一行就够了。
- **没有 §2 那些字段。** `[features.multi_agent_v2]` 这张表本身是上游的，Local 也有；但 RONDO 往里加的
  `team_state_enabled` / `durable_team_enabled` / `publication_critic` **只存在于 Multi**。这张表是
  `deny_unknown_fields`，所以在 Local 的 `config.toml` 里写这几个键会被当作未知键报错，不是静默忽略。

---

## 4. 不在本文范围内的

- **上游通用配置**：见本文开头的链接。
- **开发与构建设施**：构建锁、资源看门狗、CI 与发布流水线分别见
  [`doc/development-environment.md`](development-environment.md)、
  [`doc/ci-pipeline.md`](ci-pipeline.md)、[`doc/cd-release-pipeline.md`](cd-release-pipeline.md)。
