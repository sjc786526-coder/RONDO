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

### 完成/验收标准

- [ ] 训练投影精确来自 frozen `train.jsonl` 的 470 条记录；上传清单不含 validation、真实 seed、holdout、真实
      `E_final` 或其他私有正文，直接相关 pure tests 证明该边界。
- [ ] 用冻结 tokenizer/template 对 470 条最终训练序列完成精确 token 统计；receipt 记录 min/max/P50/P95、上限和
      超限数，实际训练无未记录截断。
- [ ] completion-only loss 通过可执行测试或 smoke 证据证明：输入/prompt token 不计入 labels，target assistant
      token 计入 labels，非空 completion 不被全部 mask。
- [ ] 真实 smoke 至少完成一个 optimizer step、保存 adapter 并在新进程或等强隔离后成功重载；本地不适合时可在
      所选云后端完成。
- [ ] 一个冻结 recipe 的正式 LoRA 训练有效完成；adapter、实际配置、依赖身份、聚合训练指标和训练 receipt 已保存到
      任务私有远端资产，并下载到 ignored 本地区域复核哈希。
- [ ] 云端累计实际费用不超过 25 USD、GPU Job/Pod 并发始终为 1，任务结束时没有仍在运行或持续计费的计算资源；
      如使用临时卷或 task storage，记录其最终状态。
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
- 经一次授权选定的 Hugging Face Jobs 或 RunPod 私有任务资源：单 GPU smoke、一次有效正式训练、必要转换与私有
  产物持久化；可在普通技术失败后做有原因的修复重试，但总费用和单并发边界不变。

### 不允许修改

- `mydev/`、`multidev/`、生产 Guardian 路由、现有 b10333 qualification、Plan 033 baseline、既有 shadow 结果、
  `eval/results/runs.jsonl` 或既有 `rondo.local.toml`。
- `training/local-approval-synthetic-v1/train.jsonl`、`validation.jsonl`、manifest、schema/prompt/data card 等 L5b
  frozen 资产；Plan 032/033/034/036 历史 plan 的稳定正文。
- Codex/llama.cpp 上游基线、宿主机或全局工具链、CI/PR、公开 Hub/RunPod 资产、长期在线服务、定时任务或
  Inference Endpoint。
- 主工作区已有 tracked 文件、两份未跟踪 `doc/research/RONDO Multi*.md`、其他 worktree 与来源不明的既有
  ignored 资产。

### 不允许读取/查看

- `.env.local` 的内容；只能按根规则静默检查文件存在、非符号链接、权限 0600 和任务所需变量非空，禁止 source、
  搜索、打印、复制或记录值。
- Plan 032 私有 holdout 正文、真实 seed/holdout、真实 `E_final` 和与本任务无关的私有数据。
- 任何认证 token、云端 secret 值或远端私有产物正文中与任务无关的内容；不得运行 `hf auth token`。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

### 3.1 数据隔离与训练投影

1. 训练数据宇宙只能是 frozen `train.jsonl` 的 470 条（SHA-256
   `1e66c06e9357a3b6e14aedd193c5405ad2c18924e57da6a3a209f079b80c110a`）。执行者可从这 470 条内部做
   group-safe 监控划分，或只记
   training loss，但必须记录实际进入梯度与监控的数量/分组；validation、真实 seed、holdout 和真实 `E_final`
   不得影响梯度、recipe、超参、checkpoint 选择或重训决定。
2. 训练上传在访问 validation 之前完成，采用明确 allowlist 和 body-free manifest。云端只允许收到 470 条 train、
   必要 schema/模板/tokenizer 合同、训练/转换脚本及 manifest；测试必须拒绝 validation/holdout 路径、未知文件、
   symlink 和清单外正文。
3. validation 只能在正式训练终态与训练 receipt 冻结后由本地阶段读取，用途仅为生成两侧对照输出和导入 Plan 036。
   本任务全程不读取或物化真实 holdout。

### 3.2 模型、模板与训练有效性

1. 训练 base 固定为官方 BF16 repo/revision；tokenizer 文件必须来自明确冻结 revision 并记录文件哈希，chat template
   绑定现有 lock 的 `mistralai/Ministral-3-8B-Instruct-2512@5b26027e7b19eeb4b7352e1fed3926375dd2cb4d`
   与 SHA-256 `74eeb55fd3341286ec3fd44e902b7120721acc81cd394e96b431f85e93a1ea56`，不得从远端 `main`
   静默解析任一资产。
2. 所有训练输入必须用正式模板与 tokenizer 精确渲染/计数；若序列超出 recipe 上限，先调整合法 recipe 或定位数据，
   不得静默 truncate。是否 packing、rank、target modules、学习率、batch、累积、epoch/max steps 由执行者根据真实显存
   和 smoke 决定并在正式提交前冻结。
3. 正式训练前必须以真实 optimizer step + adapter reload 证明数据映射、completion-only mask、模型/PEFT 组合和持久化
   路径成立。普通依赖、OOM、映射、target module、保存或基础设施问题先根因定位、窄修后合理重试，不因第一次失败
   结束；不得无差别重放同一失败命令。
4. “一个有效正式训练”以 frozen recipe 对声明的 470 条 train universe 完成预定训练、产出可重载 adapter 且训练
   receipt/指标持久化为准。达到该状态后禁止因 loss、validation 或主观质量不满意再跑第二个 recipe；此前因明确技术
   失败产生的有界重试不视为第二个有效 recipe，但必须计入费用和记录根因。训练 receipt 至少绑定 base/tokenizer/
   template、train hash/count、投影/脚本/依赖/recipe、provider/job/hardware、实际步数与聚合 loss、终态、持久化
   revision、产物哈希和费用。

### 3.3 云端授权、预算与持久化

1. 执行者在 Hugging Face Jobs 与用户随后配置的 RunPod MCP 中择一条最稳妥的主路线；可因已证明的后端技术故障切换，
   但两个平台合计实际费用仍不得超过 25 USD，任何时刻只允许一个单 GPU Job/Pod。H100、多 GPU 或第二个有效 recipe
   均需新授权。
2. 第一次付费提交前必须从当时平台事实冻结 GPU、单价、timeout、最坏费用、预计存储/下载峰值和停止方式；预留修复
   余量后，“已结算费用 + 当前运行保守上界 + 拟提交任务最坏费用（含 smoke、失败重试、训练、转换、存储和出站）”
   仍须不超过预算。无法证明强制 timeout/终止后停止计费的后端不使用。提交后报告一次 Job/Pod ID 与费用上界，并持续
   监控到终态，不能把“已提交”当完成。
3. 远端资产必须私有。计算资源停止前先把 adapter、必要 checkpoint、实际配置/依赖、聚合指标和训练 receipt 持久化到
   已授权的任务私有资产；不得创建公开 repo/volume/Space/Endpoint 或长期服务。任务结束要确认没有残留计费计算资源；
   已授权停止、取消或终止本任务创建的 Job/Pod，并移除停止计费所必需的本任务 ephemeral compute；不得删除持久化训练
   产物、用户既有 repo/volume 或任何来源不明的远端资产。

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
   含全部组件哈希的 canonical artifact manifest 计算，不能接受调用方随意自报字符串；receipt 绑定两种不同工件哈希与
   五项 shared contract，并让 Plan 036 从私有完整输出重算验证。正式三方导入精确覆盖 `130 × 3` 个 sample-side，
   不缺、不重、不混分区；本任务不继续打 Opus 裁判包，也不运行正式 Local M4。

### 3.5 本地资源、安全与 Git

1. 下载/转换前重新读取 Windows `C:` 实际余量、项目占用和预计峰值；不得用 WSL 虚拟余量满足门禁。保持 Docker、
   重型 Cargo 与真实本地模型加载互斥；本任务无必要不运行 Docker/Cargo。容量不足或无法读取宿主实际余量时停止重型
   本地步骤，不靠删除来源不明资产腾空间。
2. 不调用 Sol、Opus 或任何真实模型 API；HF/RunPod 控制面只用于已授权的私有训练资源，模型推理只在任务云 GPU 的
   smoke/训练辅助步骤或冻结 b10333 本地服务中进行。
3. linked worktree 不共享 ignored 数据。tracked 代码与文档只在本 worktree 修改；真实模型、runtime、private output
   和 receipt 使用明确的主工作区任务目录，不建 symlink、不把 ignored 正文复制进 Git，也不修改主工作区 tracked 文件。
4. 权重、adapter、checkpoint、原始输出、私有 receipt、密钥、机器配置和云端身份信息不得进入 Git。私有目录 0700、
   普通文件 0600；最终检查 tracked 大文件/敏感字段、所有 worktree 状态和意外生成物。
5. 只跑直接相关的 Python/pure tests、真实训练 smoke、必要本地模型 smoke/130 条输出和正式 preflight；不跑全量 eval、
   重型 Cargo、CI 或 PR。完成后停止服务、释放端口、确认显存回落，并只提交任务 worktree 分支，不合并、不推送、
   不删除 worktree、不重命名分支。

## 4. 软性建议

以下内容是基于当前仓库与环境的实现建议，不是固定路线。执行者可依据实际依赖、RunPod/HF MCP 能力、GPU 和运行结果
采用更简单或更稳妥的等强方案。

- 优先保持两块轻量设施：一个训练投影/recipe/receipt 模块，一个复用现有 b10333 launcher/client 与 Plan 036 schema 的
  paired-output runner；不建立训练平台、数据库、签名链或通用数据治理框架。
- 可先尝试 5—10 条本地 smoke；当前机器为 RTX 4060 Laptop 8GB，若需要下载完整 BF16、依赖不适配或显存明显不足，
  直接用所选云端单卡做短 smoke 更合理，不为本地绿色而换底模或改训练合同。
- HF 只读 preflight 在规划时显示可用的单卡包括 L40S 48GB（当时 1.80 USD/h）和 A100 80GB（当时 2.50 USD/h）；
  价格和可用性必须在提交时重查。RunPod 路线等 MCP 和 runpod-doc 可用后再按其实时能力选择，不把当前猜测写进脚本。
- TRL/Transformers/PEFT、量化训练、Trackio、checkpoint 频率和内部监控 split 均由执行者选择。Trackio 私有配置不顺时，
  使用 Job 日志加私有聚合指标文件即可。
- b10333 实际支持且最简时优先 adapter on/off；若 loader/转换兼容性不稳定，可从同一 BF16 谱系用完全相同的 converter、
  quantizer、quantization 和校准输入生成成对 GGUF。选择后把命令、版本和哈希写进 receipt，不预先偏好某一种。
- 对 Plan 036 的兼容工作只解决真实终态表达、完整导入和后续匿名候选对“无合规输出”事实的如实表示，不借机重构
  盲评设施或改变裁判语义。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已阅读根规则、README、当前 WBS、方向 2 WBS、Plan 034/036、L5b 数据合同、Plan 036 importer/pair schemas、
  b10333 qualification 与历史模型冻结快照。
- 已确认本地 `main@8250c4ddec991b16a2cd2e5881256b4870489946`；主工作区有两份来源不明的未跟踪
  `doc/research/RONDO Multi*.md`，保持不动。
- 已创建 `.claude/worktrees/037-l6-first-lora-paired-artifacts` 与同名分支，基线精确为 `8250c4d`。
- 已确认 L5b frozen 数据为 train 470 / validation 130，Plan 036 cohort 为 130 条、65 / 65 两批，canonical pair
  receipt 与完整三方导入入口已存在。
- 已只读确认 Hugging Face 登录身份可用（未读取 token）；规划时 HF 单卡价格表可读。RunPod/runpod-doc MCP 当前尚未
  出现在工具列表，留待用户随后配置并完成少量登录。
- 当前主机事实：RTX 4060 Laptop 8188 MiB，检查时占用 1574 MiB；RONDO 约 32 GiB；Windows `C:` 实际剩余
  201,328,787,456 bytes。以上只是规划快照，执行下载/模型生命周期前必须重查。

### 当前工作

- execplan 已完成独立审查；等待执行者接管实施。

### 本任务剩余步骤

- 执行者接管 worktree，复核 live 状态和 RunPod/HF 可用性，落地最小训练/输出设施与 focused tests。
- 冻结 train-only 投影、token/template、recipe、依赖、上传清单、预算与 smoke 合同。
- 完成真实 smoke、一次有效正式训练、私有持久化与本地产物回收。
- 形成同源本地 pair，完成两侧 130 条运行、pair receipt 和 Plan 036 正式导入。
- 完成 focused/real preflight、清理、权威文档/日志同步、diff 审查和任务分支本地提交，交给独立审查者。

### 阻塞项

- 当前无计划阻塞。若执行者选择 RunPod，用户仍需先把 RunPod 与 runpod-doc MCP 接入当前开发用 Codex 并完成登录；
  HF 路线的只读身份 preflight 已可用。

### 当前验收状态

- 仅完成规划前置；未上传数据、未创建远端资产、未提交 Job/Pod、未下载新权重、未加载模型、未训练或运行 validation。
- 独立审查已核对 live importer/schema，确认非判定终态表达冲突及 pair receipt 实物哈希边界已在本计划中明确处理。

### 交接边界

- 执行者可在硬约束内自主选择训练/转换/本地 pair 路线，并应自主修复普通技术失败；审查者按真实 receipt、产物哈希、
  运行终态、Plan 036 导入和资源清理验收，不把软建议升级为门槛。
- 本任务完成后冻结本计划；下一步只由 WBS 指向正式 Local M4。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 037 从本地 `main@8250c4d` 建独立 worktree，只提交任务分支 | 保护主工作区未知修改并遵循仓库交付流程 | Git / worktree | 已采纳 |
| 002 | HF Jobs 与 RunPod 二选一为主路线，跨平台实际费用合计不超过 25 USD、单 GPU 并发 1 | 为用户即将接入 RunPod 做好前置，同时防止切换平台造成预算叠加 | 云端执行 | 已采纳 |
| 003 | 官方 BF16 revision、冻结 tokenizer 文件和现有官方 chat template lock 分别显式绑定 | 训练与 b10333 推理不能静默消费远端 main 或旧 GGUF 内嵌模板 | 模型身份 | 已采纳 |
| 004 | adapter on/off 与成对 GGUF 均保留，由 b10333 实际兼容性决定 | 两条路线都能满足同源公平比较，预先写死会增加失败面 | 本地 pair | 已采纳 |
| 005 | 用 train-only allowlist + body-free manifest + focused tests 证明隔离，不建设复杂审计系统 | 这是阻断 validation/holdout 外发和训练泄漏的最小充分设施 | 数据边界 | 已采纳 |
| 006 | 非判定终态按事实保留；只有真实出现且 Plan 036 无法表达时才做最小版本化扩展 | 不能伪造 decision，也不为假想分支提前扩建框架 | 输出/导入 | 已采纳 |
| 007 | tracked 工作留在 worktree，模型/输出等 ignored 实物使用主工作区明确任务目录 | linked worktree 不共享 ignored 资产，现有 b10333 和 GGUF 也在主工作区 | 文件布局 | 已采纳 |
