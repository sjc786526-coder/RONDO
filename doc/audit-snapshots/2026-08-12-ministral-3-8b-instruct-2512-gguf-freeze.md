# Ministral 3 8B Instruct 2512 本地 GGUF 工程冻结（2026-08-12）

本快照为 RONDO 纯文本审批基线冻结模型工程事实。基础模型已经由 README 固定为
`mistralai/Ministral-3-8B-Instruct-2512`，本文不重新选型。本次只完成只读调查、小型元数据查询、
`hf download --dry-run`、资源核算和下载方案；**未下载权重、未加载模型、未启动 llama.cpp、未使用 GPU**。

当前状态：`download_ready_blocked_on_user_approval`。实际下载必须取得用户对本文唯一文件的明确授权，并在下载前重新通过
canary 稳定窗口、Docker/本地模型进程、Windows `C:` 余量和对象一致性检查。

## 1. 证据口径与冻结结论

本文用以下标签区分证据，避免把估算写成验收结果：

- **官方事实**：模型作者、Hugging Face Hub 或 llama.cpp 在冻结 revision/tag 上公开的资料和文件元数据。
- **社区声明**：社区转换仓的模型卡、文件元数据或提交历史；不自动等同于可独立重放的转换证明。
- **工程推算**：依据架构、文件大小和运行参数进行的计算或取舍，尚未在本机 model-backed 实测。
- **待实测**：必须由 RTX 4060 Laptop 8GB、项目固定 llama.cpp `b10333` 和精确 GGUF 完成的后续验收。

唯一冻结对象：

| 字段 | 冻结值 |
|---|---|
| repo | `bartowski/mistralai_Ministral-3-8B-Instruct-2512-GGUF` |
| revision | `ad82bf81321f4b22de70014ecd5135730115f6a8` |
| file | `mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf` |
| quantization | `Q4_K_M`，社区声明为 imatrix 量化 |
| exact size | `5,198,387,456` bytes（5.198 GB / 4.841 GiB） |
| LFS content SHA-256 | `7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a` |
| target | `/home/sjc/desktop/RONDO/eval-data/models/mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf` |
| state | dry-run 已通过；文件尚不存在，等待单独下载授权 |

**工程决策**：Q4_K_M 在 8 GiB 显存中比 Q5_K_M 留出约 0.80 GiB 更多权重外余量，又避免 Q3_K_M 更明显的
质量损失成为审批基线的额外变量。Bartowski 相比官方同档量化披露了 BF16 来源、llama.cpp `b7229`、imatrix 及校准来源，
更适合冻结训练前基线的量化来源链；官方文件仍作为身份更短但转换过程不透明的主要对照。精确 revision、字节数和 LFS
内容哈希约束了最终工件身份，不以作者名或下载量替代完整性验证。

这项选择**不证明** Bartowski 的量化质量一定高于官方，也不证明精确文件已能由 `b10333` CUDA 加载。二者都必须在后续
model-backed 任务中实测。

## 2. Hugging Face MCP 与 hf CLI

### 2.1 当前会话实际结果

- HF MCP 工具在当前会话已加载且可见。实际调用了 `hf_whoami`、`hub_repo_details` 和 `model_search`；并行请求返回
  `Mcp error -32603: Internal error`，单项重试返回连接失败。因此结论是“已实际测试但服务不可用”，不是 MCP 验收通过。
- 独立用户级 `hf` CLI 为 `1.27.0`。`hf auth whoami --format json` 成功确认已登录；验证过程没有读取或记录 token。
- CLI 成功完成模型搜索、精确 revision、递归文件清单、LFS 内容哈希、模型卡和两个精确文件 dry-run。Hub CLI 是本次冻结
  精确资产事实的主入口；MCP 的语义发现能力因服务故障未得到成功调用证据。

### 2.2 适用边界

- MCP 适合语义搜索、关联资产发现和 repo 概览，但只有真实成功响应才算使用通过。
- `hf models` 适合冻结 repo commit、gated/private 状态、siblings、GGUF/safetensors 元数据；`hf download --dry-run`
  适合在不获取权重的前提下复核精确文件选择和显示大小。
- CLI 的 `--dry-run`、Hub/LFS 元数据和理论显存计算都不是文件下载、文件哈希实算或模型加载验收。

## 3. 官方模型与原始权重

### 3.1 仓库、许可与 revision

截至 2026-08-12 的官方资产：

| 用途 | repo | frozen revision | gated | license / 说明 |
|---|---|---|---|---|
| README 固定的 Instruct FP8 checkpoint | `mistralai/Ministral-3-8B-Instruct-2512` | `5b26027e7b19eeb4b7352e1fed3926375dd2cb4d` | false | Apache-2.0；混合 FP8/BF16 |
| 标准 Instruct BF16 checkpoint | `mistralai/Ministral-3-8B-Instruct-2512-BF16` | `f6fae9795746f63c9be8344932f01275f3c63734` | false | Apache-2.0 |
| 官方 GGUF | `mistralai/Ministral-3-8B-Instruct-2512-GGUF` | `0102285ad796bd99af90f58de616092e5630e970` | false | Apache-2.0 |
| 预训练祖先（不是本任务 Instruct checkpoint） | `mistralai/Ministral-3-8B-Base-2512` | `d4883f9b36aa2e5d775730d3fdba3d30de51a8ef` | false | Apache-2.0；BF16 |

官方 Additional Checkpoints collection 和 `mistralai` 命名空间精确名称搜索只发现上述与 8B Instruct 2512 相关的一个
官方 GGUF repo，没有遗漏第二个官方 8B Instruct GGUF 仓库。

### 3.2 架构、精度和上下文

以下为官方 config/model card 与 Hub 元数据事实：

- dense multimodal Mistral3/Pixtral-style 模型：约 8.4B language model 加 0.4B vision encoder。
- text：34 层、hidden size 4096、intermediate size 14336、32 attention heads、8 KV heads、head dim 128、
  vocab 131072；无 sliding window。
- 最大位置数 262,144；YaRN factor 16，original max positions 16,384，RoPE theta 1,000,000。
- vision：24 层、hidden size 1024、16 heads、image size 1540、patch size 14、spatial merge size 2。
- BF16 仓 Hub 统计总参数 `8,918,026,240`。FP8 主仓并非全 FP8：`7,415,529,472` 个 F8_E4M3 参数、
  `1,502,496,768` 个 BF16 参数；vision tower、multimodal projector 和 `lm_head` 没有转为 FP8。

262k 是模型声明上限，不是 8GB 显存可用上下文。仅 F16 KV 的工程估算在 256k 已约 34 GiB，不能作为本机默认值。

### 3.3 tokenizer、chat template 与推荐推理设置

- 官方模型包含 `tekken.json` 与 `tokenizer.json`，模型卡要求 `mistral-common >= 1.8.6`。
- BOS `<s>` 为 id 1，EOS `</s>` 为 id 2，PAD `<pad>` 为 id 11。原生模板使用 `[SYSTEM_PROMPT]`、
  `[INST]`、`[AVAILABLE_TOOLS]`、`[TOOL_CALLS]`、`[ARGS]`、`[TOOL_RESULTS]`、`[IMG]` 等标记。
- 官方面向 production/daily-driver 建议 temperature 小于 0.1、清晰 system prompt、尽量缩小工具集合。RONDO
  冻结方案使用 temperature `0.0`、top-p `1.0`、seed `42`、单并发。
- 官方 vLLM 路径要求 vLLM `>=0.12.0` 和 mistral-common `>=1.8.6`；这是 vLLM 建议，不能直接当作
  llama.cpp `b10333` 的验收证据。

官方 Instruct/BF16 仓在 2026-06-30 修改 stray `[THINK]` special tokens，又在 2026-07-15 更新 chat template 以匹配
mistral-common。官方 GGUF binary 自 2025-12-02 上传后未更新，其内嵌模板结构较旧；主要社区 GGUF 同样在 2025-12
转换，也没有新模板同步证据。未来验收必须记录 GGUF 内嵌模板和实际请求渲染，不能以当前主仓模板替代工件事实。

### 3.4 JSON/结构化审批输出

官方模型卡声明 native function calling 和 JSON outputting，Mistral 托管服务文档另有 Structured Outputs。官方已知限制明确：
JSON mode 只保证合法 JSON，不保证给定 schema；具体 schema 应使用 function calling/structured mechanism。

对 RONDO 的工程含义是：本地 llama.cpp 可用 grammar/schema 约束语法，但模型能力声明和托管 API 保证不能外推为本地 GGUF
已经通过审批结构化输出验收。RONDO 仍需 fail-closed 地做 JSON 解析、JSON Schema、枚举、字段和审批业务语义校验；grammar
不是业务正确性证明。真实 `E_final` 输出保持 `not_run`。

### 3.5 原始 safetensors 组成和是否需要下载

FP8 主仓提供同一 checkpoint 的两种替代序列化，不应同时下载：

| 形式 | bytes | 说明 |
|---|---:|---|
| `consolidated.safetensors` | 10,420,633,176 | 9.705 GiB；LFS SHA-256 `ab5e41c341ac8331e653f572218e6bf29082b2360c0207c1f84d9a3c963b27fe` |
| 3 个 `model-*` shards | 10,420,654,824 | 另有 103,195-byte index；与 consolidated 是替代关系 |

BF16 仓也为替代序列化：consolidated `17,836,115,976` bytes（16.611 GiB），4 shards 合计
`17,836,123,192` bytes，另有 index。Hub 的整仓 used-storage 会把替代序列化重复计入，不是一次合理下载量。

本地未微调 llama.cpp baseline 只需运行已冻结 GGUF，不需要下载 FP8/BF16 safetensors。未来云端训练、合并或把训练前后模型
按同一新管线重新转换时，BF16 源权重可能需要单独授权；本任务不下载任何原始权重。

## 4. 官方 GGUF 调查

官方 GGUF revision `0102285ad796bd99af90f58de616092e5630e970` 的完整权重清单：

| 文件 | bytes / GiB | LFS content SHA-256 |
|---|---:|---|
| `Ministral-3-8B-Instruct-2512-Q4_K_M.gguf` | 5,198,911,904 / 4.842 | `33e7a72cf5e6e2cfc2f2847075acc013d68bba023e35310cef86b5cf8fdca761` |
| `Ministral-3-8B-Instruct-2512-Q5_K_M.gguf` | 6,059,268,512 / 5.643 | `7a5454127ec772e2389f0e71a77fedb88b83d4366d8a69facd0cfd0898f04d35` |
| `Ministral-3-8B-Instruct-2512-Q8_0.gguf` | 9,029,392,800 / 8.409 | `bd0ca58473b64618df4d08c1410cc25c910ca84e647833ebaf099e0fc0523b45` |
| `Ministral-3-8B-Instruct-2512-BF16.gguf` | 16,988,084,640 / 15.821 | `fa785e6a56f240dacbc451ea4aaab501d11f5903005903cec6e0ba11c30e3357` |
| `Ministral-3-8B-Instruct-2512-BF16-mmproj.gguf` | 858,283,168 / 0.799 | `e799380f596d152ff4026a72d409ecc89c96cd437676804bc3f2ab3bd6b486ec` |

Hub 能解析其 GGUF metadata：architecture `mistral3`、text parameter count `8,489,553,920`、context
262,144 且有内嵌 chat template。这是当前 GGUF 格式级证据，不是项目固定 `b10333` 的 CUDA 加载证据。

官方来源身份最强：Mistral 命名空间、官方 collection、repo metadata 指向原 Instruct 模型。但公开 model card/commit history
没有披露 converter 或 llama.cpp commit、quantize command、校准数据、imatrix 使用情况、是否 re-quant，也没有给出精确上游
base revision。GGUF binary 的提交 `65457cc28fafb2210c8fb885a068b107e8d7fab3` 只是 large-folder upload；公开历史不足以重放
`exact source revision -> conversion -> quantization`。`Q4_K_M` 中的 `M` 是 llama.cpp mixed quant type 名称，不代表必然使用
imatrix，因此官方 imatrix 状态只能记为 **undisclosed**。

## 5. 主要社区 GGUF 比较

下表 revision 和大小均由 2026-08-12 Hub/CLI 元数据冻结；“来源/方法”仅表示该仓公开证据。
表内候选均为 public、非 gated，模型卡/Hub tag 标示 Apache-2.0。

| repo / revision | Q4_K_M 精确文件 | bytes | 来源与转换披露 | imatrix / 复现性评价 |
|---|---|---:|---|---|
| **Bartowski** `bartowski/mistralai_Ministral-3-8B-Instruct-2512-GGUF` / `ad82bf81321f4b22de70014ecd5135730115f6a8` | `mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf` | 5,198,387,456 | 指向官方 BF16；声明 llama.cpp `b7229`；同时发布 BF16 GGUF 与 imatrix | 明确 all quants use imatrix，列出校准来源；未披露精确官方 BF16 commit 和完整 subset/命令，属于主要候选中最完整而非完全重放 |
| Unsloth `unsloth/Ministral-3-8B-Instruct-2512-GGUF` / `3731507ec3e867db16d620f73e14d689125758f4` | `Ministral-3-8B-Instruct-2512-Q4_K_M.gguf` | 5,198,386,720 | metadata 指向官方 FP8；仓内有 imatrix 和多档 quant；通用 Dynamic 2.0 说明不是该文件精确命令 | converter commit 和逐文件方法未披露；Q4_K_M 是否应用特定动态配方不宜补猜 |
| LM Studio Community `lmstudio-community/Ministral-3-8B-Instruct-2512-GGUF` / `03465d18062ad69116eced14a79a34c7856b6319` | `Ministral-3-8B-Instruct-2512-Q4_K_M.gguf` | 5,198,387,168 | 指向官方 BF16；声明 llama.cpp `b7231` | 没有 imatrix、校准数据或命令披露 |
| mradermacher static `mradermacher/Ministral-3-8B-Instruct-2512-BF16-GGUF` / `f06fd231c33d424e7d5841d6d40065779c36e41e` | `Ministral-3-8B-Instruct-2512-BF16.Q4_K_M.gguf` | 5,198,387,616 | 提供常规量化系列 | converter commit、命令和校准未披露 |
| mradermacher imatrix `mradermacher/Ministral-3-8B-Instruct-2512-BF16-i1-GGUF` / `5b7c4f2a2cdfba5e6d24afe8a4e1b416d47b3368` | `Ministral-3-8B-Instruct-2512-BF16.i1-Q4_K_M.gguf` | 5,198,387,904 | 明确 i1 系列 | converter commit、校准来源和完整命令未披露 |
| ggml-org `ggml-org/Ministral-3-8B-Instruct-2512-GGUF` / `711997ebd75d80288650bf86a91c80ac73a7e529` | 无 Q4_K_M；仅 Q8 language GGUF | 9,028,867,840（Q8） | 指向官方 BF16，说明 `convert_hf_to_gguf.py` | converter commit 未披露；Q8 本体已超过 8GiB，不能在本机全量显存容纳 |

Bartowski 的冻结 Q4 LFS SHA-256 为
`7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a`。其模型卡声明的 llama.cpp
`b7229` 对应 Git commit `682e6658bb8de53f56bfbf16efee98697db1b21f`；仓内 BF16 GGUF 为 `16,987,559,872`
bytes，imatrix 为 `5,328,672` bytes。公开校准来源缩短了方法链，但 subset 选择和完整命令仍不足，所以本文不写成“完整可重现”。

Bartowski 的相邻量化大小：

| 量化 | bytes | GiB | 工程定位 |
|---|---:|---:|---|
| Q3_K_M | 4,242,053,376 | 3.951 | 上下文余量更大，但质量损失风险更高 |
| IQ4_XS | 4,696,414,464 | 4.374 | 更小的 4-bit 候选，需单独质量兼容实测 |
| Q4_K_S | 4,954,102,016 | 4.614 | 比 Q4_K_M 略省显存，质量余量较弱 |
| **Q4_K_M** | **5,198,387,456** | **4.841** | 冻结基线 |
| Q4_K_L | 5,596,846,336 | 5.212 | 质量/占用更高，8GiB 余量变窄 |
| Q5_K_M | 6,058,744,064 | 5.643 | 质量更高但 8GiB 上下文与运行余量紧张 |
| Q6_K | 6,972,872,960 | 6.493 | 不适合本机保守全卸载基线 |
| Q8_0 | 9,028,868,352 | 8.409 | 文件本体已超过 8GiB |

### 5.1 官方与最终社区文件的实际差异

- 官方优势：作者命名空间、官方 collection、最短的发布身份链；风险是转换/量化方法和 imatrix 不透明。
- Bartowski 优势：公开 BF16 来源、量化器 release、imatrix 和校准来源，训练前后复用管线时可控变量更多；风险是多一层
  社区转换信任，且完整命令、精确 BF16 source commit 仍缺失。
- 两个 Q4_K_M 仅相差约 0.5 MiB，大小不构成实质选择依据；它们内容哈希不同，不能互换。
- 两者都早于 2026-07 官方 template 更新。选择 Bartowski 不是为了模板更新，而是为了量化来源可解释性。
- 精确 revision 与 LFS SHA 可验证“下载的是被冻结的社区工件”，不能验证社区声明的转换过程。后续真实质量横评仍需保持相同
  prompt/template/runtime 参数。

## 6. 纯文本边界与 mmproj

语言 GGUF 和约 0.799 GiB 的视觉 encoder/projector 是独立文件。llama.cpp multimodal 文档也把 LLM GGUF 与 projector
分开传入。RONDO 审批只接受纯文本 `E_final`，不向模型传入图片，因此本次只冻结 language GGUF，**不下载 mmproj**。

这是结构和文件拆分支持的工程判断，仍需后续在精确 `b10333` 上验证 language-only 启动。建议真实启动时使用本地
`--model` 且显式 `--no-mmproj`，使误入图像输入 fail-closed；当前 RONDO launcher 合同还没有暴露 `--no-mmproj`，本任务只记录
这一缺口，不修改运行时代码。

## 7. llama.cpp b10333 兼容性边界

项目冻结 llama.cpp `b10333`，Git commit `08659901c43b51de735740f1cf61bb82fbe0c4e4`。冻结源码中：

- 架构映射和模型分发包含 `MISTRAL3`；`src/models/mistral3.cpp` 有 Mistral3 graph，并把 34 层识别为 8B。
- conversion 代码注册 Mistral3；量化器保留标准 `Q4_K_M` 支持。
- Bartowski 使用的 `b7229` 早于 `b10333`。标准 GGUF/K-quant 在后续版本具有源码级读取路径，是有利兼容证据。

但仓库现有 lock 能力仍为 `cpu_only_no_model`，只验收了 CPU x64 frontend/runtime closure；没有 CUDA runtime，也没有让
`b10333` 实际解析或加载本文件。因此兼容结论精确表述为：**source/format-level supported, exact CUDA/model-backed not run**。

## 8. RTX 4060 Laptop 8GB 资源预算

### 8.1 KV 公式

在 34 layers、8 KV heads、head dim 128、K/V 都为 F16 且无 sliding window 时：

```text
KV bytes/token = 34 * 2(K,V) * 8 * 128 * 2 bytes = 139,264 bytes = 136 KiB
```

| context | F16 KV cache 工程估算 |
|---:|---:|
| 4,096 | 0.531 GiB |
| 8,192 | 1.063 GiB |
| 16,384 | 2.125 GiB |
| 32,768 | 4.250 GiB |
| 262,144 | 34.000 GiB |

这只计算理论 KV，不含 CUDA context、compute/graph/scratch buffer、allocator 碎片、桌面占用和输出增长。

### 8.2 权重加 F16 KV

| 量化 | weights | +4k KV | +8k KV | +16k KV | +32k KV |
|---|---:|---:|---:|---:|---:|
| Bartowski Q3_K_M | 3.951 GiB | 4.482 | 5.014 | 6.076 | 8.201 |
| **Bartowski Q4_K_M** | **4.841 GiB** | **5.372** | **5.904** | **6.966** | **9.091** |
| Bartowski Q5_K_M | 5.643 GiB | 6.174 | 6.706 | 7.768 | 9.893 |

**工程建议**：为 CUDA/图和桌面等保留约 1.5 GiB 的保守余量，初始固定 `Q4_K_M + 8192 context + F16 K/V +
parallel 1`。Q5_K_M 在 8k 时理论仅余约 1.29 GiB，偏紧；Q4_K_M 16k 也偏紧。KV 改为 Q8/Q4 可节省显存，但会引入新的
质量和兼容变量，不作为未微调首版基线。最终安全 context、全量 offload、显存峰值、共享内存回退和性能均为待实测。

### 8.3 后续建议启动参数（现在不得执行）

在 CUDA `b10333` 和模型另行验收时，以以下参数作为起点：

```bash
llama-server \
  --offline \
  --no-models-autoload \
  --no-ui \
  --model /home/sjc/desktop/RONDO/eval-data/models/mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf \
  --alias rondo-local-approval \
  --no-mmproj \
  --n-gpu-layers 99 \
  --split-mode none \
  --main-gpu 0 \
  --fit off \
  --ctx-size 8192 \
  --batch-size 512 \
  --ubatch-size 256 \
  --parallel 1 \
  --flash-attn on \
  --cache-type-k f16 \
  --cache-type-v f16 \
  --jinja \
  --host 127.0.0.1 \
  --port 8080
```

这里是参数建议，不是已运行命令。`rondo.local.toml` 当前能表达 context、GPU layers、flash attention 和 parallel，尚不能
表达 `--no-mmproj`、cache type、batch/ubatch、`--fit off`。RONDO 的 `context_size = 0` 会省略 `--ctx-size`，上下文由模型
元数据和 b10333 默认 fit 决定，可能从模型上限尝试后自动缩减，不能冻结确定的实验条件；本机首次验收必须显式改成 8192。
是否需要调整 launcher 参数合同属于后续 GPU smoke 任务。

## 9. 未微调与微调后量化可比性

训练前后比较必须区分“模型训练收益”和“量化/模板/运行时变化”：

1. 严格比较应固定同一 BF16 源谱系、tokenizer/chat template、llama.cpp conversion/quantization commit、量化类型、
   imatrix 数据与命令、context、KV type、prompt、seed、sampling 和结构化输出约束。
2. 本次 Bartowski 文件可作可部署的未微调基线；若未来无法精确取得/复用 Bartowski 的完整 b7229 命令和校准 subset，不能把
   它与另一条新量化管线的微调模型差异全部归因于训练。
3. 最干净的未来方案是：在微调产物完成后，用同一个重新冻结的新 llama.cpp commit、同一 imatrix 和同一命令，分别从未经
   微调 BF16 与微调合并 BF16 生成一对 GGUF，再重跑 baseline/finetuned。原始 Bartowski 结果保留为 deployment baseline。
4. tokenizer/template 修复、mmproj 是否存在、KV 量化、context 截断或 runtime build 变化都可能污染训练前后对比，必须成为
   结果元数据而不是静默变化。

## 10. 下载、哈希和本地配置冻结

### 10.1 已执行 dry-run

以下精确 dry-run 已实际执行成功，没有下载权重：

```bash
hf download \
  bartowski/mistralai_Ministral-3-8B-Instruct-2512-GGUF \
  mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf \
  --revision ad82bf81321f4b22de70014ecd5135730115f6a8 \
  --local-dir /home/sjc/desktop/RONDO/eval-data/models \
  --max-workers 1 \
  --dry-run \
  --format json
```

CLI 返回文件和 `5.2G` 显示大小。对官方 Q4 同样完成 exact revision dry-run，返回 `5.2G`；没有下载任一权重。
dry-run 只在 ignored 目标下留下 192 bytes 的 Hugging Face local-dir metadata/lock，目标 GGUF 不存在。

### 10.2 获批后的唯一下载命令

只有用户明确授权本文唯一对象，并且下载前资源门禁全部通过后，才运行：

```bash
HF_XET_CACHE=/home/sjc/desktop/RONDO/eval-data/models/.cache/huggingface/xet \
HF_XET_CHUNK_CACHE_SIZE_BYTES=0 \
HF_XET_NUM_CONCURRENT_RANGE_GETS=1 \
HF_XET_HIGH_PERFORMANCE=0 \
hf download \
  bartowski/mistralai_Ministral-3-8B-Instruct-2512-GGUF \
  mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf \
  --revision ad82bf81321f4b22de70014ecd5135730115f6a8 \
  --local-dir /home/sjc/desktop/RONDO/eval-data/models \
  --max-workers 1
```

`--max-workers 1` 限制为单文件 worker；Xet range gets 也显式限制为 1，禁用 high-performance 和 chunk cache，避免隐含的高并发
磁盘/网络访问。不得改 repo、revision、文件名或追加 mmproj/其他 quant。

### 10.3 文件大小和 SHA-256 验证

下载完成后只做静态验证，不加载模型：

```bash
MODEL=/home/sjc/desktop/RONDO/eval-data/models/mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf
test -f "$MODEL" && test ! -L "$MODEL"
test "$(stat -c '%s' "$MODEL")" = 5198387456
printf '%s  %s\n' \
  7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a \
  "$MODEL" | sha256sum --check --strict -
```

LFS content SHA-256 与整文件 SHA-256 对应；真实 `sha256sum` 只有下载后才能产生验收证据。

### 10.4 下载后 `rondo.local.toml` 方案

下载且静态验证通过后，先从完整 `rondo.local.example.toml` 复制/保留所有必需字段，再只修改或核对以下键。下方是差异片段，
**不是可替换完整表的独立配置**；`runtime`、API/base URL、model id、binary/host/port、metrics/slots/tools 和 request timeout 等
未列键必须沿用完整合同。

```toml
[local_model]
model_path = "eval-data/models/mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf"
model_sha256 = "7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a"
format = "gguf"
quantization = "Q4_K_M"

[local_model.server]
context_size = 8192
gpu_layers = "auto"
flash_attention = "on"
parallel = 1

[local_model.request]
stream = false
temperature = 0.0
top_p = 1.0
seed = 42
max_output_tokens = 512
max_retries = 0
structured_output = true
```

现有 loader 会检查普通非 symlink 文件、GGUF magic 和完整 SHA；`quantization` 目前只是声明字符串，不会反向证明文件内部 quant，
repo/revision/converter/imatrix 也不在 TOML 表达，故以本档案保存来源冻结。`gpu_layers = "auto"` 是 RONDO policy，会映射为
`--n-gpu-layers 99`，不是 llama.cpp 原生 auto。下载前不写入机器实际配置。

## 11. 主机与 canary 下载门禁快照

2026-08-12T10:38:45Z 的只读快照：

- Windows `C:`（`/mnt/c`）总量 `992,273,043,456` bytes，已用 `778,064,154,624`，实际可用
  `214,208,888,832` bytes（约 199.5 GiB）。WSL 虚拟文件系统显示的约 852 GiB 余量不用于满足宿主门禁。
- `eval-data/models/` 只有 192 bytes dry-run metadata；永久新增权重为精确 `5,198,387,456` bytes，另有微小 metadata。
  为中断恢复/临时文件保守预留两倍文件大小，即至少 `10,396,774,912` bytes（9.683 GiB）宿主余量。
- 瞬时进程名扫描未发现 llama-server、Ollama、vLLM 或本地模型进程；这只是当时快照。
- 第一次瞬时 Docker 查询看似空闲，数秒后的只读复查已出现正在运行的 RONDO P2 B7 canary 容器
  `7dfec90ff85d`，任务 label `20260812-280000008-tb-rondo-r1`。这直接证明“瞬时 Docker 为空”不能构成稳定窗口。
- 当时 `docker system df`：images 11.5 GB、containers 1.468 GB（1 active）、volumes 0、build cache 13.22 GB。
  本任务没有启动、停止、拉取或修改任何 Docker 对象。

即使单文件、单 range 下载，5.2GB 网络和 Windows VHD 磁盘写入仍可能与 canary 抢占网络/磁盘 I/O，并放大任务延迟。
建议窗口：canary 当前批次结束后，由其调度者明确保证整个下载期间不会启动新任务；窗口长度取决于当时未测网络速度，不在本快照
虚构时长。没有该确认时保持阻塞。

下载前必须重新完成并记录：

1. canary 调度者明确确认窗口内不启动新任务；
2. Docker 无运行容器，真实本地模型进程不存在；
3. Windows `C:` 实际余量仍满足仓库门禁并至少覆盖上述保守增量；
4. repo、revision、文件名、exact bytes 和预期 SHA 与用户批准对象逐字一致。

任一条件失败即停止并报告，不能仅凭瞬时 Docker 空列表继续。

## 12. 恢复入口与未完成验收

当前精确恢复入口：

1. 用户只对第 1 节唯一 GGUF 给出明确下载授权；
2. 在 worktree `/home/sjc/desktop/RONDO/.claude/worktrees/0812-local-model-engineering` 恢复本计划；
3. 重做第 11 节四项下载前门禁；
4. 运行第 10.2 节唯一下载命令；
5. 只运行第 10.3 节 size/SHA 验证并更新 ignored `rondo.local.toml`；
6. 不启动 llama.cpp、不加载模型、不使用 GPU，另开后续 CUDA/model-backed 验收任务。

仍未完成：真实文件 SHA、CUDA runtime、GGUF load、GPU offload、显存峰值、最大安全 context、首 token/总耗时、chat template 实际
渲染、grammar/schema/真实审批输出、未微调 M3 baseline。等待下载批准不是技术失败，以上项目均不得写成通过。

## 13. 权威和候选资料

- Mistral 官方模型卡：<https://docs.mistral.ai/models/model-cards/ministral-3-8b-25-12>
- Mistral 已知限制：<https://docs.mistral.ai/resources/known-limitations>
- 官方 FP8 Instruct：<https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512>
- 官方 BF16 Instruct：<https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-BF16>
- 官方 GGUF 冻结树：<https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF/tree/0102285ad796bd99af90f58de616092e5630e970>
- 官方 Additional Checkpoints collection：<https://huggingface.co/collections/mistralai/ministral-3-additional-checkpoints-6929c2e6c913fbc94d7c6468>
- Bartowski 候选：<https://huggingface.co/bartowski/mistralai_Ministral-3-8B-Instruct-2512-GGUF>
- Unsloth 候选：<https://huggingface.co/unsloth/Ministral-3-8B-Instruct-2512-GGUF>
- LM Studio Community 候选：<https://huggingface.co/lmstudio-community/Ministral-3-8B-Instruct-2512-GGUF>
- mradermacher static 候选：<https://huggingface.co/mradermacher/Ministral-3-8B-Instruct-2512-BF16-GGUF>
- mradermacher imatrix 候选：<https://huggingface.co/mradermacher/Ministral-3-8B-Instruct-2512-BF16-i1-GGUF>
- ggml-org 候选：<https://huggingface.co/ggml-org/Ministral-3-8B-Instruct-2512-GGUF>
- llama.cpp `b10333` release：<https://github.com/ggml-org/llama.cpp/releases/tag/b10333>
- llama.cpp Mistral3 frozen source：<https://github.com/ggml-org/llama.cpp/blob/b10333/src/models/mistral3.cpp>
- llama.cpp server：<https://github.com/ggml-org/llama.cpp/blob/b10333/tools/server/README.md>
- llama.cpp multimodal：<https://github.com/ggml-org/llama.cpp/blob/b10333/tools/mtmd/README.md>
- Hugging Face download/local-dir：<https://huggingface.co/docs/huggingface_hub/en/guides/download>
- Hugging Face environment variables：<https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables>
