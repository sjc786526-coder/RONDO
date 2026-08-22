# RONDO Multi Publication Critic：本地源码与工程事实取证报告

> 文档性质：形成于 2026-08-21 的只读取证报告，用于外部评审比较且仅比较
> `Skywork/Skywork-Reward-V2-Qwen3-1.7B` 与 `Qwen/Qwen3-Reranker-4B`。本文不做模型排名、
> 不给最终技术推荐，也不扩展候选池。
>
> 检查基线：`main@9f32f22a60e73db0b2234ae9d4ddc8c15d904985`。
>
> 执行边界：未启动/修改 RunPod，未调用付费 API，未下载模型或 package，未读取 `.env.local`、ignored
> 私密 trace 或任务正文，未运行 Cargo、Docker、训练或真实模型。本轮只执行了源码/环境/缓存/磁盘检查和两个随机初始化
> tiny Transformers mock；mock 不是候选模型证据。

本文使用四种证据标签：

- **源码确认**：当前 RONDO、当前已安装 package 或 exact 本地缓存源码可逐行确认；
- **本机环境确认**：本轮命令在当前机器得到；
- **静态工程推断**：由已确认的数据流、tensor shape 或文件合同推导，尚未在候选模型上运行；
- **需要后续 paid smoke**：必须取得完整权重并在目标 GPU 上运行才能关闭。

## A. Environment snapshot

### A.1 RONDO revision 与规划位置

本轮开始时的原始输出为：

```text
$ git rev-parse HEAD
9f32f22a60e73db0b2234ae9d4ddc8c15d904985

$ git status --short
<no output>
```

**源码确认**：当时主工作区干净。`doc/WBS.md:3-7,29,34-38,97-104` 表明 RONDO Multi 已完成既有包、
当前没有已排期工作包；Publication Critic 仍是研究而非已登记实施任务。对应长期边界见
`doc/WBS/multi-agent-trusted-evidence.md`，最新研究设计是
`doc/research/2026-08-21-rondo-multi-public-state-publication-quality-critic-research-design.md`。该设计文档记录的
publication 代码基线是 `56ec5d2...`；本轮用当前 `9f32f22...` 重新检查。两基线之间，用户点名的
publication/training 源码没有差异，研究设计本身有后续 score-first 等修订。

报告写入后的 `git status --short` 只有预期中的：

```text
?? doc/research/2026-08-21-rondo-multi-publication-critic-local-engineering-facts.md
```

没有其他 tracked/untracked 工作区变化。

### A.2 三个不同的 Python 环境，不能混称为一个“当前环境”

| 范围 | 位置/身份 | 实际事实 |
|---|---|---|
| RONDO 当前 controller/eval 环境 | `eval/.venv` | Python 3.12.3；由根 `justfile:3-11` 以 `eval/uv.lock` frozen sync；`eval/pyproject.toml:1-8` 只有 `harbor==0.20.0`；没有训练包。 |
| 本机非 RONDO 管理的 ML 环境 | `/home/sjc/vlm_env` | Python 3.12.3；可读取 Torch 2.5.1+cu121 / Transformers 5.8.1 源码。本报告的“当前已安装 Transformers 源码”结论来自这里，不把它冒充上一轮训练环境。 |
| 上一轮 L6 实际远端训练环境 | 原 `/workspace/rondo-l6/venv`，本机已不存在 | 以已回收 `dependency-identity.json`/receipt 为事实源：Python 3.12.3、CUDA 12.8、Torch 2.8.0+cu128、Transformers 5.14.1 等。位置和创建流程见 `training/local-approval-l6/stage2-runbook.md:265-278`。 |

上一轮转换还使用独立 `/workspace/rondo-l6/conversion-venv`（Python 3.11、Transformers 4.57.6），见
`training/local-approval-l6/stage2-runbook.md:280-312`；它不是训练 venv。

### A.3 实际版本

| Package/runtime | RONDO `eval/.venv` | 本机 `/home/sjc/vlm_env` | L6 实际训练 receipt |
|---|---|---|---|
| Python | 3.12.3 | 3.12.3 | 3.12.3 |
| PyTorch | not installed | 2.5.1+cu121 | 2.8.0+cu128 |
| CUDA runtime | not installed | Torch build 12.1；当前 `torch.cuda.is_available()==False` | 12.8；recipe 的容器标签写 12.8.1 |
| NVIDIA driver | 当前 live version 无法确认；`nvidia-smi` 报 NVML 被 OS 阻断 | 同左 | receipt 未记录 driver |
| Transformers | not installed | 5.8.1 | 5.14.1 |
| Accelerate | not installed | 1.13.0 | 1.14.0 |
| bitsandbytes | not installed | 0.49.2 | 0.49.2 |
| PEFT | not installed | 0.19.1 | 0.19.1 |
| TRL | not installed | not installed | 1.9.0 |
| sentence-transformers | not installed | not installed | 未纳入 receipt，远端当时是否安装/版本未知 |
| flash-attn | not installed | not installed | 未纳入 receipt，未知 |
| xformers | not installed | not installed | 未纳入 receipt，未知 |
| DeepSpeed | not installed | not installed | 未纳入 receipt，未知 |
| triton | not installed | 3.1.0 | 未纳入 receipt，未知 |
| flashoptim / flash-optim | not installed | not installed | 未纳入 receipt；旧 direct pins 中不存在 |

**本机环境确认**：当前没有 `nvcc`，`/dev/dxg` 不存在；WSL 有 libcuda stub，但不能据此声明 GPU/driver 可用。
L6 实际身份位于
`eval-data/local-approval/l6/plan037-stage2/attempt-03-formal-20260816T104402Z/dependency-identity.json:1-15`，
并由同目录 `training-receipt.json:144-165` 重复绑定。它只精确记录七个 direct package、Python、CUDA 和
container tag；`eval/rondo_eval/local_approval/l6_training.py:53-63,859-912` 没有保存完整 transitive `pip freeze`，
container 也没有 digest，因此不能表述为 bit-for-bit 完整环境锁。

项目的依赖/环境载体是：

- `eval/pyproject.toml` + `eval/uv.lock` + ignored `eval/.venv`；
- `training/local-approval-l6/dependencies-candidate-v1.txt:1-10` 的旧训练 direct pins；
- `training/local-approval-l6/conversion-dependencies-v1.txt:1-13` 的独立转换 pins；
- RunPod task-local venv 和回收的 actual dependency identity/receipt；
- 没有根 `requirements.txt`、根 Python `pyproject.toml`、Poetry lock 或项目 conda env。

**静态工程推断**：新建 Publication Critic 专用 venv 不需要修改 `eval/.venv`、旧 `/workspace/rondo-l6/venv`
或已归档 receipt；上一轮已经天然分离 controller、训练和转换环境。因此独立环境本身不会改变上一轮可复现合同，前提是
不改旧 pins/receipt、也不复用旧路径。这不等于旧 container 能 bit-for-bit 重建。

### A.4 本地模型/Hugging Face cache

**本机环境确认**：`hf` 来自 `/home/sjc/.local/bin/hf`，其环境的 `huggingface_hub==1.27.0`。由于 `hf cache list`
在本沙箱启动时被网络策略阻断，本轮改用同一 package 的纯本地 `scan_cache_dir()` 和文件系统检查，没有联网或下载。

| 目标 | repo/revision/cache 事实 |
|---|---|
| Qwen3 family tokenizer/config | not locally available；无 snapshot、config、tokenizer 或 weights |
| `Qwen/Qwen3-Reranker-4B` | not locally available |
| `Skywork/Skywork-Reward-V2-Qwen3-1.7B` | not locally available |
| ModernBERT | not locally available |
| 其他 Qwen3 checkpoint | none |

标准 `~/.cache/huggingface/hub` 只有约 384 KiB，主要是 9 个 Ministral repo 的 README。另有一个
`Qwen/Qwen2.5-VL-3B-Instruct` 40-byte `refs/main` 残留，revision
`66285546d2b821cf421d4f5eb2576359d3770cd3`，但没有 blobs/snapshots，不能算 tokenizer/config/weight 资产。
`eval-data/models` 只有无关的
`mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf`（logical 5,198,387,456 B）。exact llama.cpp 源码里的
Qwen 模板和 `ggml-vocab-qwen35.gguf` 是运行时源码 fixture，不是候选 checkpoint/cache。

### A.5 磁盘空间

```text
Filesystem  Mount/use                 Size  Used  Avail  Use%
/dev/sdd    RONDO + HF cache (WSL)    1007G 150G  806G   16%
C:          /mnt/c                    925G  757G  168G   82%
```

精确 `/mnt/c` 可用量为 `180,255,981,568 B`（167.876 GiB）。WSL `/dev/sdd` 可用 805.814 GiB，
但按项目门禁不能替代 Windows `C:` 实际余量；`scripts/with-build-lock.sh:154-164` 和
`training/local-approval-l6/stage2-runbook.md:37-40` 也使用 `/mnt/c` 读数。

| 路径 | allocated 大小 |
|---|---:|
| `eval-data`（已含 models） | 47,091,662,848 B（约 44G） |
| `eval-data/models` | 5,198,618,624 B（约 4.9G） |
| `training` | 1,892,352 B（约 1.9M） |
| `~/.cache/huggingface` | 471,040 B（约 460K） |
| `~/.cache/torch` | 69,632 B（约 68K） |

只算 BF16 参数 tensor，C0/C1/C2/C3 四份权重为：

- 1.7B：`4 × 1.7e9 × 2 B = 13.6 GB = 12.666 GiB`；当前本机不构成明显压力；
- 4B：`4 × 4e9 × 2 B = 32 GB = 29.802 GiB`；可容纳但占用显著。

以上不含 optimizer state、master weights、scheduler/RNG、模型 cache、SCP/verify 暂存和保存时重复副本。
因此 4B 的完整可恢复 checkpoint 是否安全不能仅凭 weights-only 余量关闭。

## B. Publication packet facts

### B.1 当前真实 schema 与上下文

| 项目 | 当前真实事实 |
|---|---|
| title 最大长度 | tool schema 无 `maxLength`，raw input 无源码上限。截断阈值 200 scalars；实际 overlong canonical stored 最大 **213 scalars / 815 UTF-8 bytes**，因为追加 13-scalar/15-byte marker。 |
| summary 最大长度 | raw 无上限；阈值 2,000，实际 stored 最大 **2,013 scalars / 8,015 bytes**。 |
| handoff 最大长度 | raw 无上限；阈值 1,000，实际 stored 最大 **1,013 scalars / 4,015 bytes**。 |
| new Event 可获得哪些上下文 | publish 前已有 authoritative actor、target kind、raw title/summary/handoff、based-on revision、request identity；Event 尚不存在，无历史。 |
| existing Event 可获得哪些历史 | 无需新 API 即可用 permission-scoped `history(event_id, limit=N)` 得 canonical title + 最近 N Version；`N=1` 得最新一条，单页最大 50。 |
| Event history 是否 bounded | 单次 page bounded；整个 Event chain 不 bounded，可用 `before` 持续分页。 |
| history 当前按什么单位限制 | Event-scoped 以 **Version 数**限制，默认 10、最大 50；不是字符、UTF-8 bytes 或 token。 |
| evidence metadata 能拿到什么 | 已提交 Version 有 Fact IDs；model-facing history 每次最多显示 32 refs + offset/omitted。逐个 read 可得 producer、success/failure category、item/call/tool locator；按需读取 observation body 最多 4,000 scalars，但 V1 不应带 body。 |
| 哪些内容绝对不应进入 Critic packet | transcript、hidden reasoning、sibling 私有内容、全 Team State/整个 Active World Index、未筛选工具/evidence body、密钥、原始 trace、repo、无界 history，以及 label/defect/split/generator/reviewer/source identity 等监督 metadata。 |
| canonicalization 在哪里发生 | 仅在 `TeamStore::publish()` commit 路径：new title `store.rs:341-351`，summary/handoff `:379-386`。 |
| publish 前是否已经能拿到 canonical text | **不能**。handler 拿到的是 raw draft；`clamp_*` 是 `team-state` crate-private，且只在 store mutation 内调用。existing Event 的旧 title/history 已 canonical，但当前 draft 没有。 |
| Critic hook 最自然的位置 | `core/src/tools/handlers/team_tools/publish.rs::handle_call()`：target/submission 构造后、同步 `handle.publish()` 前（当前 `:34-77`），从而在 TeamStore mutex 外 await。 |

`team_publish` 的模型可见输入为 `event_id? / title? / summary / handoff? / based_on_revision?`，只有 `summary`
在 schema required；见 `multidev/codex-rs/core/src/tools/handlers/team_tools/spec.rs:11-59`。解析器还接受 schema 隐藏的
`request_id?`，未知字段拒绝；见 `publish.rs:102-114`。actor 来自 authoritative session，缺失 based-on revision 按 0，
缺失 request ID 使用 harness call ID；见 `publish.rs:34-65`。

canonical Version 是 `author + summary + handoff + evidence_refs`，见
`multidev/codex-rs/team-state/src/model.rs:152-161`。Evidence refs 由 Harness 在成功 commit 时自动选择，不是模型 authored
字段；`store/evidence.rs:97-127`。

### B.2 长度阈值与真实 stored 上界

**源码确认**：`clamp_authored()` 先 `take(N)`，再追加 `" […truncated]"`，并非把 marker 算进 N；见
`multidev/codex-rs/team-state/src/model.rs:20-45`。marker 是 13 Unicode scalars / 15 UTF-8 bytes。因此上表使用的是
真实 stored 上界，不是注释所称的 ceiling。UTF-8 上界只计字符串本体，不含 JSON key、quotes 和 escaping。

### B.3 existing Event history 的最小当前实现

**源码确认**：`TeamStateHandle::history()` 已经能同步、permission-scoped 地读取 existing Event，见
`multidev/codex-rs/team-state/src/handle.rs:267-273`、`store.rs:697-761`。

- 最近 1 个 Version：`limit=1`；得到 canonical Event title 和最新 Version；
- 最近 N 个 Version：`limit=N`，被 clamp 到 1..50；
- 当前 team_history 最大 bounded page：50 Versions；
- 完整 Event chain：只能分页取得，整体无界，不能称为 bounded packet；
- 更窄 projection：当前没有专用 Critic type，但 core packet builder 可先调用现有 history，再 exact-allowlist 取
  title/summary/handoff/固定 metadata；若要在 domain 层冻结 typed projection，最小改动点是
  `team-state/src/view.rs`、`store.rs::event_history` 邻近、`handle.rs` 和 `lib.rs`，再由 core builder 消费。

`VersionView` 当前还含 id、author/thread+label、完整 evidence refs、producer/root state、stale、retired 等；见
`team-state/src/view.rs:23-38,50-57` 和 `store.rs:673-688`。model-facing `team_history` 会缩成
version id、author label、summary/handoff、最多 32 evidence refs + pagination、producer/root/stale；见
`core/src/tools/handlers/team_tools/history.rs:66-101,113-149`。

Active World Index 不是等价的 history packet：它只投影 active view，用约 4,000-token hard cap 丢弃旧版本并显式标 omission，
且每次 sampling 重建、不进入普通 conversation/rollout；见 `team-state/src/render.rs:18-25,82-149,256-303`、
`core/src/team/projection.rs:1-16,69-125`。

### B.4 最大输入规模的机械上界

当前没有 Critic packet serializer，因此 whole JSON 没有可给出的有限全局上界：raw request strings 没有 maxLength，
participant `author_label` 没有长度 clamp，Event chain 可分页无界，canonical Version 的 evidence vector 也保存整个 window。
下面只计算设计中 exact allowlist 的 **canonical authored text**，不含字段名、JSON framing、IDs、label、evidence metadata。

定义 publication-only = canonical Event title + 本次 canonical summary + optional handoff；history 只增加 prior
summary/handoff，不重复 title：

| 内容 | Unicode scalar 最大 | UTF-8 bytes 最大 |
|---|---:|---:|
| publication-only | **3,239** = 213+2,013+1,013 | **12,845** = 815+8,015+4,015 |
| + 最近 1 个 prior Version | **6,265** | **24,875** |
| + 最大单页 50 个 prior Versions | **154,539** | **614,345** |

existing `team_publish` draft 自身不带 title，因此只计本次 summary+handoff 时是 3,026 scalars / 12,030 bytes；
上表为了比较统一把已存在 Event 的 canonical title 也计入 publication packet。new Event 则三个字段本来就都来自本次 publication。

若字面拼接完整 model-facing `team_history` page，它会再输出一次 title；publication + literal page 的 authored text 上界为
154,752 scalars / 615,160 bytes。缺少一个 handoff 时，每处分别减 1,013 scalars / 4,015 bytes。

这些数字不是 token 数，也不是整个请求 body 的 byte cap。

### B.5 Evidence window 与真实分布缺口

**源码确认**：尚未发布的本次 Fact window 没有 read-only peek/reservation API。`take_publish_window()` 在 commit 中筛选
并推进 cursor，Critic await 期间还可能新增 Fact；见 `store.rs:369-385`、`store/evidence.rs:97-127`。因此 V1 当前最多能
安全使用固定 evidence policy marker、history 中 bounded Fact IDs/count/omitted，或逐个读取的 body-free category/tool metadata；
它不能无副作用确认最终会附上的完整新 Fact window。

tracked Team Lens/Plan 050 资产是 body-free，body-bearing fixture 是 synthetic sentinel，未形成真实 publication 正文样本。
本轮也未读取 ignored trace。因此：

```text
当前无法获得真实 token distribution
```

同样无法给出真实 P50/P90/P95/P99/max 字符分布。不能用 synthetic fixture 冒充真实分布。

### B.6 Hook 还缺的两个当前合同

1. **Canonical draft**：必须把当前 `clamp_*` 变为 store 与 packet builder 共用的纯函数/typed canonical candidate，
   或在 packet 前拒绝超长 draft；当前 publish 前拿不到权威 canonical text。
2. **Committed replay fast path**：dedup 只在 `TeamStore::publish()` 内按 `(actor, request_id)` 检查 exact raw request，
   `store.rs:292-306`。naive 前插 Critic 会让已提交 replay 再推理。需要只读 committed lookup 或 session 侧绑定
   request identity + canonical fingerprint 的缓存；PASS 后仍由原 store 重做 permission/stale/commit。

以上是接入缺口，不是本轮实现建议或模型选择。

## C. Existing training stack

### C.1 当前框架与职责

| 组件 | 当前实际职责 |
|---|---|
| Transformers | `AutoTokenizer`、model loader、`TrainingArguments`、原生 `Trainer`；`l6_training.py:1189-1194,1236-1274,1327-1354` |
| PyTorch | `Dataset` 和 padding collator tensor；`l6_training.py:1294-1322` |
| PEFT | k-bit preparation、LoRA injection、adapter reload；`l6_training.py:1192,1275-1292,1435-1461` |
| bitsandbytes | NF4 4-bit base + `paged_adamw_8bit`；recipe `:45,51-57` |
| Accelerate | 作为 Trainer 间接依赖；项目代码不直接调用 |
| TRL | 仅在 dependency identity 中冻结；训练代码没有 import/use |
| DeepSpeed / LLaMA-Factory | 当前路径没有配置、import 或调用 |
| 纯 PyTorch training loop | 没有；loop 由 Trainer 管理 |

### C.2 loss、forward、collator、batch 与 checkpoint

| 位置 | 当前事实 |
|---|---|
| Trainer class | 直接使用 `transformers.Trainer`；全仓无 custom Trainer subclass / `compute_loss` precedent。 |
| current loss | 没有显式 loss；CausalLM 根据 `labels` 做 completion-only LM loss，prompt labels 为 `-100`；`l6_training.py:581-623,1294-1322`。 |
| forward | 无 `forward_score()` wrapper；Trainer 隐式调用 CausalLM forward。 |
| collator / batch | 只有 `input_ids / attention_mask / labels`，padding 分别 pad-id / 0 / -100；`l6_training.py:1294-1322`。 |
| gradient accumulation | 已接线并实际设为 8；recipe `:38`、`l6_training.py:1330`。 |
| gradient clipping | 已接线 `max_grad_norm=1.0`；recipe `:42`、`l6_training.py:1337`。 |
| mixed precision | 已接线 BF16；recipe `:37`、`l6_training.py:1339`。 |
| LR scheduler | warmup ratio + scheduler type 已接线；`l6_training.py:1334-1336`。 |
| checkpoint save | Trainer `save_steps=25`、`save_total_limit=2`；recipe `:3-6`。 |
| resume | `trainer.train(resume_from_checkpoint=...)`，外层再检查 direct `checkpoint-N`、非 symlink、同 run/recipe/dependency、未形成完成态；`l6_training.py:1084-1159,1354`。 |

本机回收的真实 L6 checkpoint 包含 `adapter_model.safetensors`、`optimizer.pt`、`scheduler.pt`、
`trainer_state.json`、`rng_state.pth`、`training_args.bin`。这是 bitsandbytes QLoRA checkpoint 证据，不是 FlashOptim
或 full-model 证据。

### C.3 scalar + point/pair 的最小改造面

**可以复用**：原生 Trainer/TrainingArguments 的 optimizer/scheduler、gradient accumulation、clip、BF16、save/resume
骨架；hash/manifest、group split、近重复、exclusive publish 的机制模式。

**需要小改/中等改动**：新 collator 可加入 `sample_kind`、point label、pair arm/index；当前 L6 已设置
`remove_unused_columns=False`（`l6_training.py:1344`），custom `compute_loss()` 可取走这些字段再调用模型。
point 和 pair sequences 可 pad 到共同宽度、沿 batch 维 flatten/concat，一次 forward 后按索引拆 score；autograd 不要求改
模型内部。这是静态 tensor/framework 事实，尚无候选模型 smoke。

**应该新建**：Publication Critic dataset/projection/batch schema、custom Trainer 或带 loss 的 model wrapper、
full-model load/save/reload、recipe/dependency/receipt/artifact contract。`synthetic_training.py` 写死 Local approval 的
allow/deny schema且不调用模型；`l6_training.py` 又写死 470 条、completion-only target、NF4/LoRA regex 和 adapter semantics，
只能复用模式，不能直接改几个字段充当新任务。

同一 batch 混合 pointwise/pairwise 在 Trainer 上可实现，但必须明确 loss 归一化、权重、有效 item count 和索引映射。
当前仓库没有对此的测试先例。

## D. FlashOptim local compatibility

### D.1 安装与直接 Transformers integration

| 问题 | 当前事实 |
|---|---|
| FlashOptim installed? | **No**：RONDO env、本机可读 ML env、cache 中均未发现。 |
| 当前本机 Transformers 5.8.1 integration? | **No**：`OptimizerNames` 与 handler registry 无 `flash_adamw` / `flash_adamw_8bit`；`/home/sjc/vlm_env/.../transformers/training_args.py:111-157`、`trainer_optimizer.py:592-615`。 |
| L6 actual Transformers 5.14.1 integration? | **No direct `TrainingArguments(optim=...)` name**。本机无该 package source；用官方 pinned v5.14.1 源码补查，enum/registry 同样无 FlashOptim。 |
| 准确 optimizer 名称 | 当前两个版本均为 **none**。`optim="flash_adamw"` 会在 `OptimizerNames(...)` 转换时被拒绝。 |
| dependency delta | 旧 frozen direct deps 无 FlashOptim；新环境至少增加一个未验证 dependency，且不能依赖旧 `optim=` 接线。 |

5.14.1 的 supplementary primary-source evidence：

- [official `training_args.py` v5.14.1 optimizer enum](https://github.com/huggingface/transformers/blob/v5.14.1/src/transformers/training_args.py#L104-L148)
- [official `trainer_optimizer.py` v5.14.1 registry](https://github.com/huggingface/transformers/blob/v5.14.1/src/transformers/trainer_optimizer.py#L535-L556)

该官方 pinned source 只用来回答本机缺失的 exact frozen version 实现，不是公开模型调研。

### D.2 `optim_args` 与 Flash-specific 参数

本机 5.8.1 的 `optim_args` 只是 `key=value,...` 字符串 parser，见
`/home/sjc/vlm_env/.../transformers/trainer_optimizer.py:65-73`；5.14.1 同样只有 generic parser。因为没有 Flash handler，
以下参数不会由 Transformers 自动传给 FlashOptim：

```text
master weight bits
state bits
gradient release
其他 FlashOptim-specific 参数
```

准确结论均为：

```text
当前本地无法确认
```

Transformers 5.14.1 的 generic Trainer 支持 `optimizer_cls_and_kwargs=(OptimizerClass, kwargs)` 注入自定义 optimizer；
见 [official trainer.py v5.14.1](https://github.com/huggingface/transformers/blob/v5.14.1/src/transformers/trainer.py#L306-L361)。
这只证明存在框架入口，不证明 FlashOptim 的类名、参数、gradient release 或兼容性。

### D.3 Trainer 一般机制与 FlashOptim 专项结论

| 机制 | 一般 Trainer / 当前 L6 事实 | FlashOptim 当前本地结论 |
|---|---|---|
| BF16 | Trainer 支持；L6 已实际使用 | 当前本地无法确认 |
| gradient checkpointing | Trainer/model 支持；当前 L6 经 PEFT k-bit prepare 开启 | 删除 PEFT 后需接原生 model API；Flash-specific 当前无法确认 |
| gradient accumulation | Trainer 已支持并实证为 8 | 标准 step 形态可驱动；gradient release 组合当前无法确认 |
| gradient clipping | Trainer 在 optimizer step 前 clip；L6 为 1.0 | Flash/gradient-release 组合当前无法确认 |
| LR scheduler | Trainer 从 optimizer 创建并 step scheduler | 需标准 `param_groups` 等；当前本地无法确认 |
| single GPU | Trainer 通用路径支持；L6 实际为单 A40 | Flash-specific 当前本地无法确认 |
| Trainer checkpoint save | 一般路径会保存 model、optimizer、scheduler、Trainer state、RNG | 是否能正确保存 Flash state 当前无法确认 |
| resume_from_checkpoint | 一般路径调用 optimizer/scheduler `load_state_dict()` | Flash state_dict/load 兼容性当前无法确认 |

### D.4 checkpoint 重点结论

Transformers 5.14.1 一般 checkpoint 路径在 `_save_checkpoint` 中保存 model、optimizer+LR scheduler、scaler、RNG、
`trainer_state.json`；普通 optimizer 路径调用 `torch.save(self.optimizer.state_dict(), optimizer.pt)`，resume 再调用
`optimizer.load_state_dict()`。可参见
[official trainer.py v5.14.1 checkpoint implementation](https://github.com/huggingface/transformers/blob/v5.14.1/src/transformers/trainer.py#L2778-L2979)。

**源码确认**：L6 实物也有 optimizer/scheduler/trainer/RNG 文件，但 optimizer 是 `paged_adamw_8bit`。
本机没有 FlashOptim package/source，故 FlashOptim `state_dict()` 是否普通 PyTorch 兼容、是否能被当前 loader 安全恢复、
master/state bits 是否完整入盘，全部仍是缺口。它们可以先做无付费 tiny optimizer checkpoint smoke；候选模型上的完整恢复和
显存峰值仍需后续 GPU smoke。

本轮得到的 FlashOptim 缺口同时作用于两个候选，并非“Qwen 4B 特有实质问题”的证据，因此没有扩展 GaLore 调研。

## E. Skywork implementation surface

### E.1 SequenceClassification precedent 与 exact model 边界

**源码确认**：RONDO 产品、训练和 eval 代码中没有 `AutoModelForSequenceClassification`、`num_labels=1`、scalar/regression
head precedent。当前 L6 recipe 是 `AutoModelForImageTextToText`，见
`training/local-approval-l6/recipe-candidate-v1.json:31-35`、`l6_training.py:1262-1274`。

本机 Transformers 5.8.1 框架具有：

- `AutoModelForSequenceClassification`：`models/auto/modeling_auto.py:2046-2052`；
- `qwen3 -> Qwen3ForSequenceClassification` mapping：同文件 `:1340-1346`；
- Qwen3 sequence classification class：`models/qwen3/modeling_qwen3.py:520-521`；
- generic `Linear(hidden_size, num_labels)` + last non-pad-token pooling：`modeling_layers.py:97-168`。

但 Skywork exact config/tokenizer/model code 不在本地 cache，所以不能确认它是否走标准 mapping、是否需要 remote code、
实际 pooling/head、padding 或 `num_labels`。这些应标 `未知/需模型 metadata 或 model smoke`，不能从模型名补出。

### E.2 scalar logits 与 custom loss

若 exact checkpoint 确实返回 `logits.shape == [B,1]`，custom `compute_loss()` 做
`score = logits.squeeze(-1)` 没有框架障碍。需要注意：Transformers generic sequence-classification loss 在
`num_labels=1` 时自动选择 regression/MSE，见本机 `transformers/loss/loss_utils.py:91-107`；它不是本项目 Binary
BCE/logistic + pair ranking loss，因此必须 custom loss。

本轮 tiny mock 用随机小型 `Qwen3Config(num_labels=1)` 验证：4 条 concat input 一次 forward 得 `[4,1]`，
`squeeze(-1)` 后混合 BCE 与 `-logsigmoid(score_pos-score_neg)` 能 backward，scalar head 和 embedding 均有 gradient。
这是 **框架 smoke**，不是 Skywork 模型 smoke。

### E.3 pair batching 与 tokenizer/template

scalar path 可把 `x_pos/x_neg` pad 到共同宽度，沿 batch concat，一次 forward 后 split scores；不改模型内部结构。
point samples 也可一起 flatten，但需新 collator/index map/custom Trainer。

本机没有 Skywork config/tokenizer/chat template，也没有任何 Qwen3 tokenizer/config cache：

```text
not locally available
```

因此 actual padding side、chat template、特殊 token 与 packet render identity 尚未确认。

## F. Qwen Reranker implementation surface

### F.1 Qwen3 `forward()` logits 路径

本机 Transformers 5.8.1 `Qwen3ForCausalLM.forward()` 的准确参数是：

```python
logits_to_keep: int | torch.Tensor = 0
```

不是 `num_logits_to_keep`。位置：
`/home/sjc/vlm_env/lib/python3.12/site-packages/transformers/models/qwen3/modeling_qwen3.py:458-469,502-505`。

语义：

- `0`：所有 sequence positions，输出 `[B,S,V]`；
- 正整数 `N`：最后 N positions；`1` 输出 `[B,1,V]`；
- 1-D Tensor：选择 sequence-position indices；
- 它选择 **position**，不选择 vocab columns。

实现先取得完整 transformer hidden states，再做
`self.lm_head(hidden_states[:, slice_indices, :])`。slice/lm_head 没有 detach/no-grad。随机 tiny mock 机械验证了
`0/1/2/Tensor` 的 shape 和 backward；embedding 与 lm_head 均有 gradient。`logits_to_keep=1` 只省略其他 positions 的
vocab projection/logits tensor，不省略 transformer 对输入序列的 forward/backward。

### F.2 普通 LM labels 不直接适用

若同时传标准 full-sequence `labels`，Qwen forward 会把截短 logits 交给 CausalLM loss，而 loss 会 flatten 完整 shifted labels；
本机 tiny mock 对 `logits_to_keep=1` + `[B,S]` labels 得 batch-size mismatch。因此 yes/no scorer 需要不传标准 LM labels，
在 custom loss 中从最后位置目标 token logits 计算 Binary/pair loss。证据：`modeling_qwen3.py:507-509`、
`transformers/loss/loss_utils.py:46-68`。

### F.3 能否只计算 yes/no 两个 vocab logits

**不能由当前 stock forward 原生完成**。`lm_head = Linear(hidden_size, vocab_size, bias=False)`，见
`modeling_qwen3.py:447-451`；forward 无 vocab-index 参数。即使 `logits_to_keep=1`，仍先算
`hidden_last @ W_vocab` 得 `[B,1,V]`，调用方再 gather yes/no。

若要只投影两行权重，必须新 wrapper/bypass stock `Qwen3ForCausalLM.forward()`；当前实现没有该 API。本报告不修改模型源码。

### F.4 vocab 与 BF16 logits tensor

本机 `Qwen3Config` 默认 `vocab_size=151,936`，见
`transformers/models/qwen3/configuration_qwen3.py:62`。仅 BF16 logits tensor：

```text
bytes = batch × positions × 151,936 × 2
```

| Batch | positions | tensor-only |
|---:|---:|---:|
| 1 | 4,096 | 1.159 GiB |
| 1 | 8,192 | 2.318 GiB |
| 2 | 4,096 | 2.318 GiB |
| 2 | 8,192 | 4.637 GiB |
| 4 | 4,096 | 4.637 GiB |
| 4 | 8,192 | 9.273 GiB |
| 1 | 1 | 0.290 MiB |
| 2 | 1 | 0.580 MiB |
| 4 | 1 | 1.159 MiB |

这不是训练总显存；不含权重、activation、attention、autograd saved tensors、gradient、optimizer state 或 allocator overhead。

### F.5 tied embeddings

本机库实现：

- `embed_tokens = Embedding(V,H)`：`modeling_qwen3.py:361-363`；
- `lm_head = Linear(H,V,bias=False)`：`:447-451`；
- class 声明潜在 tying mapping：`:442-444`；
- 但 `Qwen3Config.tie_word_embeddings` 默认 **False**：`configuration_qwen3.py:62-75`；
- generic tying 遇到 False 返回空 mapping：`transformers/modeling_utils.py:2531-2539`。

tiny mock 确认默认 False 时两个 Parameter 不共享，显式 True 才共享。由于 Qwen3-Reranker-4B exact config 不在本地，
不能把 library default 冒充 checkpoint-specific 配置；optimizer-state 估算应保留这项 metadata 缺口。

### F.6 tokenizer/template 与 SentenceTransformers

Qwen3-Reranker/Qwen3 tokenizer/config/template 均 not locally available。llama.cpp source fixture 中的 Qwen templates
不是候选 tokenizer contract。

`sentence-transformers` 在 RONDO env、本机 ML env 和 package/cache 中均未安装，RONDO tracked 源码也无 `CrossEncoder`
引用。因此当前本地无法从 package source确认其 exact training API、Qwen score extraction 或 custom loss hook。
引入它会增加一个新直接依赖和 wrapper；直接 Transformers 已暴露 model outputs/custom Trainer 接口。这只是代码表面事实，
不是路线推荐。

## G. Local inference surface

### G.1 当前 exact llama.cpp 资格边界

上一项目的 exact runtime 是 llama.cpp `b10333` / commit
`08659901c43b51de735740f1cf61bb82fbe0c4e4`；见 `eval/rondo_eval/local_approval/launcher.py:34-38`、
`eval/locks/llama-cpp-b10333.json:2-10`。已验证能力只是 exact Ministral GGUF + 12K + `/v1/responses`
结构化文本判定；`eval/locks/local-approval-b10333-ministral-12k-v1.json:1-61` 没有 raw score/logprobs 证据。

### G.2 SequenceClassification scalar server

| 能力 | 当前可复用事实 |
|---|---|
| Python local server precedent | 有 `GuardianBridgeServer`，但它代理 llama.cpp，不加载 Transformers；`guardian_bridge.py:308-422`。 |
| loopback-only | 有：bridge 绑定 127.0.0.1；client 也拒绝非 loopback。 |
| schema validation | 有 approval-specific request/output validation模式；scalar schema需新建。 |
| timeout / retry | upstream client有固定 timeout、`max_retries=0`；bridge handler自身无独立 wall timeout。 |
| body cap | bridge 入站 4 MiB；llama response 1 MiB。 |
| no redirect | 有专用 no-redirect opener并复验 final URL；`client.py:552-568`。 |
| single-slot | llama server强制 `parallel=1`；Python bridge是 `ThreadingHTTPServer`，自身没有 semaphore。 |
| health check | llama `/health` 已用；Python bridge `GET` 一律 404，无自身 health。 |
| identity | `/props`、`/models` + PID/start ticks/command/model/config/listener receipt模式可复用。 |
| lifecycle | C++ child有 watchdog/signal/terminate→kill；Python bridge有 context-managed shutdown/join。 |

RONDO 没有现成 Transformers SequenceClassification launcher。当前 launcher 强制 exact llama.cpp binary、pinned GGUF、chat
template 和 Ministral qualification lock；`launcher.py:956-974,1045-1103,1154-1173`。因此 scalar scorer 可复用的是
工程模式，模型加载、score schema、health、真正单槽和 candidate identity 是 **需要新路径**。

### G.3 CausalLM yes/no 与当前 `/v1/responses`

RONDO 当前 request builder不发送 `logprobs/top_logprobs`，parser只取唯一 `output_text`；见
`client.py:261-309,502-549`、`l6_b10333_pair.py:286-329`。

exact b10333 本地源码的机械事实更强：

- Responses request 会转为 chat body，chat parser 能把 `logprobs/top_logprobs` 转成 top-N probabilities；
  `server-chat.cpp:250-295`、`server-common.cpp:1143-1152`；
- 它提供的是生成 token 的 top-N log probabilities，不是调用者指定 vocab columns 的 raw logits；
  `server-context.cpp:2002-2055`、`server-task.cpp:292-334`；
- `/v1/responses` 非流式和流式 serializer 都把 `output_text.logprobs` 硬编码为空数组；
  `server-task.cpp:556-625`（关键 `:581-588`）、`:653-683`；
- b10333 自带 Responses tests没有 logprobs case；`tools/server/tests/unit/test_compat_oai_responses.py:12-113`。

因此准确结论是：

```text
上一项目未验证
```

并且当前 exact `/v1/responses` envelope 本身不会返回已计算 probabilities。改走 Chat Completions 也不是现成小改：
当前 RONDO Rust provider只有 `WireApi::Responses`，没有 chat wire variant；`multidev/codex-rs/model-provider-info/src/lib.rs:49-83`。
Qwen raw yes/no scorer需要新的 server/API/parser 或直接 Transformers score service，不能把上一轮文本生成资格冒充 raw score 支持。

### G.4 Rust adapter

当前 `team_publish` 无 scorer hook，generic Rust Responses API 也没有 scalar/logprob 字段；见
`publish.rs:34-77`、`multidev/codex-rs/codex-api/src/common.rs:75-123,251-275`。两个候选都需要 Publication
Critic 专用 typed score client、finite-number/schema/identity/timeout/cap/no-redirect 检查和 hook 状态机。Qwen path 还需冻结
tokenizer/verbalizer/scoring identity。

## H. RunPod/full-checkpoint infrastructure

### H.1 bundle、上传与回收

- 现有 train bundle 严格固定为 Local approval 470 条 train-only projection、Ministral model contract、QLoRA recipe、
  dependencies、template 和 runner；`bundle-allowlist-v1.json:2-53`、`l6_training.py:409-534`。新任务必须独立 bundle。
- 上传是 tar + SCP，远端先验 tar hash、解包后再跑 bundle verifier；`stage2-runbook.md:164-224`。传输机制通用，
  allowlist 内容不通用。
- 回收用 `scp -r remote/formal/. local/`，完整下载后 chmod + verify；`:614-642`。它可传任意目录树但无断点续传。

### H.2 artifact allowlist 不是 full-model 合同

路径层面，旧 allowlist允许 `adapter-final/` 和 `checkpoints/` 下任意普通文件，没有 extension whitelist；
`artifact-export-allowlist-v1.json:2-12`。但端到端语义全部写死 adapter：

- final path 是 `adapter-final`；`l6_training.py:1324-1326`；
- reload 使用 `PeftModel.from_pretrained(base, adapter_dir)`；`:1435-1461`；
- receipt output path 固定 `{adapter, checkpoints}`；`:1403-1404,1714-1733,1760-1762`；
- entrypoint 强制 `reload-adapter`；`runpod-stage2-entrypoint.sh:53-57`。

因此旧链路的完成态是 LoRA-specific；不能通过把 full weights 塞进旧目录名就称为支持 full model。

### H.3 hash verifier 与 multi-GB 文件

training artifact verifier不是流式 hash：`_regular_file()` 执行 `path.read_bytes()`，单文件机械上限 32 GiB；
`l6_training.py:155-175,985-1001,1502-1537,1572-1602`。峰值内存至少等于最大 shard，finalize/verify 会重复读取。
当前实证只覆盖约 178 MB adapter 和约 91 MB optimizer 文件，不能宣称已验证数 GB checkpoint。

conversion verifier已有 1 MiB 流式 hash，见 `training/local-approval-l6/conversion_tooling.py:114-138`，但 training artifact
verifier尚未复用。

### H.4 receipt、resume 与 C1/C2/C3

- receipt内嵌 base/tokenizer/chat-template model contract，含 immutable repo revision；
- dependency identity记录七个 package、Python、CUDA、container tag；
- optimizer参数在 allowlisted `actual-recipe.json`，receipt只存 recipe SHA；不单列 optimizer implementation source revision；
- checkpoint tree hash覆盖 optimizer/scheduler/trainer/RNG files；
- generic resume guard + `trainer.train(resume_from_checkpoint=...)` 可抽取，但当前 train仍重建 NF4 base、PEFT prepare、
  LoRA injection，所以实际 resume path是 LoRA-specific；
- 当前 entrypoint只有 smoke/formal，没有 C1→C2→C3 stage machine；
- `save_total_limit=2` 不会长期保留 C0/C1/C2/C3 四阶段。需要独立阶段 output/receipt/retention 合同。

RunPod旧 Pod volume为100 GB；旧本地回收门按35 GiB conservative peak估算。四份 4B BF16权重本身约29.8 GiB，
加入 optimizer/master state、cache和临时副本会超出旧估算。100 GB是否够用取决于 FlashOptim state bits、是否每阶段保留
optimizer state及保存峰值，必须重新做容量门禁；当前 LoRA证据不能回答。

## I. Side-by-side engineering fact table

### I.1 源码改动面粗图

这里的等级只描述相对当前 RONDO 的代码表面，不构成模型排名。

| 模块 | Skywork scalar RM | Qwen3 Reranker raw-logit scorer |
|---|---|---|
| dataset builder | **中等改动**：可复用 hash/split/manifest 模式，但 Candidate/Pair/schema 全新 | **中等改动**：同左 |
| tokenizer/template | **未知/需模型 smoke**：本地无 config/tokenizer/template | **未知/需模型 smoke**：本地无 exact tokenizer/template/verbalizer |
| model loading | **小改 + 未知**：框架有 Auto SequenceClassification；exact Skywork config 未确认 | **小改 + 未知**：本机有 Qwen3 CausalLM；exact 4B config 未确认 |
| `forward_score` | **小改**（条件式）：若 `[B,1]` 则 squeeze；actual head/pooling需 smoke | **中等改动**：`logits_to_keep=1` + yes/no gather；stock forward仍全 vocab |
| Binary loss | **中等改动**：必须 custom；默认 single-label loss是 MSE | **中等改动**：必须 custom；标准 LM labels不适用 |
| pair loss | **中等改动**：concat/split可行，但需新索引/loss合同 | **中等改动**：concat/split可行，但需新索引/loss合同 |
| Trainer | **需要新路径**：无 custom Trainer precedent | **需要新路径**：同左 |
| optimizer | **未知/需模型 smoke**：FlashOptim未安装、无 direct integration | **未知/需模型 smoke**：同左；4B显存需实测 |
| checkpoint | **未知/需模型 smoke**：generic Trainer框架现成，Flash state未知 | **未知/需模型 smoke**：同左且工件更大 |
| offline evaluator | **需要新路径**：共享 score/threshold/parity runner 尚无 | **需要新路径**：同左并冻结 verbalizer |
| local server | **需要新路径**：可复用工程模式，无 SequenceClassification launcher | **需要新路径**：当前 Responses 丢 logprobs/raw score |
| Rust adapter | **需要新路径**：专用 scalar schema/client/hook | **需要新路径**：专用 dual-token score schema/client/hook |
| quantization | **未知/需模型 smoke**：无候选量化资产/路径证据 | **未知/需模型 smoke**：llama.cpp文本生成经验不等于 exact reranker score |

### I.2 最终工程事实并列

| 工程事实 | Skywork 1.7B | Qwen3 Reranker 4B |
|---|---|---|
| 原生 score 类型 | 任务假设是 SequenceClassification scalar；本地 exact config缺失，actual `[B,1]` 未确认 | CausalLM最后位置 yes/no vocab score；stock forward输出全 vocab |
| 当前 Trainer 接入难度 | 框架有 Auto SequenceClassification，但需新 custom loss/Trainer | Qwen3 forward现成，但需 last-position verbalizer score + custom loss/Trainer |
| pair loss 接入难度 | 两端 concat一次 forward可行；新 collator/index/loss | 同样可 concat；输出 `[2B,1,V]` 再 split/gather |
| FlashOptim 本地兼容性 | package absent；5.8.1/5.14.1无 direct integration；unknown | 同左；没有 Qwen-specific incompatibility本地证据 |
| logits 额外显存风险 | 若 scalar head为 `[B,1]`，输出 tensor本身很小；actual model待确认 | 默认 `[B,S,151936]` 很大；`logits_to_keep=1` 降到 `[B,1,151936]`，仍非两列 |
| checkpoint/resume 风险 | generic Trainer可保存；Flash state未知；四权重约12.7 GiB | generic Trainer可保存；Flash state未知；四权重约29.8 GiB且临时/optimizer风险更明显 |
| 本地服务复用程度 | loopback/cap/no-redirect/identity/lifecycle模式可复用；模型server需新建 | llama.cpp process模式可参考，但已验证 Responses不能给所需 raw score；需新score路径 |
| 量化路径当前已有证据 | 无 exact候选资产或量化score证据 | 只有无关模型的 llama.cpp/GGUF文本生成经验；无 exact候选 raw-score/score-drift证据 |
| 需要 paid smoke 的问题 | actual load/head/pooling、4K/8K VRAM、吞吐、Flash训练/恢复、量化drift、C0/accuracy | actual config/verbalizer、4K/8K VRAM、吞吐、Flash训练/恢复、量化drift、C0/accuracy |

## J. Unknowns requiring actual model/GPU smoke

先区分不一定付费的 metadata 缺口：两个候选 exact config/tokenizer/template/revision 均未缓存；Qwen exact
`vocab_size/tie_word_embeddings/yes-no token IDs` 和 Skywork exact auto-class/head/pooling 可在后续受控小 metadata 检查中关闭，
不需要为了这些字段先运行付费训练。本轮没有下载。

以下需要完整模型/目标 GPU；本报告不执行：

| Unknown | 范围 | 结论 |
|---|---|---|
| 真实 4K/8K forward+backward peak VRAM | both | 需要后续 paid smoke |
| 在冻结 batch/accumulation/sequence 下的 tokens/s | both | 需要后续 paid smoke |
| 实际 `$ / M tokens` | both | 需要后续 paid smoke |
| FlashOptim one-step correctness、peak、gradient release组合 | both | 需要后续 paid smoke |
| FlashOptim checkpoint `state_dict()`、独立 reload/resume parity | both | 先可做 package-level无费smoke；候选完整恢复需要后续 paid smoke |
| Qwen stock full-vocab last-position projection的真实额外峰值 | Qwen | 需要后续 paid smoke |
| 量化后的 score/threshold drift | both | 需要后续 paid smoke |
| 真实 hard-slice accuracy / false-pass / false-rewrite | both | 需要后续 paid smoke |
| C0 prior | both | 需要后续 paid smoke |
| 少量监督 sample efficiency | both | 需要后续 paid smoke |
| C1→C2→C3遗忘与收益 | both | 需要后续 paid smoke |
| 本地 RTX 4060 Laptop 8GB scalar/raw-score latency与稳定性 | both | 需要后续 paid smoke |

本轮没有产生可支持模型优劣、benchmark 胜负或最终选型的实测证据。
