# Plan 015：本地审批模型工程调研与 GGUF 冻结

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

## 1. 目标

### 最终目标

在不下载任何模型权重、不加载模型、不使用 GPU 的前提下，对 README 已冻结的
`mistralai/Ministral-3-8B-Instruct-2512` 完成日期冻结的模型工程调查；基于官方原始资产、官方量化资产、
主要可信社区 GGUF、llama.cpp `b10333` 与 RTX 4060 Laptop 8GB 约束，冻结一个未微调本地审批基线 GGUF，
使任务达到 `download_ready_blocked_on_user_approval`，并提供后续单文件下载、哈希验证、配置与 GPU smoke 的
精确恢复入口。

### 完成/验收标准

- 形成一份位于 `doc/audit-snapshots/` 的日期冻结模型工程档案，明确区分官方事实、社区声明、工程推算与待实测项。
- 实际调查基础模型官方仓库、官方命名空间内现有量化资产和主要社区 GGUF；比较来源链、base revision、转换工具、
  量化方法、imatrix、文件大小、维护证据、许可证与 llama.cpp 兼容性，不以下载量或作者名替代证据。
- 档案覆盖模型架构、参数、原生精度、上下文、tokenizer、chat template、推荐推理设置、结构化输出注意事项、
  原始权重组成/体积、是否需要原始 safetensors、视觉 projector/mmproj 边界。
- 对 Q4_K_M 及至少两个合理相邻档位给出 8GB 显存下的权重、KV cache、上下文和运行余量工程核算；所有未运行结论
  均标为估算或待实测。
- 冻结唯一推荐 GGUF 的 repo、40 位 commit revision、精确文件名、量化规格、Hub 文件大小、目标路径，完成精确
  `hf download --dry-run`，给出单并发下载命令和 SHA-256 验证方案。
- 实际测试 Hugging Face MCP 与用户级 `hf` CLI 1.27.0；MCP 若不可用，保留可复核错误并说明 CLI 覆盖边界；
  CLI 验证账户状态时不得读取或输出 token。
- 核算下载新增占用、目标目录、Windows `C:` 盘实际余量、Docker/canary/本地模型进程状态与 I/O 风险；瞬时空闲
  不得视为稳定窗口。
- 给出 `rondo.local.toml` 的非密钥配置方案与下载后恢复步骤，并说明未微调基线与未来微调后量化的公平可比合同。
- 运行必要的轻量文档/一致性/Git 大文件检查；不运行 Docker、Cargo、Bazel、模型服务、GPU 或完整测试。
- 未获单独下载授权时，计划状态精确停在 `download_ready_blocked_on_user_approval`；已完成的研究文档可提交、合并
  本地 `main` 并推送 `origin/main`，但不得表述为权重或 model-backed 验收完成。

## 2. 范围

### 允许修改

- `plan/015-local-approval-model-engineering-freeze-execplan.md`
- `doc/audit-snapshots/` 下本任务日期冻结档案
- `doc/WBS/local-approval-model.md` 中受本任务影响的简洁当前事实
- `agent_log/` 下本任务精炼执行日志
- 仅当现有合同不能表达冻结结果时，最小修改 `rondo.local.example.toml`；机器实际配置只给出方案，不在下载前写入

### 不允许修改

- README 已冻结的基础模型选择
- `mydev/`、`eval/` 的功能代码、测试、运行时 lock 与 llama.cpp `b10333` 固定版本
- canary worktree、campaign、结果、paid profile、共享 eval 运行状态及任何来源不明的现有修改
- Hugging Face 远端仓库、Jobs、Endpoint、Space、Collection 或其他远端状态
- 任何 GGUF、safetensors、adapter、mmproj 或其他权重资产（下载审批前）

### 不允许读取/查看

- `.env.local` 的内容
- HF token 的明文、长度、前后缀或哈希
- holdout 内容、私有测评数据和与本任务无关的个人文件

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过检查或提前推进而违反。

1. 基础模型固定为 `mistralai/Ministral-3-8B-Instruct-2512`，本任务不重新选型。
2. 当前一次性授权只含只读调研、小型元数据、精确 dry-run、资源核算、文档与 Git 交付；实际权重下载必须另获用户对
   唯一 repo/revision/file 的明确授权。
3. 不通过下载权重来比较候选；`hf download --dry-run` 必须保持 dry-run，不得因缓存命中或工具行为落地权重。
4. 不加载模型、不启动 llama.cpp、不执行 model-backed 请求、不使用 GPU，不运行或拉取 Docker，不运行重型构建/测试。
5. HF MCP 的“已配置”“当前会话可见”“调用成功”分开记录；失败时不得假装使用成功。
6. repo revision 必须冻结为可复核的 40 位 commit；文件大小优先使用 Hub/LFS 元数据和 CLI dry-run 交叉验证。
7. 官方原始模型、官方量化、社区转换分别建立来源链；转换者声明若没有转换脚本、commit 或可复核元数据，应降低
   可复现性评级而不是补全猜测。
8. 纯文本审批不得下载不需要的视觉 projector/mmproj；是否可省略必须由模型架构、GGUF 组成和 llama.cpp 行为证据支持。
9. 显存、KV 与上下文只做保守工程估算，明确公式和假设；CUDA/model-backed 兼容、速度、峰值显存、最大安全上下文、
   structured output 服从真实 GPU 验收结果。
10. 下载准备检查只能报告当时快照；canary 调度者未明确保证窗口期间不会启动任务时，状态仍阻塞。
11. 即使获得下载授权，下载前也必须重新核对唯一对象、canary 稳定窗口、Docker/本地模型进程和 Windows `C:` 余量；
    任一不满足即停止。下载完成后仍不得加载模型或使用 GPU。
12. Git 中不得出现模型权重、adapter、原始权重、意外大文件、凭据或本机私有配置。

## 4. 软性建议

以下内容用于根据现有仓库给出的执行建议，但不是固定结论。AI 可依据实际证据采用更优方案。

- 先以 HF MCP 做语义发现和关联仓库扩展，再以 `hf models`、Hub API/LFS 元数据和官方资料固定精确事实。
- 候选比较至少覆盖官方命名空间与若干能解释转换链的社区仓库；用一张统一证据表避免把热度误当质量。
- 优先选择单文件、Q4_K_M 或资源/质量更合适的相邻量化；最终来源不在计划阶段预设为官方或社区。
- 让未微调与未来微调后模型尽量采用同一 llama.cpp build、GGUF conversion commit、量化算法、imatrix 策略、
  tokenizer/chat template 和推理参数；无法同一化的差异必须作为实验变量记录。
- 日期冻结档案保存权威链接、查询日期、commit、文件清单摘要与复现命令，普通工具流水仅写入临时笔记，不堆进 WBS。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-12：读取根规则、README、当前 WBS、方向 2 WBS、数据布局、开发环境、配置合同与 Plan 模板。
- 2026-08-12：确认主工作区 `main...origin/main` 干净；发现并保护
  `.claude/worktrees/0811-p2-b7-results` 中未提交的 `eval/results/runs.jsonl`，其余既有 worktree 未修改。
- 2026-08-12：创建独立 worktree `.claude/worktrees/0812-local-model-engineering`，分支
  `0812-local-model-engineering`。
- 2026-08-12：当前会话可见 Hugging Face MCP 工具；首次 `hf_whoami` 与两次 `model_search` 实际调用均返回
  MCP `-32603 Internal error`，`hub_repo_details` 和单项重试也失败。MCP 已实际测试但不可用，不能称成功验收。
- 2026-08-12：用户级 `hf` CLI 1.27.0 的登录状态、模型搜索、精确 revision、递归文件/LFS 元数据和 dry-run 均成功；
  验证中没有读取或记录 token。
- 2026-08-12：完成官方原始/量化资产与 Bartowski、Unsloth、LM Studio、mradermacher、ggml-org GGUF 的统一
  来源链比较；官方命名空间没有第二个 8B Instruct 2512 GGUF repo。
- 2026-08-12：冻结 `bartowski/mistralai_Ministral-3-8B-Instruct-2512-GGUF` revision
  `ad82bf81321f4b22de70014ecd5135730115f6a8` 的
  `mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf`，精确 5,198,387,456 bytes，LFS SHA-256
  `7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a`。
- 2026-08-12：最终候选与官方 Q4_K_M 的 exact-revision `hf download --dry-run` 均成功；未下载权重。
- 2026-08-12：完成 8GB/F16 KV 核算、目标路径/哈希/配置/恢复方案和主机资源快照。资源复查在瞬时空闲后数秒即发现
  P2 B7 canary 容器运行，证明当前没有稳定下载窗口。
- 2026-08-12：形成日期冻结档案
  `doc/audit-snapshots/2026-08-12-ministral-3-8b-instruct-2512-gguf-freeze.md`。
- 2026-08-12：独立终审复核最终 Bartowski 对象、官方对照、KV 算法、MCP/CLI、b10333/mmproj 和审批边界，无阻塞
  finding；已按审查意见澄清 TOML 仅为差异片段、`context_size = 0`/fit 语义和社区来源声明口径。

### 当前工作

- 等待用户对已冻结唯一 GGUF 的单独下载授权；研究和下载准备阶段没有其他待执行项。

### 后续计划

- 当前阶段：轻量一致性检查后提交研究成果，合并/推送 `main`，集中报告唯一对象与资源状态。
- 获明确授权后：在保留的独立 worktree 恢复，先重新核对 canary 稳定窗口、Docker/模型进程、Windows `C:` 余量与
  批准对象；只下载唯一文件，验证 exact bytes/SHA 并更新 ignored `rondo.local.toml`。
- 下载完成后仍不加载模型或使用 GPU；CUDA/model-backed smoke、上下文扫描与未微调 M3 baseline 另行验收。

### 阻塞项

- 权重下载未授权；在研究和 dry-run 完成后必须转为
  `download_ready_blocked_on_user_approval`，这不是技术失败。
- canary 由另一会话调度；当前没有调度者对稳定下载窗口的明确保证。

### 当前验收状态

- `download_ready_blocked_on_user_approval`：模型工程调查、唯一候选冻结、精确 dry-run、磁盘/资源核算和下载方案已完成；
  没有下载、加载或验收任何模型权重。当前阻塞是预期审批门，不是技术失败。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 下载审批前把任务终态定义为 `download_ready_blocked_on_user_approval` | 用户明确把实际权重下载设为独立授权门；研究成果仍可独立验收和交付 | Plan、档案、日志、交付措辞 | 已采纳 |
| 002 | 最终 GGUF 来源在证据比较后决定，不预设官方或社区 | 官方与社区资产的转换、量化、imatrix、兼容和可复现性可能不同 | 候选调查与最终冻结 | 已采纳 |
| 003 | MCP 可见性与成功调用分开验收 | 当前工具已加载但首次服务调用为 `-32603`，不能把配置/可见性当成功使用 | 工具使用记录与降级方案 | 已采纳 |
| 004 | 不修改或读取 canary results worktree | 其中存在并行会话的未提交结果；本任务只做模型工程准备 | worktree 与资源检查 | 已采纳 |
| 005 | 唯一基线冻结为 Bartowski `Q4_K_M` revision `ad82bf…` | 相比官方同档，它披露 BF16 来源、llama.cpp b7229、imatrix 和校准来源；精确 revision/LFS SHA 约束社区工件身份。官方转换方法与 imatrix 未披露，两者模板均旧于当前主仓，不能只按官方身份决策 | 下载对象、量化、档案与后续配置 | 已采纳 |
| 006 | 8GB 首次验收从 8192 context、F16 K/V、单并发开始 | Q4 权重 4.841 GiB，8k F16 KV 估算 1.063 GiB；需给 CUDA/graph/scratch/桌面留余量，262k 模型上限不适合作为本机默认值 | 后续 `rondo.local.toml` 与 GPU smoke | 已采纳 |
| 007 | Phase A 调研成果现在交付，Phase B 下载继续由本计划的条件分支恢复 | 当前可验收成果不依赖权重；下载授权和稳定 canary 窗口仍是硬门，保留 worktree 可避免丢失精确恢复入口 | Git 交付与 worktree 生命周期 | 已采纳 |
