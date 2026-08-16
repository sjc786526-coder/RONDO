# Plan 037：L6 首轮 LoRA 微调与本地成对输出闭环

> 本计划是本任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，执行期间默认不得修改。
> 若必须改变目标、范围、硬约束或完成标准，应暂停并请求用户确认。
> 本计划只处理首轮 L6 训练、成对本地工件和 130 条 synthetic validation 输出；后续正式 Local M4
> 只由 `doc/WBS.md` 与 `doc/WBS/local-approval-model.md` 安排。

## 1. 目标

### 最终目标

使用 L5b 冻结的 470 条 synthetic train 完成首轮有效 SFT/LoRA，在官方
`mistralai/Ministral-3-8B-Instruct-2512-BF16@f6fae9795746f63c9be8344932f01275f3c63734`
谱系上形成可由本地冻结 b10333 串行加载的 `local-static` / `local-ft-static` 成对工件；两侧以同一模板、
request、sampling、12k 服务参数和结构化输出合同运行全部 130 条 frozen synthetic validation，并通过
Plan 036 的完整三方导入与 canonical L6 pair receipt 校验。

本任务不运行 Opus 裁判，不读取真实 holdout，不形成 Local M4 质量结论，也不因 validation 表现继续调参或训练
第二个有效 recipe。

### 阶段划分与授权门

本任务分为两个连续阶段。阶段一只做本地准备；阶段一提交并经用户/审查者验收后，用户另行给出阶段二授权，才可创建
RunPod 资源、上传 train-only bundle 或开始任何付费 GPU 工作。制定本计划、发送阶段一提示词或完成阶段一，均不构成
阶段二授权。

- **阶段一：本地准备与审查。** 在不创建/启动/修改任何 RunPod 资源、不上传任何任务数据、不产生本任务云费用的前提下，
  尽可能完成数据投影、token/template 检查、completion-only loss 测试、候选 recipe/依赖锁/镜像方案、启动/持久化/
  回收脚本、本地可行的轻量 dry-run、RunPod body-free 容量/价格预案和 focused tests。完成后只提交任务 worktree，
  停止并交审。
- **阶段二：RunPod smoke、正式训练与本地闭环。** 仅在新授权覆盖具体预算上限和远端动作后执行。允许真实 GPU/驱动、
  显存、镜像或 RunPod 环境暴露问题时做有原因的窄修和有界重跑；目标是减少可避免的云端调试，不是要求云端零试错。
  候选 recipe 可依据真实 optimizer smoke 做一次有证据的技术收敛，最终 recipe 在正式训练开始前冻结；若需要改变冻结
  base、数据边界、训练目标、核心路线、阶段二批准预算或启动第二个质量 recipe，必须停止并重新请求授权。

### 最终完成/验收标准

- [ ] 训练投影精确来自 frozen `train.jsonl` 的 470 条记录；上传清单不含 validation、真实 seed、holdout、真实
      `E_final` 或其他私有正文，直接相关 pure tests 证明该边界。
- [ ] 用冻结 tokenizer/template 对 470 条最终训练序列完成精确 token 统计；receipt 记录 min/max/P50/P95、上限和
      超限数，实际训练无未记录截断。
- [ ] completion-only loss 通过可执行测试或 smoke 证据证明：输入/prompt token 不计入 labels，target assistant
      token 计入 labels，非空 completion 不被全部 mask。
- [ ] 真实 smoke 至少完成一个 optimizer step、保存 adapter 并在新进程或等强隔离后成功重载；本地不适合时可在
      阶段二 RunPod 完成。
- [ ] 一个冻结 recipe 的正式 LoRA 训练有效完成；adapter、必要 checkpoint、实际配置、依赖身份、聚合训练指标和
      training receipt 已在 RunPod 销毁前保存并验真到本地 ignored 目录或阶段二明确批准的私有 HF repo，任务完成前
      必须下载到本地 ignored 目录复核哈希。
- [ ] RunPod 本任务累计实际费用不超过阶段二批准上限且绝不超过 25 USD、GPU Pod 并发始终为 1；任务结束时没有仍在
      运行的计算或未经授权持续计费的存储资源，所有 task-only 远端对象及获准保留资产的最终状态/费用均已确认。
- [ ] 未微调与微调后两种本地工件来自同一官方 BF16 base lineage，且 b10333 能以同一 runtime、chat template、
      request、sampling、12,288 context、512 output 和 decision schema 合同串行加载。
- [ ] 两侧对 frozen 130 条 synthetic validation 各形成 130 条且每样本唯一的最终记录；allow/deny、结构化失败、
      超时或明确拒绝均按实际终态记录，不伪造业务判定补齐结果。
- [ ] canonical L6 pair receipt 与本地输出通过 Plan 036 正式完整导入；`sol-static` 只来自 frozen validation target，
      Plan 033 Bartowski GGUF 不冒充本次 `local-static`。
- [ ] focused tests、真实训练/本地运行 preflight、私有文件权限与哈希检查、tracked 敏感/大文件检查以及
      `git diff --check` 通过；skip 或未运行项不写成通过。
- [ ] 本地模型进程、端口和 GPU 显存清理完成；WBS 只在上述事实齐全后把 L6 标为完成，并把下一产品工作指向正式
      Local M4，不提前写 M4 质量结论。
- [ ] 任务分支形成少量清晰本地提交，停在未合并、未推送、待独立验收状态。

### 阶段一交审标准

- [x] train-only 投影、上传 allowlist/body-free manifest、470 条精确 token census、completion-only mask 和数据隔离
      focused tests 均已完成；validation/holdout 未进入训练投影、上传包、梯度或 recipe 选择。阶段一允许普通工具遍历
      validation，以及用少量 fixture 验证结构和导入兼容性，但不运行完整 130 条模型质量比较。
- [x] 训练/转换/回收脚本、候选 recipe、候选依赖锁与容器/镜像方案、输出目录和 receipt 结构已落地；明确哪些参数/依赖
      允许依据阶段二真实 smoke 做技术收敛。无需真实 8B GPU 的部分已用小 fixture、mock 或本机可承受的 dry-run 验证，
      未把它冒充真实 optimizer smoke。
- [x] 已形成可执行的 RunPod 启动包与 train-only 上传包，记录精确文件清单/哈希；数据传输、模型定版下载、日志监控、
      adapter 回收和任务 Pod 终止路径均已说明并可在阶段二直接操作。
- [x] 基于阶段一结束时 RunPod 只读容量/价格/可用余额事实，汇报建议显卡、显存、选择理由、单价、容器/卷大小、smoke/
      训练/转换/回收各段预计时长、总预计与最坏运行时长、最坏费用、重试余量、止费点和建议的阶段二授权上限；控制面
      无法读取可用余额时明确记录，留待阶段二授权时由用户确认。若无法把最坏费用控制在 25 USD 内，应在此处报告而非
      创建 Pod。
- [x] 若建议使用私有 HF 产物仓或 RunPod task-only template、registry credential、volume/network volume，阶段一报告
      必须说明用途/收益、准确对象、生命周期、费用与风险；未列入阶段二授权的对象不得创建。
- [x] focused tests、preflight、敏感/大文件与 `git diff --check` 通过；工作树提交后停止，明确列出未运行的真实 smoke、
      正式训练与 130 条本地输出，等待用户阶段二授权。

## 2. 范围

### 允许修改

- `plan/037-l6-first-lora-paired-artifacts-execplan.md` 的“当前状态”和“关键决策记录”。
- `training/` 内最低必要的 L6 数据投影、recipe/依赖合同、训练脚本、body-free manifest/receipt schema 与说明；
  frozen L5b 正文只读，不改写。
- `eval/rondo_eval/local_approval/`、`eval/templates/local-approval/` 和 `eval/tests/` 内直接服务于训练投影校验、成对
  b10333 本地运行、终态记录及 Plan 036 导入的轻量实现和 focused tests。
- 对 Plan 036 当前只接受 allow/deny 的 live 表达缺口，可在 `eval/rondo_eval/local_approval/cross_eval.py`、
  `eval/templates/cross-eval-judge/` 和对应测试内做最小、版本化终态兼容扩展；不得改弱既有 decision、identity、
  完整性或盲化校验，也不得改变 frozen cohort 和 65 / 65 分批。
- 任务完成时精炼更新 `training/README.md`、`doc/eval-data-layout.md`、`doc/WBS.md`、
  `doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md` 和一份 `agent_log/`。
- 主工作区 `/home/sjc/desktop/RONDO/eval-data/local-approval/l6/` 与
  `/home/sjc/desktop/RONDO/eval-data/cross-eval/<execution_id>/` 下的任务专用 ignored 私有目录，以及现有 ignored
  b10333 runtime/model 资产的只读使用；真实权重、adapter、输出和私有 receipt 均留在 ignored 区。
- 阶段二新授权后的任务专用 RunPod 单 GPU Pod 生命周期（任一时刻至多一个），以及授权中列明的 train-only 上传、
  短 smoke、一次有效正式训练、必要转换、产物回收和 task-only 资源终止；可在普通技术失败后做有原因的窄修重试，
  必要时可在先终止失败 Pod 后创建替代 Pod，但预算和单并发边界不变。
- 阶段二授权中逐项列明的 task-only RunPod template、私有 registry credential、volume/network volume；默认只建 Pod，
  阶段一说明具体用途/收益并由用户批准后即可采用。
- Hugging Face 可作为冻结官方 base/tokenizer 的只读来源；阶段二也可在当前 namespace 创建一个私有 model repo，
  仅持久化本任务生成的模型/adapter/必要 checkpoint、转换工件、实际配置、聚合指标、manifest 和 receipt。HF 不得承担
  smoke、训练、转换或推理，不得上传 train、validation、holdout、真实数据或本地逐样本输出。

### 不允许修改

- `mydev/`、`multidev/`、生产 Guardian 路由、现有 b10333 qualification、Plan 033 baseline、既有 shadow 结果、
  `eval/results/runs.jsonl` 或既有 `rondo.local.toml`。
- `training/local-approval-synthetic-v1/train.jsonl`、`validation.jsonl`、manifest、schema/prompt/data card 等 L5b
  frozen 资产；Plan 032/033/034/036 历史 plan 的稳定正文。
- Codex/llama.cpp 上游基线、宿主机或全局工具链、CI/PR、公开 Hub/RunPod 资产、长期在线服务、定时任务或
  Inference Endpoint；不得创建 RunPod Serverless endpoint、cluster 或阶段二授权清单外的 volume/template/credential。
- 主工作区已有 tracked 文件、全部既有研究文档、其他 worktree 与来源不明的既有
  ignored 资产。

### 敏感凭据、真实秘密与普通项目数据

- `.env.local` 的内容、HF/RunPod/SSH/registry 等 token、私钥、密码和其他凭据按严格秘密处理；只能按根规则静默检查
  `.env.local` 文件存在、非符号链接、权限 0600 和任务所需变量非空，禁止 source、搜索、打印、复制或记录值，
  也不得运行 `hf auth token`。意外发现的真实个人身份信息或未公开第三方秘密适用同一保护。
- tracked synthetic train/validation、TB 题目、fixture、schema、prompt、合成教师标签及不含凭据的 manifest、receipt、
  指标和模型配置属于普通项目数据，不是隐私或秘密；普通搜索、格式检查和工程工具遍历 validation 不构成失败。
- 模型权重、adapter、GGUF 和逐样本原始输出同样不因内容本身被视为秘密，但仍因仓库体积、资产落点和实验边界不得
  进入 Git。Plan 032 holdout 与真实 `E_final` 不属于本任务训练或 synthetic validation 闭环：不得进入梯度、上传或
  本任务质量判断，也不得运行正式 holdout 测评。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

### 3.1 数据隔离与训练投影

1. 训练数据宇宙只能是 frozen `train.jsonl` 的 470 条（SHA-256
   `1e66c06e9357a3b6e14aedd193c5405ad2c18924e57da6a3a209f079b80c110a`）。执行者可从这 470 条内部做
   group-safe 监控划分，或只记
   training loss，但必须记录实际进入梯度与监控的数量/分组；validation、真实 seed、holdout 和真实 `E_final`
   不得影响梯度、recipe、超参、checkpoint 选择或重训决定。
2. 训练上传采用明确 allowlist 和 body-free manifest。云端只允许收到 470 条 train、必要 schema/模板/tokenizer 合同、
   训练/转换脚本及 manifest；测试必须拒绝 validation/holdout 路径、未知文件、symlink 和清单外正文。validation 的
   普通搜索、结构查看、格式解析或少量接口 fixture 不得改变这条上传边界。
3. validation 不得进入训练投影、梯度、超参数/recipe/checkpoint 选择或是否重训的判断。阶段一可做不分析模型质量的
   schema/解析/导入兼容检查；完整 130 条成对模型输出仍只能在正式训练终态、最终 recipe 与 training receipt 冻结后
   执行。本任务不把真实 holdout 正文用于训练、上传或质量判断，也不运行正式 holdout 测评。

### 3.2 模型、模板与训练有效性

1. 训练 base 固定为官方 BF16 repo/revision；tokenizer 文件必须来自明确冻结 revision 并记录文件哈希，chat template
   绑定现有 lock 的 `mistralai/Ministral-3-8B-Instruct-2512@5b26027e7b19eeb4b7352e1fed3926375dd2cb4d`
   与 SHA-256 `74eeb55fd3341286ec3fd44e902b7120721acc81cd394e96b431f85e93a1ea56`，不得从远端 `main`
   静默解析任一资产。
2. 所有训练输入必须用正式模板与 tokenizer 精确渲染/计数；若序列超出 recipe 上限，先调整合法 recipe 或定位数据，
   不得静默 truncate。阶段一形成 packing、rank、文本层 target regex、学习率、batch、累积、epoch/max steps、量化方式和
   依赖组合的候选方案；target regex 经实际模块范围验证后作为视觉隔离边界固定，不在 smoke 后漂移。其余明确列入
   `smoke_adjustable_once` 的参数可依据显存与兼容性做一次有证据的技术收敛，并在正式训练开始前冻结最终 recipe/依赖。
   该收敛不得改变 base、训练数据、completion-only 目标或演变为第二套质量 recipe。
3. 正式训练前必须以真实 optimizer step + adapter reload 证明数据映射、completion-only mask、模型/PEFT 组合和持久化
   路径成立。普通依赖、OOM、映射、target module、保存或基础设施问题先根因定位、窄修后合理重试，不因第一次失败
   结束；不得无差别重放同一失败命令。成功 smoke 前为使同一候选路线跑通所需的普通窄修不按“第二 recipe”计数；
   最终 recipe 一旦进入正式训练便不得再以质量为由改配重训。
4. “一个有效正式训练”以 frozen recipe 对声明的 470 条 train universe 完成预定训练、产出可重载 adapter 且训练
   receipt/指标持久化为准。达到该状态后禁止因 loss、validation 或主观质量不满意再跑第二个 recipe；此前因明确技术
   失败产生的有界重试不视为第二个有效 recipe，但必须计入费用和记录根因。训练 receipt 至少绑定 base/tokenizer/
   template、train hash/count、投影/脚本/依赖/recipe、provider/job/hardware、实际步数与聚合 loss、终态、持久化
   revision、产物哈希和费用。

### 3.3 两阶段授权、RunPod 预算与持久化

1. **阶段一禁止云端变更。** 可只读查询 RunPod 文档、GPU catalog/capacity/价格和现有本任务相关状态以形成预案，但
   不得调用 create/start/stop/restart/delete，不得创建 Pod/volume/template/registry credential，不得上传 train 或其他
   文件，也不得创建/修改 HF repo 或产生本任务费用。阶段一结束必须提交并停下，由用户/审查者先验收。
2. **阶段二计算只使用 RunPod。** 用户另行批准阶段一结果和具体预算上限后，才可按需创建任务专用单 GPU Pod（任一时刻
   至多一个），完成真实 smoke、一次有效正式训练、必要转换和产物回收。默认远端对象只有 Pod；阶段一说明并由阶段二
   授权逐项列明时，可创建 task-only template、私有 registry credential 或临时 volume/network volume，以及一个私有
   HF model repo 作为非计算持久化目标。不得使用 HF Jobs/Endpoint/Space 计算或切换其他计算供应商；H100、多 GPU、第二个
   有效 recipe、公开资产或预算扩张均需新授权。普通依赖、镜像、驱动、OOM、脚本、保存或临时网络问题可先定位、窄修
   并在批准预算内合理重试，不要求云端零试错，也不得无差别重复同一失败操作。
3. 阶段一必须用 live 价格和容量形成 body-free 预算表；阶段二创建 Pod 前再复核 GPU、实际单价、磁盘/卷费率、强制
   最长运行时间、预计与最坏费用、已结算费用、实时可用余额和修复余量。若 MCP/控制面不能可靠返回可用余额，应在
   创建 Pod 前明确报告，并由用户在阶段二授权中确认余额，而不是默认仍有 25 USD。有效总上限取 25 USD、用户阶段二
   批准额和当时确认的可用余额三者中最小值，并在其中保留完成回收/止费所需余量；任何时刻只允许一个本任务单 GPU Pod。
   若“已花费 + 当前运行保守上界 + 完成所需最坏费用”接近有效上限、余量不足以安全完成，应在越线前保存可恢复状态、
   止费并及时报告，不能靠余额耗尽自动停机。
4. **阶段二付费动作前先报告。** 阶段一交审报告必须列出拟选显卡/显存、选择理由、live 单价、smoke/正式训练/转换/
   回收的预计分段时长、总预计与最坏运行时长、磁盘/volume 费用、最坏总费用和止费点，用户据此批准阶段二。真正创建
   资源前再次复核；若显卡、价格、时长、附属对象或最坏费用相对批准内容有实质变化，先报告更新并等待确认。Pod 创建后
   再报告 Pod ID 与实际单价，然后在同一活动任务中持续主动读取 container/system logs、Pod 状态和阶段性 billing，及时
   识别无进展、反复崩溃、OOM、错误数据/recipe 或费用偏离；不得把“已创建/已提交”当作完成。
5. **存储费用单列。** RunPod network volume 费用计入 25 USD RunPod 总上限，并按阶段一确认的容量、tier、费率和预计
   保留时长单独列项；默认在产物另有验真副本后删除 task-only 临时 volume，若要长期保留必须再授权持续费用。HF 私有
   repo 创建本身不等于已确认免费：阶段一须只读核对账号类型、现有私有存储用量、预计上传量和是否落在 included quota。
   若会触发 HF 订阅、pay-as-you-go 或任何新增费用，实际创建/上传前必须单独说明金额和计费周期并取得新授权；未获该
   授权时 HF 本任务新增实际费用必须为 0 USD，且不得用 RunPod 的 25 USD 余额概念掩盖 HF 的独立账单。
6. 远端数据和产物必须私有。RunPod 训练输入仍限 470 train allowlist；HF repo 只接收阶段二批准的任务生成工件 allowlist，
   不得接收 train/validation/holdout/真实数据或本地逐样本输出。终止 Pod 前，adapter、必要 checkpoint、实际配置/依赖、
   聚合指标和 training receipt 必须至少在本地 ignored 目录或已批准的 HF 私有 repo 有一份哈希验真的持久副本；任务完成
   前再下载到本地复核。`stop` 只作为临时止 GPU 费/保数据手段，最终应终止/删除**仅本任务创建的**临时 Pod、template、
   credential 与不再需要的 volume，确认不再计费；获准保留的 HF 私有产物仓不删除，不得触碰用户既有远端资产。

### 3.4 成对本地工件与 130 条输出

1. `local-static` 与 `local-ft-static` 必须共享同一官方 BF16 base lineage、tokenizer、template、conversion/quantization
   路线、b10333 runtime、12k 服务参数、request、sampling 和 output contract。可选择同一新 base GGUF 的 adapter
   on/off，或同源成对 GGUF；Plan 033/Bartowski 工件只作历史部署参考。
2. 两侧必须顺序加载，不能同时驻留 GPU。先做少量结构化输出 smoke，再按同一确定顺序运行全部 130 条 validation；
   两侧都冻结 temperature 0、top_p 1、seed 42，并共享当前 qualification identity 中除 model/adapter 身份外的完整
   serving contract；不因某侧中途表现调整另一侧输入、参数或重试策略。
3. 每个样本每侧只能进入一个诚实终态。基础设施启动失败可在进入样本集合前修复；样本级 allow/deny、结构化失败、
   超时或拒绝均作为事实保存，不能改写为假 decision。live Plan 036 v1 无法表达非判定终态，因此本任务必须做最小、
   版本化的 terminal union/importer 兼容，并以 mixed-terminal fixture 证明导入及后续匿名候选表示不补造 decision；
   既有 v1 decision、130 条 cohort identity 和 65 / 65 分批保持不变。
4. canonical pair receipt 的 base、两种工件和 training receipt 身份必须由 runner 从实际 regular file、冻结 lock 或
   含全部组件哈希的 canonical deployment manifest 计算，不能接受调用方随意自报字符串。两侧 manifest 必须绑定
   b10333 实际加载的 GGUF/adapter 与 converter、quantizer、quantization；微调侧还要绑定 formal source adapter tree。
   私有 evidence locator 只能通过重新读取这些实物恢复正式导入能力。正式三方导入精确覆盖 `130 × 3` 个 sample-side，
   不缺、不重、不混分区；本任务不继续打 Opus 裁判包，也不运行正式 Local M4。

### 3.5 本地资源、安全与 Git

1. 下载/转换前重新读取 Windows `C:` 实际余量、项目占用和预计峰值；不得用 WSL 虚拟余量满足门禁。保持 Docker、
   重型 Cargo 与真实本地模型加载互斥；本任务无必要不运行 Docker/Cargo。容量不足或无法读取宿主实际余量时停止重型
   本地步骤，不靠删除来源不明资产腾空间。
2. 不调用 Sol、Opus 或任何真实模型 API；RunPod 控制面只用于对应阶段已授权的操作。HF 控制面不得用于计算，私有 repo
   也只能执行阶段二批准的 create/upload/readback；HF 凭据只经现有安全登录或 secret 注入传递，`hf auth token`、token/
   secret 搜索或打印始终禁止。模型推理只在阶段二任务 Pod 的 smoke/训练辅助步骤或冻结 b10333 本地服务中进行。
3. linked worktree 不共享 ignored 数据。tracked 代码与文档只在本 worktree 修改；真实模型、runtime、private output
   和 receipt 使用明确的主工作区任务目录，不建 symlink、不把 ignored 正文复制进 Git，也不修改主工作区 tracked 文件。
4. 权重、adapter、checkpoint、原始输出、私有 receipt、密钥、机器配置和云端身份信息不得进入 Git。私有目录 0700、
   普通文件 0600；最终检查 tracked 大文件/敏感字段、所有 worktree 状态和意外生成物。
5. 只跑直接相关的 Python/pure tests、真实训练 smoke、必要本地模型 smoke/130 条输出和正式 preflight；不跑全量 eval、
   重型 Cargo、CI 或 PR。完成后停止服务、释放端口、确认显存回落，并只提交任务 worktree 分支，不合并、不推送、
   不删除 worktree、不重命名分支。

## 4. 软性建议

以下内容是基于当前仓库与环境的实现建议，不是固定路线。执行者可依据实际依赖、RunPod MCP 能力、GPU 和运行结果
采用更简单或更稳妥的等强方案。

- 优先保持两块轻量设施：一个训练投影/recipe/receipt 模块，一个复用现有 b10333 launcher/client 与 Plan 036 schema 的
  paired-output runner；不建立训练平台、数据库、签名链或通用数据治理框架。
- 阶段一尽量用 5—10 条 train、同格式小模型或 mock 完成不会误导的 pipeline dry-run；当前机器为 RTX 4060 Laptop
  8GB，若完整 BF16/真实 adapter optimizer step 明显不适合本机，则把真实 smoke 留给阶段二 RunPod，不为本地绿色而
  换底模或改训练合同。
- 阶段一只需把最可能成功的候选 recipe/依赖/镜像和备选技术参数准备清楚；target regex 在阶段一先按 runtime 文本模块名
  fail-closed，阶段二 smoke 再证明实际注入、batch、量化和真实依赖可运行。允许在 allowlist 内做一次集中技术收敛，
  正式训练启动才是最终冻结点。
- 优先让一个 RunPod Pod 顺序完成短 smoke、正式训练和必要转换，以减少反复拉模型/启动；若实际兼容性或持久化风险令
  拆分更稳妥，也可在同一阶段二预算内有理由地调整。GPU 型号、镜像、磁盘和最长运行时间以阶段一结束时的 live
  RunPod 事实为准，不在计划里预先锁死。
- 默认保持远端对象最少；若 task-only template、registry credential 或 network volume 能减少重复启动/下载或保护
  checkpoint，可采用阶段一说明、阶段二列名授权的方案。标准 network volume 优先，高性能 tier 只有在 I/O 证据与预算
  支持时使用；任务结束默认删除临时 volume，不把 RunPod 当长期仓库。
- 阶段一应把 train bundle 和脚本真正准备到可传输状态，并先验证传输/启动方案；但不要求为了“零云端调试”在本机
  下载不必要的完整 BF16 权重。HF 只读下载必须指定 revision 与文件范围，禁止静默使用远端 main。
- 数据和产物传输可按实际网络与工具选择 RunPod 官方支持的 `runpodctl`、SCP/rsync、network volume 的 S3-compatible
  接口或已批准的私有 HF repo；阶段一应固定命令形态、allowlist 与目标路径，阶段二对传输前后文件做哈希核对，不需要
  为此建设通用对象存储层。
- TRL/Transformers/PEFT、量化训练、Trackio、checkpoint 频率和内部监控 split 均由执行者选择。Trackio 私有配置不顺时，
  使用 Pod 日志加私有聚合指标文件即可。
- b10333 实际支持且最简时优先 adapter on/off；若 loader/转换兼容性不稳定，可从同一 BF16 谱系用完全相同的 converter、
  quantizer、quantization 和校准输入生成成对 GGUF。选择后把命令、版本和哈希写进 receipt，不预先偏好某一种。
- 对 Plan 036 的兼容工作只解决真实终态表达、完整导入和后续匿名候选对“无合规输出”事实的如实表示，不借机重构
  盲评设施或改变裁判语义。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已按实际执行基线 `7a53a56662904eb43a857b57a90adc8713ff2bda` 接管专用 worktree。该 worktree
  源自当时的 `main@8250c4ddec991b16a2cd2e5881256b4870489946`；并行任务后续已把主工作区
  `main` 推进到 `4ebf62d204f0f3926d256532600938916e8979ca`。主工作区已有 tracked 文件、既有研究
  文档、038 worktree 和其他来源不明资产均保持不动。
- 阶段一接管时误执行一次仓库依赖关键词盘点：
  `rg -n "dependencies|optional-dependencies|pytest|unittest|transformers|torch|peft|trl|huggingface" pyproject.toml eval training uv.lock requirements*.txt`。
  该普通搜索遍历了 tracked synthetic validation；当时 `git status` 仍干净，随后复核 train/validation SHA-256 仍分别为
  `1e66c06e…110a` / `cbab8084…8dd2`。validation 没有进入训练投影、上传包、梯度或 recipe 选择；按用户补充授权，
  这不构成隐私泄露或训练污染，无需重建数据或增加访问审计。
- frozen train `1e66c06e…110a` 已确定性投影为 470 条，投影 SHA-256 为 `0026cddd…c14`。最终 train-only
  bundle manifest / tar SHA-256 分别为 `e429ca57…56ad` / `45f098d6…018c`；固定 allowlist 拒绝 validation、
  holdout、未知文件、symlink、清单外正文和连同自改 manifest 一起加入的额外文件。
- 冻结官方 tokenizer/template 对 470 条最终序列的精确 census 为 145,360 tokens（prompt 128,545，completion
  16,815），min/P50/P95/max = 278/311/331/333，limit 4096，超限 0；无 packing、无截断。470/470 prompt
  labels 全为 `-100`，470/470 completion 非空且有未 mask token。census receipt SHA-256 为 `fdb96728…4155e`。
- 候选 QLoRA recipe、7 个直接依赖 pin、RunPod entrypoint、checkpoint resume、adapter 隔离重载、pending→completed
  receipt、逐文件 artifact export/download 验真和超时/监控/止费说明已落地。候选 image 为
  `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`；本地 mock 不加载模型且 optimizer step 为 0。
- Plan 036 前置已版本化支持 decision / structured-output failure / refusal / timeout / infrastructure failure，非 decision
  不伪造成 deny；两侧 canonical b10333 deployment manifest 同时支持 adapter on/off 与 paired GGUF，绑定实际加载工件、
  共同转换/量化身份及 formal source adapter tree。formal v2 的文件入口通过 0600 private evidence locator 重建
  BuiltPairReceipt 并重新哈希七项 source；`verify-import`、`pack`、`import-results` 共用该路径，既有 v1 语义保持兼容。
  attempt-first、终态 fsync journal 的悬空 attempt 可显式收敛后继续剩余样本且不重调。
- 最终 focused unittest 75/75 通过；真实 no-model preflight 仍为 130 条、65 / 65、26 + 26 groups，
  `waiting_for_l6_outputs`；精确 census 重算逐字一致、mock dry-run、bundle 解包后自校验、`py_compile`、entrypoint
  `bash -n`、JSON 解析、候选依赖解析、敏感/大文件/权限检查和 `git diff --check` 均通过。训练与 pair 各完成两轮
  独立审查，已关闭发现且没有阶段一阻断。
- 2026-08-15 约 21:55–22:04 PDT 的只读控制面快照：Secure A40 48 GB 为推荐项，live `$0.44/h`、High；
  RTX A6000 48 GB `$0.53/h`、Low，L40S 48 GB `$0.99/h`、Low/Medium 波动，A100 PCIe 80 GB
  `$1.39/h` 但不可用。RunPod 余额 `$25`、current spend `$0/h`，本任务 billing 增量 `$0`。
- 推荐阶段二只创建 1 个 task-only A40 Pod，40 GB container disk + 100 GB Pod volume，不建 network volume、
  template 或 registry credential；预计 Pod 计费 2.5–4 h / `$1.15–1.84`，10 h 最坏 `$4.59`。建议授权上限
  `$12`，`$8` soft stop、`$10` hard recovery line、A40 10 h 强制终止。若选择支持 network volume 的 L40S，
  需阶段二另行点名授权，8 h 含 100 GB standard network volume 约 `$8.04`。
- HF 只读身份为 personal namespace `WHU-SJC`、非 PRO、可见 repo/bucket 用量为 0；官方 Free private quota 为
  100 GB，但账号设置端点 403，无法从控制面精确证明剩余字节。建议条件式创建私有
  `WHU-SJC/rondo-local-approval-l6-20260815`，预计仅上传 adapter、必要 checkpoint、Q4 GGUF、实际配置/依赖、
  聚合指标/manifest/receipt 共 6–8 GB，预计新增费用 `$0`；若创建/上传前不能确认落在免费 quota，跳过 HF 上传并
  直接回收到本地，不开订阅或 pay-as-you-go。
- 阶段一没有创建/修改/删除任何 RunPod/HF 对象，没有上传、产生新增费用、下载 base 权重、加载 8B、训练、转换、
  调用真实模型/API，亦未运行完整 130 条成对输出或正式 holdout 测评。

### 当前工作

- 阶段一审查窄修已完成并提交任务分支；当前停止在用户审查与阶段二单独授权门前。

### 本任务剩余步骤

- **授权门：**用户/审查者先验收阶段一提交，再逐项批准 task-only Pod、train-only 上传、条件式 HF 私有 repo、
  预算上限和任何可选附属对象。
- **阶段二：**在 RunPod 完成真实 optimizer smoke 与隔离 adapter reload；根据显存/兼容性证据只做一次允许范围内的
  技术收敛并冻结 final recipe/dependencies；完成一个有效正式训练、转换、持久化、下载验真、同源 pair 两侧各
  130 条输出和 Plan 036 正式导入，随后清理所有 task-only 远端对象。

### 阻塞项

- 阶段一无阻塞。阶段二授权尚未给出，这是有意的授权门而非失败。

### 当前验收状态

- 阶段一交审项全部满足；真实 8B optimizer smoke、adapter 真实重载、正式训练、转换、HF 上传、本地成对推理、完整
  130 条输出和正式 Plan 036 导入均未运行，不能表述为通过。

### 交接边界

- 阶段一提交后停止修改和远端操作。用户若单独授权阶段二，执行者按本计划的真实 receipt、产物哈希、运行终态、
  预算/止费和 Plan 036 导入继续；若没有新授权，只保留本地候选与 ignored 工件等待审查。
- 整个 Plan 037 完成后冻结本计划；下一步只由 WBS 指向正式 Local M4。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 037 从本地 `main@8250c4d` 建独立 worktree，只提交任务分支 | 保护主工作区未知修改并遵循仓库交付流程 | Git / worktree | 已采纳 |
| 002 | RunPod 是唯一训练/转换计算后端；HF 可作冻结官方资产来源及阶段二批准的私有产物仓 | 保持计算归因单一，同时允许先远端持久化降低 Pod 等待和产物丢失风险 | 云端执行 | 已采纳 |
| 003 | 官方 BF16 revision、冻结 tokenizer 文件和现有官方 chat template lock 分别显式绑定 | 训练与 b10333 推理不能静默消费远端 main 或旧 GGUF 内嵌模板 | 模型身份 | 已采纳 |
| 004 | adapter on/off 与成对 GGUF 均保留，由 b10333 实际兼容性决定 | 两条路线都能满足同源公平比较，预先写死会增加失败面 | 本地 pair | 已采纳 |
| 005 | 用 train-only allowlist + body-free manifest + focused tests 证明隔离，不建设复杂审计系统 | 这是阻断 validation/holdout 外发和训练泄漏的最小充分设施 | 数据边界 | 已采纳 |
| 006 | 非判定终态按事实保留；只有真实出现且 Plan 036 无法表达时才做最小版本化扩展 | 不能伪造 decision，也不为假想分支提前扩建框架 | 输出/导入 | 已采纳 |
| 007 | tracked 工作留在 worktree，模型/输出等 ignored 实物使用主工作区明确任务目录 | linked worktree 不共享 ignored 资产，现有 b10333 和 GGUF 也在主工作区 | 文件布局 | 已采纳 |
| 008 | 任务以阶段一“本地准备并停下交审”和阶段二“另行授权后 RunPod 执行”分门 | 尽量在计费前消除可本地发现的问题，同时保留真实云环境下合理窄修空间 | 授权 / 成本 | 已采纳 |
| 009 | Pod 运行期间由同一活动任务持续读取日志、状态和 billing，回收验真后终止 task-only Pod | 长训练不能以已提交代替完成，且 stop 后仍可能存在存储费 | 监控 / 止费 | 已采纳 |
| 010 | 阶段一只形成候选 recipe/依赖/镜像；真实 smoke 后允许一次有证据的 allowlist 内技术收敛，正式训练启动前冻结 | 本地无法证明真实 8B optimizer、显存和云端依赖兼容性；文本 target regex 已在阶段一固定 | 训练 recipe | 已采纳 |
| 011 | 私有 HF 产物仓与 task-only template/credential/network volume 可选，阶段一说明、阶段二逐项授权并单列费用 | 保留更稳妥的启动与持久化路线，同时避免无边界远端状态 | 远端资产 | 已采纳 |
| 012 | tracked synthetic/TB 数据按普通项目数据处理；validation 可被普通工具和兼容测试读取，但不得进入训练、上传或训练决策 | 保留训练归因所需的最小卫生，避免把普通合成数据隐私化或扩建审计体系 | 数据分类 / 隔离 | 已采纳 |
| 013 | 阶段二主路线为 Secure A40 48 GB + 40 GB container disk + 100 GB Pod volume；不建 template/credential/network volume，条件式 HF 私有 repo 只作产物持久化 | 当前 live 价格、容量与 470 条 token 规模下成本最低且余量充足；A40 可用区当前不支持 network volume | 资源 / 预算 | 阶段一候选，待阶段二授权与创建前复核 |
| 014 | 候选 QLoRA 为 rank 16、固定文本层 regex target、LR 2e-4、batch 1 × accum 8、2 epochs、NF4 4-bit、无 packing；target regex 属安全边界不允许 smoke 后漂移，loader/attention、rank、batch/accum/LR、epochs/max steps/max sequence length 和依赖允许一次有据收敛 | 本地能证明格式/mask与 runtime 模块范围，但不能证明真实 8B 显存和云端依赖兼容性 | recipe | 阶段一候选，正式训练前冻结 |
| 015 | formal v2 pair 导入必须用 private evidence locator 重建并重验 BuiltPairReceipt；两侧分别绑定 b10333 实际 deployment manifest，adapter on/off 与 paired GGUF 都保留，微调侧绑定 completed formal source adapter tree 与转换身份 | 保留 v1 兼容且不预先锁死本地部署路线，同时防止合同 JSON、自报 receipt 或任意工件冒充实际加载的正式同源比较 | pair attribution | 已采纳 |
