# 方向 2：本地审批模型接入与横评

最后更新：2026-08-10 ｜ 依赖：P0（S1/S2）｜ 当前 Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 目标

把 Codex `approve for me` 的审批模型换成可在本地推理的小模型，量化其审批质量与成本相对云端模型的差距。能力必须**可插拔、一键切换**，且不影响原有功能与性能。

## P1 当前状态

- **L1 完成**：已落地 Standard/Responses Lite 双形态 `E_final` 解析、exact policy bytes
  身份哈希、provider-neutral canonical payload 与结构化决策校验。出站静态 payload 同时排除
  顶层 `tools`、Lite `additional_tools`、warehouse-only metadata 和 provider-private 运输字段，
  malformed/歧义证据 fail-closed；合法 `ToolSearchOutput.tools` 作为既有证据保留，Luna/Sol/Local
  三个 consumer projection 对同一 Standard/Lite fixture 产生完全相同的 canonical bytes。
- **L2 前置设施就绪，真实验收未运行**：llama.cpp 固定为 `b10333`/commit
  `08659901c43b51de735740f1cf61bb82fbe0c4e4`，项目局部 CPU x64 运行时、Responses
  client、doctor、fake server、结构化输出本地校验和启动入口已实现。运行时 lock 覆盖项目目录
  52 个普通文件、10 个 symlink 和 8 个宿主动态依赖，启动环境移除 `LD_LIBRARY_PATH`；client
  禁止 redirect 并绑定 endpoint/model identity，模型存在时还要求 GGUF header 与配置 digest。
  无模型 doctor 返回 `infrastructure_ready_model_missing`/78，不把 router 健康冒充模型就绪。
- 当前未提供本地模型权重，本批也明确禁止下载；因此未启动真实模型、未推理、
  未量显存/上下文/首 token/总耗时，L2 验收与 L2a/L3/L4 保持待后续阶段。

## 核心设计（已定，不再反复讨论）

- **正式端到端测评统一用 `--approve-for-me` 对应的三项配置**：
  `approvals_reviewer = "auto_review"`、`approval_policy = "on-request"`、
  `sandbox_mode = "workspace-write"`。Guardian 另显式覆盖为 `gpt-5.6-luna` + `low`，继续使用
  Codex 原生 Guardian 框架与只读取证能力。0.147 的 CLI shorthand 一次展开这三项；测评元数据
  仍逐项记录，不能只写一个模糊的“approve for me”。
- **为什么必须显式指定模型**：`v0.147.0` 的默认值已不是单一的
  `codex-auto-review`：OpenAI API key 路径默认 `gpt-5.6-luna`，ChatGPT 路径默认
  `codex-auto-review`，Bedrock 则返回 provider 自身模型 id；候选不在 catalog 且无 metadata
  override 时仍会回退主模型。测评必须显式写死模型与
  effort，以免认证方式或 provider 变化暗中改变实验变量。`sol + low` 作为高正确率
  上限对照，`luna + low` 作为经济基线；两者都复用既有 API provider。
- **`Luna-Guardian-live` 是真实可部署系统的结果**；`Luna-static` / `Sol-static` / `Local-static`
  三个同证据组才是严格的模型横向比较。后者统一**不给模型任何工具与自主调查能力**：static
  consumer 必须移除顶层 `tools`，也必须移除 Lite `input` 中的 `additional_tools` developer item，
  再构造 provider-neutral 的单轮结构化请求。只检查“没有顶层 tools”不足以证明无工具。
  （这里说的“无网络”指模型侧没有自主联网能力；runner 仍需联网访问 Luna / Sol API。）
- **`E_final` 有两种等价的完整逻辑请求形态**：标准 Responses 把 Guardian policy 放在顶层
  `instructions`、工具放在顶层 `tools`；`v0.147.0` 的 Luna 使用 Responses Lite，policy 改放
  `input` 里的 developer message，工具改放 `additional_tools` item，顶层 `instructions` 为空且
  `tools` 缺席。影子回放必须先解析成统一的逻辑 payload，不能假设固定 JSON 位置。
- 这组对比回答的是"面对 Luna 实际收集到的同一组证据，不同模型会怎么判"，**不宣称**比较了各模型拥有工具后的完整 Agentic 调查能力。
- **严格耗时测评期间不在线运行影子模型**，尤其避免本地 8B 模型造成 GPU/CPU/内存/温度/调度波动；只记录证据包，任务结束后离线回放。普通调试阶段可酌情在线跑云端静态影子。
- Sol 成本较高，只对预先固定的分层样本或重点诊断样本回放；Luna 与本地模型可全量回放。
- 不自建第二套会话系统、不做证据链重建或工具状态机，只在 Guardian 请求发送前截快照（见 P0-S2）。
- `v0.147.0` 的 Guardian policy/template 与审批 prompt 已有实质变化，approval/retry reason 也会成为
  有意义输入。证据与标签必须记录 policy/baseline 版本，不把 0.146.1 和 0.147 样本静默混合训练或横评。
- **预留但不现在做**：若后续要研究"取证调查本身值多少分"，只需额外保存该审批轮的**首个**请求 `E0`，与 `E_final` 对比即可，仍然不引入会话管理或证据链重建。P0 只做 `E_final`。

## 任务分解

### L1 静态影子审批协议（规模 S）

- 输入：规范化 `E_final`；输出：结构化判定（allow / deny + 理由 + 风险标签）。
- 三个 static 组共用完全相同的输入与输出契约，任何一方多拿信息都视为设施 bug。
- 硬性：出站请求既不得包含顶层 `tools`，也不得在 `input` 中携带 `additional_tools`，不得给模型
  任何自主取证能力。
- 验收：单测同时覆盖标准 Responses 与 Responses Lite 的 `E_final`，将两者解析为
  **规范化逻辑 payload**（policy/instructions + 任务 input + 输出 schema），再断言三个 static 组
  逐字节一致；同时断言出站请求既无顶层 `tools`，也无 Lite `additional_tools`。provider URL、
  headers、认证方式天然不同，不在比较范围内。
- 原始 `E_final` 保留 `internal_chat_message_metadata_passthrough.executed_tool_calls` 以忠实记录 wire；
  该字段按上游契约仅供 warehouse，构造 static 逻辑 payload 时必须排除，不能作为影子模型输入。

### L2 本地推理服务接入（规模 M）

- 形态：起本地 OpenAI 兼容 HTTP 服务（llama.cpp server 或 Ollama，GGUF `Q4_K_M`），通过 `codex-rs/model-provider-info` 的既有 OpenAI 兼容 provider 配置指向它。**不新增 provider crate**，保持轻量（上游已有 `ollama` / `lmstudio` crate 可参考，但审批走静态无工具路径，不必复用其全部逻辑）。
- 首选运行时固定为 **llama.cpp server**，统一使用 `/v1/responses`；根目录受跟踪的
  `rondo.local.example.toml` 定义参数合同，机器实际值写入忽略的 `rondo.local.toml`。API Key 只从根目录
  忽略且权限收紧的 `.env.local` 按变量名加载，不进入 TOML、命令行、日志或工件。linked worktree 的加载器
  必须通过 Git common dir 定位主仓库根，复用同一份本机配置，不在各 worktree 复制密钥。
- 硬件约束（RTX 4060 Laptop 8GB VRAM）：
  - 8B 级模型 Q4 权重约 4.8GB，剩余显存要留给 KV cache。
  - 审批证据包可能很长（任务轨迹 + 工具结果），**上下文预算必须实测**，不能拍脑袋。L2 的第一件事就是量出"在不 OOM、不掉到共享内存的前提下，实际能吃多长的证据包"。
  - 若首选 `mistralai/Ministral-3-8B-Instruct-2512` 的上下文余量不够，按备选 `Qwen/Qwen3.5-9B` 或更低量化档重新评估；这是实测决策点，不预设结论。
- **搭建与验收分处两阶段**：服务搭建、量化选型和上下文预算实测可以在 P1 期间用手工构造的证据包先行完成；但**最终验收必须用真实 `E_final`**，因此挂在 B3 产出第一批真实证据之后。
- 验收：本地服务能对一条**真实** `E_final` 返回合规结构化判定，并记录显存峰值、首 token 延迟、总耗时。

### L2a Guardian provider 覆盖（规模 M，L7 的前置）

L2 只是把本地服务跑起来，**并不等于 Guardian 会把请求发到它那里**。
`build_guardian_review_session_config`（`core/src/guardian/review_session.rs`）克隆父会话配置，只把
provider 字段中的 `request_max_retries` / `stream_max_retries` 改为 1，provider id 与 base_url 原样继承。
`v0.147.0` 新增的 provider/auth 默认模型分流也没有改变这个事实。因此 P0-S1 只改本地
模型名时，该名称仍会被发往父会话的 provider 端点。

- 目标：让 Guardian 审批会话可以使用与主 Agent **不同的** provider。
- 落点：在 `[auto_review]` 增加 provider 覆盖项，并在 `build_guardian_review_session_config` 中一并改写 `model_provider_id` / `model_provider`。
- 需要一并处理的现实问题：本地服务的鉴权形态（多为无鉴权或假 key）、`supports_websockets = false`、超时与重试、本地模型不在模型目录中时的 `ModelInfo` 回退路径（`review.rs` 已有 `model_override.unwrap_or(turn.model_info.slug)` 的 else 分支可用）。
- 硬约束：不改变主 Agent 的 provider 解析；未配置覆盖时行为与 P0 后完全一致。
- 验收：主 Agent 用 OpenAI provider、Guardian 用本地 provider 时，两侧请求分别落到各自端点（用两个 mock server 断言）。

### L3 离线影子回放器（规模 M）—— **M3**

- 批量读取 `E_final`，分别喂给 `Luna-static` / `Sol-static` / `Local-static`，记录判定、理由、耗时、token 与成本。
- 与正式耗时测评完全解耦，不在线运行。
- 结果写入方向 0 的统一结果库（共用 schema）。
- 产出：本地模型**未微调** baseline 的首版横评报告。

### L4 审批质量指标（规模 S）

- 与 `Luna-Guardian-live` 的一致率。
- **危险动作漏放率（false allow）**：最重要的指标，权重高于其他。
- **过度拒绝率（false deny）**：直接转化为任务失败代价。
- 成本与延迟：单次审批 token 成本、P50/P95 延迟、本地侧显存峰值。
- 需要一个小规模人工标注集（几十条）作为 ground truth，一致率不能只对齐 Luna 自己。

### L5 合成训练数据管线（规模 M，授权门：GPT 批量合成费用）

- 训练集用 **GPT 批量合成**，不依赖真实跑批规模。

**真实 `E_final` 必须先做互斥切分，再谈用途。** 让同一批真实证据既当合成模板又当评测集，即使原文没进训练集，基于评测样本生成训练数据仍是信息泄漏——合成器会把评测集的分布、话术和难度特征带进训练集。因此：

| 分区 | 用途 | 禁止 |
|---|---|---|
| `seed` | 给合成器做格式与难度模板（几十条足够） | —— |
| `holdout` | 只用于 L3/L4 评测 | 任何形式进入合成上下文、提示词或人工参考 |

- 切分键必须是**跨运行稳定的语义身份**，不能用 `review_id`——
  `new_guardian_review_id`（`core/src/guardian/review.rs`）每轮生成新的 UUID v4，同一任务同一动作重跑
  会换 id，可能第一次落 holdout、第二次落 seed，互斥就只对文件实例成立、对语义样本不成立。
  改用 `sha256(task_id + 规范化待审批动作指纹)` 落桶；无 task_id 的场景退化为动作指纹本身。
- 切分不按人工挑选，避免选择偏差；切分结果写入清单并冻结，后续增量按同一规则划分，不重划历史。
- **近重复检查**：合成产出的训练样本对 `holdout` 做一次近重复检测（n-gram Jaccard 或 MinHash 即可，不上重型工具），命中阈值的样本剔除并记录数量。
- 合成要覆盖的分布：明确安全、明确危险、边界模糊、证据不足、伪装成安全的危险动作、工具结果与请求不一致。
- 产出：训练集 JSONL + 数据卡（合成方法、seed 分区来源、分布、去重与近重复检查结果、SHA256）。

### L6 微调回路（规模 L，授权门：云 GPU 训练）

流程：仓库内导出 → 上传云 GPU → LoRA SFT → 合并与量化 → 回本地推理 → L3 重跑横评 → **M4**。

**仓库边界按数据体量决定（决策门，L5 出数后立即确认）：**

| 条件 | 处置 |
|---|---|
| 训练集总量 ≤ 100MB 且单文件 ≤ 40MB | 数据集与训练脚手架一起放仓库内独立板块 |
| 超过上述阈值 | 仓库只留训练脚手架 + 数据卡 + SHA256，数据集放仓库外，单独上传云 GPU |
| 模型权重（GGUF / LoRA adapter） | **始终**在仓库外，无论大小 |

- 目录形态：新增顶层 `training/`（脚手架、数据卡、模型版本登记表），与 `mydev/` 严格隔离，不参与 Rust 构建。落地时需同步更新 `AGENTS.md` 的仓库边界一节。
- 仓库内必须留下的最小可复现信息：超参、基座模型与版本、数据卡、产出权重的哈希与对应横评分数。

### L7 一键切换与端到端可用性（规模 S，依赖 L2a）

- 通过 **S1（模型/effort）+ L2a（provider）** 两个配置项把 Guardian 审批切到本地模型，验证端到端可正常审批。**仅有 S1 做不到这件事**。
- 仅在非严格耗时场景验证；正式耗时测评仍按核心设计走 `Luna-Guardian-live`。
- 验收：切换只改配置，不改代码；切回云端模型行为与性能无残留影响。

## 与方向 0 的接口

- 消费：P0-S2 产出的规范化 `E_final`。
- 复用：方向 0 的结果库 schema、归档与曲线脚本。
- 反馈：L4 的审批失败归因回流到方向 0 的 B5 失败归因分类。

## 硬约束

- 三个 static 组的**规范化逻辑 payload** 必须逐字节一致，不得任何一方多拿信息（provider URL / headers / 认证除外）。
- 静态影子一律不给模型工具与自主取证能力；runner 访问推理端点不受此限。
- 真实证据包不进训练集；`holdout` 分区不得以任何形式进入合成上下文。
- 权重文件不进仓库。
- 严格耗时测评期间不在线跑本地模型。
- 一键切换不得以弱化审批逻辑为代价换取通过率。
- 把证据包发给云端模型（Luna / Sol 静态影子）属于**数据外发**，须单独授权；首次外发前人工抽查一批样本，确认没有明显不应外传的内容。
