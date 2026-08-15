# 方向 2：RONDO Local 本地审批模型接入与横评

最后更新：2026-08-14 ｜ 产品线：RONDO Local（`mydev/`）｜ 依赖：P0（S1/S2）｜ 当前 Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 目标与定位

把 Codex `approve for me` 的审批模型换成可在本地推理的小模型，量化其审批质量与成本相对云端教师模型的差距。
能力必须**可插拔、一键切换**，且不影响原有功能与性能。

定位是**学习型教师蒸馏**：从云端教师（Sol）的判断中蒸馏出一个本地小模型，不是从零建立一套审批能力。
当前本地审批模型**不计划正式投入生产**，目标是机器学习、数据分析和工程实践，
不提前建设生产级安全与数据治理体系。将来若决定投入真实使用，再单独建立面向生产的正确性与安全验收。

## 角色分工：Sol 生成标签，Opus 5 担任裁判

二者不混用，避免“用 Sol 的标签去评 Sol”的循环。两条入口都是**订阅制、不额外计费**，
因此不占 API 预算授权门（见 `doc/WBS.md` §6）；数据外发门仍然适用。

### Sol —— 教师标签

- Sol 生成的标签作为训练、验证和离线测评的**教师标签**，用于衡量本地模型对教师判断的蒸馏效果，
  **不冒充独立人工 ground truth**；不要求人工逐条确认，也不设“高风险审批必须人工裁决”的门槛。
- 人工只在发现明显错误、数据冲突或训练结果异常时介入；不设固定抽检比例，不建设标签可信、审计或多模型共识系统。
- **调用入口：订阅制 Sol，经开发用 Codex 生成**，不走按量付费 API，因此合成数据规模不受 API 预算门约束，
  只受订阅速率与配额限制。开发用 Codex 还负责生成流程、整理、训练和分析。
- **使用方式：人在场，用仓库内预先写好的冻结 prompt 发送，不作为纯自动化后端。** 产物是冻结文件；
  `eval/` 只**导入**这些文件，不程序化调用 Sol，也不为教师侧另开按量付费 API 入口。
- 只保留机器学习实验所需的最低限度卫生：记录 Sol 模型标识与生成日期、生成 prompt 和数据版本；
  训练集与测试集去重并隔离。

### Opus 5 —— 横评裁判

- **正式同证据横评（Local M4）由 Opus 5 担任裁判**，通过 Claude Code 订阅账号在会话内完成。
- 订阅账号只用于会话内、人工在场监督的判定工作，**不得**作为程序化 provider 接进 `eval/` 当批量推理后端。
- 裁判独立性有一处已知瑕疵且接受：Opus 5 同时参与本项目开发。鉴于目标是工程与 ML 实践而非生产验收，
  不为此建设隔离机制，只在结果表述中注明。

## 当前状态

- **L1 完成**：已落地 Standard/Responses Lite 双形态 `E_final` 解析、exact policy bytes
  身份哈希、provider-neutral canonical payload 与结构化决策校验。出站静态 payload 同时排除
  顶层 `tools`、Lite `additional_tools`、warehouse-only metadata 和 provider-private 运输字段，
  malformed/歧义证据 fail-closed；合法 `ToolSearchOutput.tools` 作为既有证据保留，Luna/Sol/Local
  三组 consumer 协议投影对同一 Standard/Lite fixture 产生完全相同的 canonical bytes；这项验收不等同于
  三套生产调用端均已实现。
- **L2 的 CPU 与 Linux CUDA model-free 运行闭包均已就绪**：llama.cpp 固定为 `b10333`/commit
  `08659901c43b51de735740f1cf61bb82fbe0c4e4`，项目局部 CPU x64 runtime closure、Responses client、
  doctor、fake server、结构化输出本地校验和启动入口已实现。运行时 lock 覆盖项目目录
  52 个普通文件、10 个 symlink 和 8 个宿主动态依赖，启动环境移除 `LD_LIBRARY_PATH`。配置/命令现可精确表达 4k
  原生 auto+fit smoke 与 8k all+fit-off baseline，固定单卡 split/main GPU、F16 K/V、512/256 batch、no-mmproj、
  Jinja 和显式官方模板。2026-08-13 已以项目局部 CUDA Toolkit 12.6.2、Ada `89-real` strict link 构建 exact
  b10333 CUDA runtime；独立 lock 冻结 source/tree、工具链、configure/build、9 个 ELF 文件、14 个 symlink、
  RUNPATH、cudart/cuBLAS、WSL `libcuda.so.1` 与系统闭包。清除 `LD_LIBRARY_PATH` 后 version/help 成功，model-free
  device/router probe 识别 RTX 4060 Laptop 并返回 `linux_cuda_built_model_unvalidated`。
- model-backed client 必须消费 launcher 写入主仓 `eval-data/local-approval/launcher-identity.json`
  的 0600 私有 receipt，绑定 nonce、PID/start ticks、实际 cmdline、监听 socket、runtime/model
  identity/path/id、endpoint 和实际服务参数指纹。schema v2 会拒绝旧 receipt；client 在 identity probe 后、decision 前以及 decision 返回后重验同一
  launcher 实例；redirect、receipt 替换、进程/监听者变化都 fail-closed。这是轻量实例身份
  约束，不是签名或权限系统，也不证明 server 实际加载了 receipt 所声明的全部字节，或 launcher 退出后
  server 必然随之退出。
- **model-backed 资格设施已就绪，一条真实证据在 4k 合同下被拒**。受限 qualification 入口、版本化 model-backed
  evidence 与单向 capability 投影已落地：正式 launcher 在证据缺失、无效或身份不匹配时一律在进程启动前拒绝，
  CUDA source build 与 CPU release 的服务身份分别精确绑定 `b1-0865990` 与 `b10333-08659901c`；
  qualification 的输入由受跟踪 selector 预先绑定唯一 path、`E_final`/meta SHA 与期望 Guardian 模型/effort，
  并复用生产 evidence reader 与 meta 校验。2026-08-14 真实模型已首次成功加载：exact GGUF 装载、服务身份与
  `/props` 上下文 4096 均通过核验。但该冻结样本的 static payload 经服务端 tokenizer 实测为 **5,313 input tokens**，
  超过 4096 上下文，llama.cpp 按合同返回 exceed-context 错误，因此没有产生结构化判定，未写入任何证据，
  能力保持 `linux_cuda_built_model_unvalidated`、CUDA lock 的 `model_backed_structured_output` 保持 `not_run`。
  显存峰值、首 token 与总耗时随该失败一并作废，尚无 model-backed 指标。
- **exact-token 普查（WP3b-A2）尝试过但未完成**：47 条真实归档只有 **24 条取得 exact token 数**，
  另 23 条在计数前就被冻结 b10333 拒绝，**没有得到全集分布**，不得当作普查完成。
  已确证的有限事实：
  1. **长度（只覆盖那 24 条）**：min 5,313、p50 7,886、p95 12,354、max 18,921。按 `input+512`，
     4k 适配 0/24、8k 适配 9/24、12k 22/24、16k 23/24、24k 24/24。**这些比例只描述这 24 条**；
     其余 23 条的 token 数未知，因此全集的 fit 数量无法给出，也不存在已证明的全集上限。
  2. **21 条已定性**：其 `reasoning` item 没有数组 `content`，被 Responses adapter 以 400 拒绝。
     真实 `/v1/responses` 判定路径共用同一 converter，所以当前请求路径同样会拒绝，
     **加大上下文救不回这 21 条**。
  3. **2 条未定性**：旧运行中返回通用 500。该状态是服务端对任意内部异常的兜底，
     现有证据不能判定它与长度、形状、模板还是其他故障有关；这 2 条既没有 token 数，也没有原因结论。
- **设施与运行的版本边界**：两次真实运行（结果一致、锚点 5,313）属于 `6b36d05` **之前**的实现。
  整改后的当前代码只通过无模型回归，尚未真实运行过。
- **下一步不是选档位，而是先做 provider-neutral static-payload 兼容**：以**已证实的那 21 条**为输入，
  对其 item 形状定义一个版本化、所有 static consumer 一致的合法投影，同步更新 L1 的逐字节等价合同与
  focused tests；不得只为 llama.cpp 做隐蔽的 provider-specific 删减。兼容合同与无模型门禁通过后，
  再重新申请一次真实模型授权、重跑 47/47 普查；重跑若仍出现通用 500，继续 fail closed 并单独诊断，
  不预先承诺兼容能解决那 2 条。拿到全集分布后才定上下文档位。
  在此之前不冻结 8k/12k/16k/24k 任何档位，也不把“只用合成证据、真实证据只取可服务子集”设为默认路线。
- **唯一权重已下载且仅静态验收**：2026-08-12 已将未微调纯文本基线冻结为 Bartowski 模型卡声明从官方
  Ministral 3 8B Instruct 2512 BF16 转换的 `Q4_K_M`，固定 repo revision、文件、大小、LFS SHA、
  单文件下载/校验和 8GB 两阶段上下文方案。2026-08-13 唯一 GGUF 已通过普通文件、精确
  `5,198,387,456` bytes 与 SHA-256 `7deb50ec…54802a` 校验；Git 未跟踪，真实 ignored 配置未写入，模型从未加载。
  真实 ignored `rondo.local.toml` 已于 2026-08-14 迁移到 exact GGUF 与 4k `auto`/`fit=on` 合同，
  `providers`、`paid_eval` 与价格配置未变、权限仍为 0600；doctor 现返回 `configuration: valid` 与
  `linux_cuda_built_model_unvalidated`。冻结选择见 2026-08-12 快照，下载/CUDA 证据见 2026-08-13 快照。
  真实 model-backed 结构化输出仍是 `gpu_model_serving_validated` 的硬前置。

### 当前推进顺序

1. 先做 provider-neutral static-payload 兼容，再重跑 47/47 exact-token 普查，然后才定上下文档位
   （当前阻塞点，见上文）。
2. 按定案后的合同完成 model-backed smoke，记录加载身份、显存峰值、首 token 与结构化输出；
   资格设施、证据 schema 与 capability 投影已就绪，只需按新合同重跑并生成版本化证据。
3. 通过后，连同 L7 的“仅改配置切换”一起形成 **Local M3**；不同上下文档位互相独立验收，
   任一档位失败不得靠弱化 identity 或输出校验凑绿。
4. **L5a**：用冻结 prompt、人在场经开发用 Codex 生成第一批 Sol 教师标签。
5. 跑 L3/L4：程序化批量运行 `Local-static`，对照导入的教师标签，固化指标口径，得到未微调 baseline。
6. 之后按 **L5b** 合成训练数据、L6 云 GPU LoRA 微调推进，最后是 **Local M4**。

真实模型加载/推理与重型 Cargo、Docker 互斥；未完成 4k 前，能力只称
`linux_cuda_built_model_unvalidated`。

## 核心设计（已定，不再反复讨论）

- **正式端到端测评统一用 `--approve-for-me` 对应的三项配置**：
  `approvals_reviewer = "auto_review"`、`approval_policy = "on-request"`、
  `sandbox_mode = "workspace-write"`。Guardian 另显式覆盖为指定云端模型 + `low` effort，继续使用
  Codex 原生 Guardian 框架与只读取证能力。0.147 的 CLI shorthand 一次展开这三项；测评元数据
  仍逐项记录，不能只写一个模糊的“approve for me”。
- **具体云端模型不在本页固定**：历史 v1—v22 使用 `gpt-5.6-luna` + `low`；**Luna 当前不可用**，
  新批次的供应商、base URL 与模型由 ignored `rondo.local.toml` 的 `paid_eval` profile 选择，
  再由每批的独立 pair lock 冻结实际条件。
- **为什么必须显式指定模型**：`v0.147.0` 的默认值已不是单一的
  `codex-auto-review`：OpenAI API key 路径默认 `gpt-5.6-luna`，ChatGPT 路径默认
  `codex-auto-review`，Bedrock 则返回 provider 自身模型 id；候选不在 catalog 且无 metadata
  override 时仍会回退主模型。测评必须显式写死模型与 effort，以免认证方式或 provider 变化暗中改变实验变量。
- **`Guardian-live` 是真实可部署系统的结果**；同证据 static 组才是严格的模型横向比较。
  static 组统一**不给模型任何工具与自主调查能力**：static consumer 必须移除顶层 `tools`，
  也必须移除 Lite `input` 中的 `additional_tools` developer item，再构造 provider-neutral 的单轮结构化请求。
  只检查“没有顶层 tools”不足以证明无工具。（这里说的“无网络”指模型侧没有自主联网能力；
  runner 仍需联网访问云端 API。）
- **`E_final` 有两种等价的完整逻辑请求形态**：标准 Responses 把 Guardian policy 放在顶层
  `instructions`、工具放在顶层 `tools`；Responses Lite 把 policy 改放
  `input` 里的 developer message，工具改放 `additional_tools` item，顶层 `instructions` 为空且
  `tools` 缺席。影子回放必须先解析成统一的逻辑 payload，不能假设固定 JSON 位置。
- 这组对比回答的是“面对实机 Guardian 实际收集到的同一组证据，不同模型会怎么判”，
  **不宣称**比较了各模型拥有工具后的完整 Agentic 调查能力。
- **严格耗时测评期间不在线运行影子模型**，尤其避免本地 8B 模型造成 GPU/CPU/内存/温度/调度波动；
  只记录证据包，任务结束后离线回放。
- 不自建第二套会话系统、不做证据链重建或工具状态机，只在 Guardian 请求发送前截快照（见 P0-S2）。
- `v0.147.0` 的 Guardian policy/template 与审批 prompt 已有实质变化，approval/retry reason 也会成为
  有意义输入。证据与标签必须记录 policy/baseline 版本，不把 0.146.1 和 0.147 样本静默混合训练或横评。
- **预留但不现在做**：若后续要研究“取证调查本身值多少分”，只需额外保存该审批轮的**首个**请求 `E0`，
  与 `E_final` 对比即可，仍然不引入会话管理或证据链重建。P0 只做 `E_final`。

## 任务分解

### L1 静态影子审批协议（规模 S）

状态：**已验收**。

- 输入：规范化 `E_final`；输出：结构化判定（allow / deny + 理由 + 风险标签）。
- 所有 static 组共用完全相同的输入与输出契约，任何一方多拿信息都视为设施 bug。
- 硬性：出站请求既不得包含顶层 `tools`，也不得在 `input` 中携带 `additional_tools`。
- 验收：单测同时覆盖标准 Responses 与 Responses Lite 的 `E_final`，将两者解析为
  **规范化逻辑 payload**（policy/instructions + 任务 input + 输出 schema），再断言各 static 组
  逐字节一致；同时断言出站请求既无顶层 `tools`，也无 Lite `additional_tools`。provider URL、
  headers、认证方式天然不同，不在比较范围内。
- 原始 `E_final` 保留 `internal_chat_message_metadata_passthrough.executed_tool_calls` 以忠实记录 wire；
  该字段按上游契约仅供 warehouse，构造 static 逻辑 payload 时必须排除。

### L2 本地推理服务接入（规模 M）

- 形态：起本地 OpenAI 兼容 HTTP 服务（llama.cpp server，GGUF `Q4_K_M`），通过
  `codex-rs/model-provider-info` 的既有 OpenAI 兼容 provider 配置指向它。**不新增 provider crate**。
- 运行时固定为 **llama.cpp server**，统一使用 `/v1/responses`；根目录受跟踪的
  `rondo.local.example.toml` 定义参数合同，机器实际值写入忽略的 `rondo.local.toml`。API Key 只从根目录
  忽略且权限收紧的 `.env.local` 按变量名加载，不进入 TOML、命令行、日志或工件。linked worktree 的加载器
  必须通过 Git common dir 定位主仓库根，复用同一份本机配置，不在各 worktree 复制密钥。
- 硬件约束（RTX 4060 Laptop 8GB VRAM）：8B 级模型 Q4 权重约 4.8GB，剩余显存要留给 KV cache；
  **上下文预算必须实测**。已实测的 24 条真实 `E_final` 为 5,313—18,921 tokens，4k 一条都装不下，8k 装得下 9 条；
  其余 23 条尚无 token 数（21 条形状被拒、2 条 500 未定性）。档位要等全集分布出来后再与 8GB 显存的 KV 预算求交。
- 验收：本地服务能对一条**真实** `E_final` 返回合规结构化判定，并记录显存峰值、首 token 延迟、总耗时。

### L2a Guardian provider 覆盖（规模 M，L7 的前置）

状态：**已验收**。实现与证据见 `plan/019-l2a-guardian-provider-override-execplan.md`。

- `[auto_review].model_provider` 引用合并后的 `model_providers` registry；未知或空白 ID 在配置加载时
  fail-closed，项目局部配置不能重定向 provider。
- Guardian 替换 provider ID 与完整配置后仍把 request/stream retry 固定为 `1/1`；未配置时继续继承
  主 Agent provider，主 Agent 配置与端点不变。
- 显式独立 provider 按自身 env/static bearer/command/无鉴权语义工作；无鉴权 endpoint 不接收主 Agent
  凭据，鉴权继承策略也参与 Guardian session 复用失效。
- 阶段 B 已通过 schema、config/Guardian 安全回归与两个 loopback mock endpoint 验收。该结论只证明
  provider 分流设施，不代表 L2 本地模型已经加载或 L7 端到端切换完成。

### L3 离线影子回放器（规模 M）

**只有 `Local-static` 由 `eval/` 程序化批量运行。** 教师侧判定不经程序化调用，而是人在场时用仓库内冻结的
prompt **经开发用 Codex（Sol）**生成，落成冻结标签文件供 L3 导入 —— **不走 Claude Code / Opus 5**，
那条入口只用于 M4 裁判，避免角色混用。这是订阅制入口边界的直接后果，
同时意味着**不为教师侧另开按量付费 API 入口**。

- 教师侧输入：导入 **L5a** 冻结的教师标签，按稳定语义身份与 `E_final` 对齐；
  每批必须带 Sol 模型标识与生成日期（字段合同见 `doc/eval-data-layout.md` §4）。
- 本地侧：批量读取 `E_final` 喂给 `Local-static`，记录判定、理由、耗时、token 与显存峰值。
- 与正式耗时测评完全解耦，不在线运行。
- 结果写入方向 0 的统一结果库（共用 schema）；教师侧的行必须标记为**导入**，不冒充自动运行产物。
- 产出：本地模型**未微调** baseline 相对教师标签的首版对比数据。
- **L3 不是里程碑**：Local M3 由真实本地审批闭环认定（见下文），L3 只提供数据。
- **顺序依赖**：L3 的教师侧输入依赖 L5a，因此 **L5a 先于 L3**；L5b 合成训练数据仍在 L3/L4 之后。

### L4 审批质量指标（规模 S）

固定一组指标口径，**在第一次正式 M4 横评前定死并写进模板，后续轮次只填数不改口径**：

- 未微调 Local、微调后 Local 各自与 **Sol 教师标签**的总体一致率（称“教师一致率”）。
- 按 **Opus 裁判结果**分开的两个数：该拒绝却批准（**漏放**）、该批准却拒绝（**误拦**）。
  只有相对独立裁判结果时才使用这两个质量名称；单纯相对 Sol 教师标签的差异只称“教师不一致”，不叫漏放/误拦。
- 工程可用性指标，与判断质量分开报告：结构化输出解析失败率、超时与 fail-closed 触发次数、
  单次审批 token 成本、P50/P95 延迟、本地侧显存峰值。
- 微调后 Local 与未微调底模的差值 —— 判断“这轮微调有没有用”的直接依据。

**不设“一致率 ≥ X%”这类机械门槛**，也不需要另建人工标注 ground truth 集；教师标签的性质见上文角色分工。

### L5 教师标签与合成训练数据管线（规模 M）

L5 分两部分，**执行时点不同**：

| 部分 | 内容 | 时点 |
|---|---|---|
| L5a 教师标签生成 | 用冻结 prompt 人在场经开发用 Codex 生成 Sol 判定，落成冻结标签文件 | **先于 L3**（L3 的教师侧输入） |
| L5b 合成训练数据 | 基于 `seed` 分区批量合成训练样本 | L3/L4 之后、L6 之前 |

- 两部分都用**订阅制 Sol 经开发用 Codex 生成**，人在场、发送预写 prompt，不依赖真实跑批规模，
  也不占 API 预算门；`eval/` 只导入冻结产物，不程序化调用。
- L5a 覆盖 L3/L4 要回放的那批 `E_final`，**含 `holdout`**——按下表，为评测生成教师标签属允许用途。
  `seed`/`holdout` 切分先于 L5a 与 L5b 完成。

**真实 `E_final` 必须先做互斥切分，再谈用途。** 让同一批真实证据既当合成模板又当评测集，即使原文没进训练集，
基于评测样本生成训练数据仍是信息泄漏。因此：

| 分区 | 允许用途 | 禁止 |
|---|---|---|
| `seed` | 给合成器做格式与难度模板（几十条足够） | —— |
| `holdout` | 只用于**评测**：L3/L4 对比、M4 锚点，以及为这两者生成教师标签或裁判判定 | 进入 **L5b 合成上下文、合成 prompt 或合成期人工参考**；进入训练集 |

**禁令的范围是合成/训练，不是评测。** 把 holdout 证据放进评测用的标签生成 prompt 或 M4 裁判 prompt 是
允许且必要的 —— 没有教师标签就无法评测。被禁止的是它以任何形式影响训练样本的构造：
合成器的上下文、合成 prompt、以及人在做合成时对 holdout 的参考。

- 切分键必须是**跨运行稳定的语义身份**：`sha256(task_id + 规范化待审批动作指纹)`，无 task_id 时退化为
  动作指纹本身。不能用 `review_id`——`new_guardian_review_id`（`core/src/guardian/review.rs`）每轮生成新的
  UUID v4，互斥就只对文件实例成立、对语义样本不成立。
- 切分不按人工挑选，避免选择偏差；切分结果写入清单并冻结，后续增量按同一规则划分，不重划历史。
- **近重复检查**：合成产出的训练样本对 `holdout` 做一次近重复检测（n-gram Jaccard 或 MinHash 即可），
  命中阈值的样本剔除并记录数量。
- 合成要覆盖的分布：明确安全、明确危险、边界模糊、证据不足、伪装成安全的危险动作、工具结果与请求不一致。
- 产出：训练集 JSONL + 数据卡（Sol 模型标识与生成日期、合成方法、seed 分区来源、分布、去重与近重复检查结果、
  SHA256）。

### L6 微调回路（规模 L，三重授权门）

**路线：LoRA，训练在云 GPU 上进行。** 本地开发机为 RTX 4060 Laptop（8 GB 显存），8B 模型在 4k 序列下做
4-bit QLoRA 已经很勉强，8k 基本不现实；训练放本地会把上下文长度这个实验变量卡死在硬件上。

这条决定使 L6 落在 `doc/WBS.md` §6 的多个授权门之下，**必须作为独立任务单独申请**，不能顺带执行：

1. 云 GPU 训练本身（产生外部费用）；
2. **训练数据外发** —— Sol 生成的合成标签要上传到云端；即便都是本项目自造数据，也属于真实数据外发；
3. 权重下载回本地。

因此推进顺序为：**先在本地用极小样本跑通 LoRA 训练脚本与数据格式**（不求收敛，只验证管线），
再一次性申请云端正式训练的预算与数据外发范围。

- **推理仍在本地**：训练产出的 LoRA adapter 或由其生成的合并/量化工件必须能由本地 llama.cpp runtime 加载，
  **训练侧的量化、转换与格式选择必须以本地推理可落地为约束**，不能训完才发现用不了。
- **训练前后可比性**：两份 Local 工件必须来自同一底模谱系，并固定相同 runtime、prompt、采样和结构化输出条件。
  最终采用 adapter on/off 还是从同一训练谱系生成成对 GGUF，由 L6 实施计划按本地 runtime 兼容性决定；
  本页不预先写死，也不把当前部署用 GGUF 直接当作训练效果归因工件。
- **轮次封顶：正式训练最多 2—3 轮**，之后必须明确三选一 —— **采用 / 保留为实验 / 停止**。
  不允许无限微调下去，也不扩成生产验收。

仓库边界按数据体量决定（L5b 出数后立即确认）：

| 条件 | 处置 |
|---|---|
| 训练集总量 ≤ 100MB 且单文件 ≤ 40MB | 数据集与训练脚手架一起放仓库内独立板块 |
| 超过上述阈值 | 仓库只留训练脚手架 + 数据卡 + SHA256，数据集放仓库外 |
| 模型权重（GGUF / LoRA adapter） | **始终**在仓库外，无论大小 |

- 目录形态：新增顶层 `training/`（脚手架、数据卡、模型版本登记表），与 `mydev/`、`multidev/` 严格隔离，
  不参与 Rust 构建。落地时需同步更新 `AGENTS.md` 的仓库边界一节。
- 仓库内必须留下的最小可复现信息：超参、基座模型与版本、数据卡、产出权重的哈希与对应横评结果。

### L7 一键切换与端到端可用性（规模 S，依赖 L2a）

- 通过 **S1（模型/effort）+ L2a（provider）** 两个配置项把 Guardian 审批切到本地模型，验证端到端可正常审批。
  **仅有 S1 做不到这件事**。
- 仅在非严格耗时场景验证；正式耗时测评仍按核心设计走云端 `Guardian-live`。
- 验收：切换只改配置，不改代码；切回云端模型行为与性能无残留影响。
- **L7 不单独构成里程碑**：它的配置切换验收并入 Local M3，因此归在 P2 而非 P3。

## 里程碑口径

### Local M3 —— 工程闭环（工程验收）

4k model-backed、结构化输出、真实 `E_final`、错误 fail-closed，以及**仅通过配置**在 cloud/local Guardian
之间切换，共同形成真实本地审批闭环。用功能与失败语义验收，**不继承公平比较设施的 `σ`/`delta` 判据**。
8k 是后续独立验证项，失败不否定 4k 可用结论。

### L5/L6 前置 dry-run —— 不是里程碑

训练前用约 **5—10 条**样本排查：标签与审批场景是否清楚、Sol 教师输出是否适合作为训练目标、
未微调 Local 能否稳定输出规定结构，以及 Opus 判定标准与产物格式是否可操作。
它**不保存一套正式分数**，也不构成里程碑，更不是“训练前的一次完整横评”。

### Local M4 —— 人判定

在同一批冻结样本上正式比较**三方：Sol、微调后 Local、未微调 Local**。
加入未微调 Local 是为了把“微调带来多少增益”与“底模本身有多少能力”拆开；训练完成后同场运行即可，
无需训练前重复做一次完整横评。不设质量机械阈值，由人根据冻结对比结果作**采用 / 保留为实验 / 停止**决定。

**规模**：单批 ≤100 条，共 2—3 批。单批控制在一次会话内可完成的量，避免长尾判定标准漂移；
批与批之间可换 prompt 版本或数据切片。

**裁判 prompt 冻结**：裁判 prompt 与判定标准**预先设计成仓库内的版本化文件**
（放 `eval/templates/cross-eval-judge/`，与既有 `eval/templates/local-approval/` 并列），
使用时由人直接复制发送，不在会话里即兴撰写。每批 JSONL 记录所用 prompt 文件的版本标识与内容哈希。
理由：会话内即兴写 prompt 会让“标准”随批次漂移，而这恰是本方案唯一不可复现的环节；
prompt 是少数能被完全冻结的部分，必须冻死。
三个被评方必须收到**同一份证据、同一 prompt**；裁判看到的三份输出必须**匿名化且顺序随机**，
否则“哪个是 Sol”这一信息本身就会影响判定。

**证据来源：合成证据做主体，真实 `E_final` 做锚点，两组分开记录、不混算。**

- 现实约束：全项目目前只有 **47 条真实 `E_final`**（分布在 24 个 run 目录，内容互异），
  其中目前只有 **24 条被冻结本地运行时接受过计数请求**（见上文；兼容工作后可能变化），锚点规模按实际可用条数计而不是 47；
  按稳定语义哈希规则预估切分后 holdout 约 20 条；**实际数量必须以尚待生成的冻结 manifest 为准**。
  无论最终数量多少，它都撑不起 200—300 条的判定规模，且这 47 条全部来自 TB 2.1 任务运行，审批情境单一。
- 因此主体横评用 Sol 批量生成的**合成审批场景**，覆盖面由构造决定，规模可控。
- 真实 holdout 单独报一组数作为 **sanity anchor** —— 用途是发现“合成场景与真实分布严重脱节”，
  不用于比较三方强弱。真实证据的 `seed`/`holdout` 切分仍按 L5 的稳定语义哈希规则，不另立一套；
  真实证据不得进训练集这条不变。

**两条必须写进合同的现实限制**：

1. **不可完全复现**。订阅侧模型版本不由本项目冻结，可能随时间变化。判定时必须记录 Claude 模型版本与
   判定日期，并把该批结果标注为“该时点判定”，不假装可重跑复现。
2. **不自动归档**。会话内判定不满足测评体系“自动运行、自动记录、自动归档”的默认要求，
   因此必须约定固定产物格式：每批判定输出一份**冻结 JSONL**，含证据哈希、prompt 版本、各被评方输出、
   裁判结论与理由，落到 `eval-data/` 下的独立命名空间。

## 与方向 0 的接口

- 消费：P0-S2 产出的规范化 `E_final`。
- 复用：方向 0 的结果库 schema、归档脚本与产品身份字段。
- 反馈：L4 的审批失败归因回流到方向 0 的 B5 失败归因分类。
- 不消费公平比较设施的 `σ`/`delta` 判据：Local M3/M4 都不继承那套机械门。

## 硬约束

- 各 static 组的**规范化逻辑 payload** 必须逐字节一致，不得任何一方多拿信息（provider URL / headers / 认证除外）。
- 静态影子一律不给模型工具与自主取证能力；runner 访问推理端点不受此限。
- 真实证据包不进训练集；`holdout` 分区不得进入合成上下文、合成 prompt 或合成期人工参考。
  为评测生成教师标签与裁判判定不受此限（见 L5 分区表）。
- 权重文件不进仓库。
- 严格耗时测评期间不在线跑本地模型。
- 一键切换不得以弱化审批逻辑为代价换取通过率。
- 把证据包或合成数据发给云端属于**数据外发**，须单独授权；首次外发前人工抽查一批样本，
  确认没有明显不应外传的内容。订阅制入口不额外计费，但不豁免数据外发门。
- 订阅制入口（Sol、Opus 5）只用于人在场监督的会话内工作，不作为程序化批量后端接进 `eval/`；
  每批必须记录所用模型标识与日期。
