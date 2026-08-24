# Plan 060：M3-B1b Publication Critic H100 全参数训练资格 Smoke ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只处理 M3-B1b 资格 smoke；M3-B1c 及其后续路线只由 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 安排。

## 1. 目标

### 最终目标

在 RunPod Secure Cloud 单卡 80GB 候选集合
`NVIDIA H100 PCIe` 与 `NVIDIA H100 80GB HBM3`（H100 SXM）中，按预先冻结的机械规则选定并锁住一个实际胜者，对
`Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`
完成一次有界、可复算的训练资格 smoke，给出 M3-B1b 的 GO/NO-GO：证明 Plan 054 的冻结输入合同与 Plan 059 v7
train-only smoke bundle 能组成 BF16 全参数、FlashOptim/FlashAdamW、C1→C2→C3、完整 checkpoint 和新进程恢复的真实训练链，
并用实测资源与费用判断共享 23 USD 总上限是否仍给 M3-B1c 留有可信余量。

本任务只验证训练路线、资源和工件闭环，不要求 loss 改善、样本排序改善、threshold/质量指标、部署资格或产品收益；GO 也只解锁
另行规划和授权的 M3-B1c。

### 阶段与一次授权

任务按下列四阶段连续执行：

1. **阶段 A——本地零费用准备。** 落地专用 objective/collator、阶段消费、full checkpoint/reload、receipt 与 focused tests；生成
   verified upload bundle；只读核对 RunPod 余额、两个候选的实时型号/中心/CUDA/库存/价格、Standard 网络卷能力、镜像、磁盘和费用上界。
   不得下载或加载本地完整模型，不运行 Docker、重型 Cargo 或本地训练。readiness 不通过则不创建外部对象。
2. **阶段 B——资产迁移、机械选择与 Commissioning。** 最多创建两个 task-only 60GB Standard 网络卷，分别服务 PCIe 与 SXM 候选；在不并发运行
   两个 GPU Pod 的前提下迁移或重建已验证 exact 模型、venv、依赖与有价值 cache。按 High > Medium > Low、同级优先 PCIe 的固定规则顺序尝试候选，
   第一个成功进入 RUNNING 且硬件身份核验通过者在 trainer 启动前写入 `selected-gpu` 记录并锁定。上传 verified code 与 train-only bundle，先打通
   load、forward/backward、FlashAdamW、save/reload；commissioning 工件不作为正式 GO 证据。
3. **阶段 C——干净正式资格 smoke。** 设施打通后冻结实际 source、bundle、依赖、image/runtime 和 recipe 身份，使用新的 run/output/checkpoint
   namespace 与新训练进程从初始模型状态完整执行一轮 C1→C2→C3，并完成一次原进程终止后的新进程恢复和继续更新。已验证且身份未变的
   模型/依赖 cache 可以复用；胜者锁定后，commissioning、formal、恢复和合理 replacement/retry 均只能使用同一型号。
4. **阶段 D——止费、验收与交接。** 回收必要的小型日志、receipt、配置、manifest/hash 和聚合资源事实；完成恢复证明后删除不再需要的大 checkpoint；
   终止全部计算 Pod，删除败者网络卷与冗余旧本机资产，保留胜者 Standard 网络卷中的 exact 模型、venv、依赖和有价值 cache。确认 GPU/CPU 持续费用
   为零，记录保留卷持续费、账户级当前运行费与最终任务费用；执行者自检、同步文档并提交 worktree，交回计划制定者独立验收。

用户最初的一次性执行提示词授权阶段 A—D；2026-08-24 的追加授权把 GPU 候选扩为 PCIe/SXM，允许最多两个 task-only Standard 网络卷与受控
replacement，并取消逐窗口人工批准。外置 `budget-policy.json` 是唯一预算权威，所有外部动作前重新读取；在预算内可自主 start/create/stop/delete
本任务对象。任意时刻最多一个 GPU Pod 运行，create 超时必须先按 task name 查询，禁止盲目重发或创建候选集合外对象。

### 完成/验收标准

- [ ] 本地 focused tests 用 tiny/random fixture 证明：冻结输入投影、Binary/Pair 同 scalar objective、pair direction、C1/C2/C3 累计成员关系、
      full checkpoint/new-process resume 和主要失败语义正确；训练入口和 upload allowlist 均不能触达 validation/unseen-test。
- [ ] verified upload bundle 只含 exact source/配置/依赖合同与 Plan 059 v7 train-only smoke bundle；本地先核对 v7 manifest 和全量冻结源 hash，
      Pod 端再核对传输 hash 与 bundle validator。整个仓库、validation、unseen-test、秘密、模型 cache 和其他 ignored 资产均未上传。
- [ ] 付费前 readiness review 记录实时余额、账户级当前运行费、两种候选的型号/中心/CUDA/库存/单价、Standard 卷能力与费率、镜像/runtime、磁盘需求、
      预计/最坏时长、最坏费用和止费余量；不满足候选集合、单 GPU 并发或外置预算策略时不创建外部对象。
- [ ] 正式 smoke 身份闭合：模型/tokenizer exact revision 与已核对文件、Plan 054 v4 input/render/window/raw scalar、Plan 059 v7 bundle、正式 source、
      dependency、image/CUDA/PyTorch/FlashOptim、recipe、`selected-gpu` 锁和实际胜者实物均可复算；未实测候选不声明吞吐、显存或成本结论。
- [ ] 模型以 BF16 全参数方式驻留并训练；预期模型参数全部 `requires_grad` 且由 FlashAdamW optimizer 完整覆盖，没有 PEFT/LoRA/QLoRA、量化、
      CPU/NVMe offload、普通 AdamW fallback、静默冻结或只训练 head。FlashOptim 合法的内部 master weight / optimizer state 精度不属于 fallback。
- [ ] `logits[:, 0]` 是 Binary 与两种 Pair 唯一共享的 raw scalar，higher-is-better；PASS/REWRITE 映射和 preferred/dispreferred 方向正确。方向验收基于
      映射、目标函数/导数测试和真实 bundle 消费，不要求极短 smoke 后模型已产生质量改善。
- [ ] 同一 model lineage 顺序经过 C1、C2、C3 且不在阶段间重置；每阶段至少完成一次真实 optimizer update，并有事实证明该阶段应含的每类监督
      实际贡献了有限 loss/gradient：C1=Binary，C2=Binary+Boundary，C3=Binary+Boundary+Within-PASS。
- [ ] forward、各 loss component、backward、代表性 gradient 与 optimizer update 有限；optimizer state 已真实建立，base model 与 scalar head 的
      代表性参数均有更新证据。不得把“所有参数每一步都必须非零变化”当作额外资格门。
- [ ] 至少保存一次包含完整 model、FlashAdamW optimizer、scheduler、必要 RNG、stage/global step、数据/recipe 身份及继续所需游标的 checkpoint；
      原训练进程已经退出，新的 OS 进程加载这些状态并继续产生至少一个新的有效 update。无需证明 bitwise trajectory replay。
- [ ] 正式 receipt 记录显存峰值、阶段/全局 step、有效样本或 token 吞吐、首步/JIT、稳态 step、save、进程启动、reload/continue 时间、checkpoint
      体积、远端磁盘峰值、实际单价与结算费用；commissioning 与 superseded attempt 不冒充正式结果，但费用全部计入。
- [ ] 基于正式实测与明确的 M3-B1c 规模假设给出可复算成本区间、剩余可承受 GPU 小时/步骤上限和风险余量；可用预算严格为
      `23 USD - Plan 060 实际结算费用`，不机械写成 17 USD，也不替未来 M3-B1c ExecPlan 预先冻结 epoch/step。
- [ ] Plan 060 全部 RunPod 费用（GPU、旧本机卷、两个候选网络卷、下载等待、commissioning、正式 smoke、重试和删除延迟）不超过运行期外置预算策略的
      生效硬上限；整个任务任意时刻 GPU 运行并发为 1，网络卷最多两个且均为 task-only Standard 60GB。
- [ ] 无论 GO、NO-GO 或未形成资格结论，必要小型证据回收后都终止本任务全部计算 Pod，删除败者卷与冗余旧本机资产，保留至多一个已验证规范资产卷；
      不触碰既有/来源不明资源，并以控制面/账单事实确认 GPU/CPU 活跃计费为零，同时记录保留卷费率、账户级当前运行费及相对基线变化。无法确认时不得写成已清理或已完成；若账户因
      既有无关资源非零，只读归因并如实报告，不得擅自清理。
- [ ] 任务终态明确为 GO、NO-GO 或 BLOCKED/INCONCLUSIVE；只有前两者是资格结论，纯容量、凭据、网络、平台、账单未结算或清理阻断不得
      伪装成训练路线 NO-GO，BLOCKED 也不解锁 M3-B1c。GO 的独立验收必须达到 `remaining correctness/functionality findings=[]`；普通非阻断观测
      可以如实保留。
- [ ] 只运行受影响模块的相称定向门禁；执行者更新 Plan 状态、方向 3 WBS 的“待独立验收”事实和一份精炼 `agent_log`，skip/未运行不写成通过；
      最终 GO/NO-GO、下一包指针和 WBS-COMPLETED 只在计划制定者独立验收通过后写入。
- [ ] 任务 worktree 形成少量清晰本地提交并保持 clean；执行者不合并、不推送、不重命名/归档分支、不删除 worktree，等待用户批准和计划制定者验收。

## 2. 范围

### 允许修改

- 本计划“当前状态”和“关键决策记录”；若实施证明必须改变稳定正文中的目标、范围、硬约束或完成标准，先请求用户确认。
- `eval/rondo_eval/publication_critic/` 内职责明确的训练目标、collator、C1/C2/C3 runner、full checkpoint/reload、receipt/resource 汇总与必要 CLI；
  优先以专用模块消费现有公共 seam，不把训练职责塞进现有 inference backend。
- `eval/tests/` 内对应 tiny/random、pure/fake 和 focused tests；必要的版本化 fixture、schema 或模板放在现有 Publication Critic namespace。
- `training/` 内轻量、受跟踪的 Plan 060 model/recipe/dependency/bundle/receipt/runbook 合同与启动脚本；不得放入模型权重、checkpoint、训练输出或超门限资产。
- `eval/environments/` 内最低必要的任务专用 Python 依赖锁，以及现有共享脚本/配置中确有职责契合的窄扩展。
- 实施完成时精炼更新 `training/README.md`、`doc/eval-data-layout.md`、`doc/WBS.md`、
  `doc/WBS/multi-agent-trusted-evidence.md` 和一份 `agent_log/`；没有事实变化的文档不改。独立验收通过后，计划制定者可在同一任务范围内追加
  `doc/WBS-COMPLETED.md` 与最终 WBS 结论。
- 主物理根 `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan060/` 下的 task-only ignored 资产，以及既有 Plan 054 exact tokenizer/cache 的
  必要只读使用。新目录用于 bundle staging、commissioning/formal receipt、日志、下载清单和小型回收证据，不得混入其他任务目录。
- 一次执行授权后的 RunPod 只读账户/价格/容量/账单查询；两个候选型号内 task-only 单 GPU Pod 的顺序 create/start/restart/monitor/stop/delete；最多
  两个 task-only 60GB Standard 网络卷；受控迁移/replacement；verified 上传、exact public model/tokenizer 与依赖下载、有界 smoke、checkpoint/reload
  和必要小型工件下载。任意时刻最多一个 GPU Pod 运行，胜者锁定后 replacement 只能保持同型号。
- Hugging Face 只作为 exact public revision 的匿名或既有安全只读下载来源；普通公开文档与源码查询也在范围内。

### 允许只读核对

- 根规则、README/WBS、Plan 054/059/037、相关日志、现有 Publication Critic 实现/测试和 RunPod L6 runbook，用于判断职责复用；不得改写历史计划或快照。
- `training/publication-critic-v7/` 全量冻结实物可在本地用于 manifest/source-hash 与 train-only 物理隔离核对，但云端上传与训练只允许
  `train-only-smoke-bundle.json` 中的正文。
- 已配置的 task-safe RunPod client 和 SSH 入口可被命令正常使用；不得打开、打印或复制其 token、私钥或底层个人配置。

### 不允许修改或执行

- `mydev/`、`multidev/` 的生产源码，Plan 054/059 冻结资产与历史结果，现有训练数据 split/label/pair/membership，既有模型锁、render、tokenizer、
  window 或 scalar 语义；若发现上游冻结合同本身错误，暂停而不是在 Plan 060 静默修订。
- M3-B1c 规模的正式 C1→C2→C3 训练、validation/unseen-test 上传/训练/调参/recipe 选择/GO 判定、threshold 或质量评价、checkpoint 选择、第二个质量 recipe、
  M3-B1c/M3-C1/方向 1、部署/量化/转换或产品启用。
- 候选集合外 GPU、Community Cloud、多 GPU 或两个 GPU Pod 并发、第三个或 High Performance 网络卷、RunPod Serverless/cluster、HF Jobs/Endpoint/Space、
  HF repo/bucket 创建或任何 HF/model/data 写入；不得为迁移新建 CPU Pod。
- LoRA/QLoRA/PEFT、4/8-bit 或其他量化训练、CPU/NVMe offload、部分冻结、只训 head、普通 AdamW/其他 optimizer fallback；也不得改变底模或数据来修绿。
- 本地完整模型下载、加载、forward 或训练，Docker、重型 Cargo/Bazel、真实 API、批量测评、宿主/全局工具链修改、CI/PR，以及清理来源不明的
  本地/远端资产。
- 合并 `main`、推送任意分支、重命名/归档任务分支或删除 worktree；这些动作必须等待用户另行批准。

### 不允许读取/查看

- `.env.local` 内容、任何 API/HF/RunPod/SSH token、私钥、密码或其他凭据。只允许按根规则静默检查 `.env.local` 的存在、非 symlink、0600 和
  任务所需变量非空；不得 source、搜索、打印、复制、记录或上传。
- 与本任务无关的个人文件、其他仓库、其他 worktree 的私有/ignored 资产、Plan 059 superseded raw batches，以及 validation/unseen-test 正文的
  人工质量浏览。普通受控 verifier 对 tracked v7 manifest/split 字段的机械核对不算查看正文。

### Git-ignored 与主工作区边界

- tracked 代码、合同、测试、文档和日志只在
  `/home/sjc/desktop/RONDO/.claude/worktrees/060-m3-b1b-publication-critic-training-smoke/` 修改并提交。
- `eval-data/`、`.env.local`、`rondo.local.toml` 和 `.claude/` 被 Git 忽略，不会自动出现在 worktree；确需持久化的 Plan 060 ignored 运行资产统一直接写入
  主物理根 `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan060/`，不在 worktree 下建立第二份私有资产树。
- 本任务只读使用主物理根既有 exact tokenizer/cache；不修改、搬运或清理 Plan 054/059 及其他任务资产。不得因 worktree 中看不见 ignored 文件而
  重建、覆盖或把它们加入 Git。
- `.env.local` 和 `rondo.local.toml` 如需由现有安全入口消费，只能从主仓库根按各自合同访问；不得复制到 worktree/Pod。RunPod 凭据只留在本地
  已配置 client，Pod 内下载 public model 的正常路径不需要 HF token。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

### 3.1 上游身份、数据隔离与目标函数

1. **消费冻结上游，不另造近似合同。** 模型固定为 exact revision；训练输入继承 Plan 054 v4 的两消息 render、exact tokenizer、16,384 window、
   overflow/omission、right padding 和 raw `logits[:,0]` higher-is-better scalar。优先复用现有 `build_messages()`、`ExactTokenizer`、
   `load_plan054_training_input()` 与 Plan 059 factory-only consumer；Plan 054 的 sigmoid/临时 threshold 只属于历史评价，不进入训练 objective 或资格结论。
2. **云端只有 train-only smoke bundle。** 上传前必须从 v7 manifest 和四个冻结源文件复核 bundle 的 source hashes，并确认 tracked bundle SHA-256 为
   `5aba49c0eb0cb01df02ff3eecbe527234c3af884331742507c56852ccd0e9839`，再冻结 archive allowlist/hash；Pod 端验证 archive 和 bundle。bundle 实物为
   6 Binary（3 PASS/3 REWRITE）、1 Boundary、1 Within-PASS 的累计 C1/C2/C3 子集；全量 42/16/14 split 和 30/6 pair 只作本地冻结来源，
   不上传 validation/unseen-test，也不把整个 `training/publication-critic-v7/` 打包。
3. **同一 scalar、正确方向。** Binary 必须让 PASS 对应高分方向、REWRITE 对应低分方向；Boundary 与 Within-PASS 均让 frozen
   `preferred_candidate_id` 相对 `dispreferred_candidate_id` 提高。可以选择数值稳定的等价 Binary/pair loss、margin/temperature 和混合权重，
   但选择必须在正式 smoke 前冻结且两种监督不得使用不同 head、不同 scalar 或反向 endpoint。
4. **累计阶段真实消费。** 正式 smoke 使用同一 model/optimizer/scheduler lineage，顺序执行 C1→C2→C3；C2 保留 Binary 并加入 Boundary，C3 再
   保留前两类并加入 Within-PASS。每阶段至少一个 optimizer update，且 receipt 能证明该阶段的每种监督真实参与有限 loss/gradient；只构建 loader、
   只跑 forward 或只消费新加入 pair 均不算覆盖。具体步数、batch 混合与权重由执行者在实测后冻结。

### 3.2 BF16 全参数、FlashAdamW 与恢复

5. **资格路线不可替换。** exact 模型参数以 BF16 进行单 GPU 全参数训练，FlashOptim 的 `FlashAdamW` 是唯一 optimizer 主路径；冻结其 package/source
   revision、版本、安装产物和 runtime class。FlashOptim 自身为了数值/压缩语义维护的 correction/master/optimizer state 可以采用其合法 dtype；
   这不等于量化模型、PEFT、offload 或普通 AdamW fallback。
6. **全参数和更新证明相称而真实。** 加载后记录模型/浮点参数总量、trainable 总量、dtype/device 和 optimizer 参数覆盖，要求预期可训练模型参数
   全部 `requires_grad` 且恰被 optimizer 覆盖；同时记录有限非零总体梯度、optimizer state 建立和至少 base model 代表层与 scalar head 的参数更新。
   不要求每个参数在每一步都出现非零梯度或不同数值，也不建立逐 tensor hash/审计链。
7. **允许技术收敛，不允许换路线。** micro-batch、gradient accumulation、loader、padding、attention backend、gradient clipping 和 scheduler
   等由执行者按兼容性决定；OOM 时按证据收敛这些参数，确有必要可启用 activation checkpointing。不得用 PEFT、量化、offload、其他 optimizer/
   候选集合外 hardware/cloud 或删减训练参数集合换取通过；胜者锁定后不得因普通技术失败切换型号修绿。
8. **full checkpoint 必须由新进程继续。** checkpoint 至少持久化完整 model、FlashAdamW optimizer（含恢复其参数语义所需状态）、scheduler、Python/
   NumPy（如使用）/Torch CPU/CUDA RNG、stage/global step、数据游标或等强继续状态及 frozen identity。保存后原训练进程正常退出，由不同 OS 进程加载，
   核对恢复点并继续至少一个新 optimizer update。checkpoint 是否压缩、文件布局和保存库由实证决定，不要求 bitwise replay；但不得只保存 model、
   重新创建空 optimizer/scheduler 或重新 seed 后冒充恢复。

### 3.3 Commissioning、正式运行与失败语义

9. **先打通，再冻结，再完整重跑。** 阶段 B 允许保留已验证的下载/cache/局部进度并从未打通处修复；普通 bundle、依赖、collator/loss、OOM 参数、
   checkpoint、传输和启动问题可自主窄修重跑，不设机械次数上限，也不得无差别重复同一失败。打通后冻结正式 source/bundle/dependencies/recipe/
   image/runtime，阶段 C 从空训练状态、新输出目录和新进程完整执行；commissioning 或 superseded attempt 只能作诊断且费用照计。
10. **正式运行暴露窄设施 bug 可以整改。** 修复后重新执行必要 commissioning、重新冻结变化身份，并从干净训练状态完整重跑正式 smoke；无需把
    已验证且未变化的公开模型/依赖 cache 人为报废。若合理收敛后仍是 FlashAdamW 根本不兼容/持续非有限、80GB 无法 BF16 全参数更新、目标方向或
    参数更新错误、full checkpoint/new-process continue 不可靠，才形成有效路线 NO-GO，不得换路线或反复重跑掩盖。
11. **没有有效正式证据就没有资格结论。** RunPod capacity、凭据、网络、平台、账单未结算、清理失败或生效预算内未完成正式 run 只形成
    BLOCKED/INCONCLUSIVE；它既不是 GO，也不是“训练路线已证伪”的 NO-GO，M3-B1c 保持锁定。

### 3.4 单 Pod、费用与外部边界

12. **候选机械选择、卷与 replacement 边界。** 候选仅为 Secure Cloud 单卡 80GB 的 `NVIDIA H100 PCIe` 与 `NVIDIA H100 80GB HBM3`。每次选择按
    实时库存 High > Medium > Low，同等级优先 PCIe；同型号中心同级时优先已授权默认中心（PCIe=`US-KS-2`、SXM=`US-NE-1`），除非支持 Standard 卷的
    其他中心有更高库存证据。第一个成功进入 RUNNING 且 GPU/显存/中心/CUDA/价格核验通过的候选在 trainer 前原子写入 `selected-gpu` 并锁定；此后不得
    切型号。最多两个 task-only Standard 网络卷、各 60GB；任意时刻最多一个 GPU Pod 运行。create 超时先按 task name 查询，容量不足可等待，其他 provider
    错误立即失败并回收证据；允许顺序删除无效/零 GPU/失去容量的 task-only Pod并以同一胜者型号和卷 replacement，禁止并行竞速。旧 Pod/本机卷仅在两个
    候选卷分别完成文件集、关键 hash、model revision 与 import 验证后删除；若平台不支持同 Pod CPU-only 启动，可预算内短启旧 H100 搬迁，不得新建 CPU Pod。
13. **外置策略是预算唯一权威。** 主物理根 ignored 文件
    `eval-data/publication-critic/plan060/controller/budget-policy.json` 只记录可实时调整的 `hard_cap_usd`；GPU、container/volume/network storage、
    下载/编译/JIT 等等待、commissioning、正式 smoke、所有重试和删除延迟全部累计。controller 每次采样重新读取该文件，按固定清理余量自动推导
    正常工作、停机回收和立即删除线；缺失或非法时 fail-closed。训练 bundle、Plan、runbook 与 cloud candidate 不复制当前金额，改预算不触发重冻。
    创建前以实时余额/费率和保守最长时长确认可行，运行中持续查看 Pod 状态、日志和 billing，并为回收/删除预留余量；不得等实际越线或余额耗尽才停。
    不得通过新建预算服务增加复杂度，简单 JSON、可复算记录与 provider 账单即可。finalizer 必须绑定生效值与策略文件 SHA-256。
14. **Hugging Face 只读。** Pod 只从公开 Hub 读取 exact model/tokenizer revision 与已冻结文件；不得使用浮动 `main`，不得登录、转发 token、创建/
    修改 repo、上传 code/data/model/checkpoint，亦不得使用 HF Jobs/Endpoint/Space/Bucket。普通公开源码/文档和依赖下载允许，但正式依赖必须冻结身份。
15. **finally-style 止费与资产保留。** 成功、NO-GO、异常或 blocked 都先尽力回收必要小型证据，再终止全部 task-only 计算 Pod，删除败者卷与冗余旧本机
    资产，保留胜者 Standard 网络卷中的 exact 模型、venv、依赖和有价值 cache，并复核 GPU/CPU active cost 为零、记录持续卷费。只下载 receipt/log/
    config/manifest/hash/聚合资源事实；full smoke checkpoint 在证明恢复后删除，不要求长期回收本地。
    若控制面暂不可达，持续安全重试清理而不是宣布完成；不得删除任何非本任务对象。用于扣减共享 23 USD 的 `actual_plan060_cost` 必须来自删除后
    最终账单/费用事实，不能用训练结束时的中间 receipt 或按小时估算替代。清理后同时记录账户级当前运行费；若既有无关资源使其非零，只读归因并
    报告相对基线变化，不得擅自清理或谎报全账户归零。

### 3.5 预算结论、记录与交付

16. **成本判断不伪精确。** receipt 用正式 steady-state step/token throughput、save/reload、cold-start/download/JIT 和 storage 实测，结合明确披露的
    M3-B1c 数据规模、阶段/epoch/step 与重试假设形成保守区间，同时报告剩余预算可承受的小时/步骤上限。若尚无足够信息证明正式训练能在
    `23 - actual_plan060_cost` 内完成，则本项不满足 GO；不得把希望、最低单步耗时或固定 17 USD 当证据。
17. **证据轻量但足够复核。** 至少保留正式 run identity、阶段监督/step、loss/gradient/update、trainable/optimizer coverage、checkpoint save/
    reload/continue、显存/吞吐/时长/体积、actual billing 和资源终态。receipt/manifest 可以是简单 JSON/JSONL/文本，不建设数据库、签名链、访问审计、
    严格因果或通用训练平台；日志与 receipt 默认不复制 candidate 正文、秘密或完整权重。
18. **文档按职责同步。** Plan 只记录任务内状态和关键决定；执行者把 WBS 更新到“正式运行已完成、待独立验收”，agent log 精炼记录实施与证据，
    README/数据布局仅在稳定事实变化时更新。独立验收通过后再由计划制定者写 WBS-COMPLETED、最终 WBS 结论和交接；GO 只能把下一包指向仍需
    独立 ExecPlan/授权的 M3-B1c，NO-GO 或 BLOCKED 不自动继续花费或训练。
19. **执行者止于提交。** 实现、focused validation、云端闭环、清理、自检和文档更新均在当前任务内自主完成，之后提交 task branch 并保持 worktree
    clean；不得合并、推送、归档或删除 worktree。执行者给出建议结论和完整未运行项，最终独立验收与 GO/NO-GO 由计划制定者负责。

## 4. 软性建议

以下内容用于根据现有代码和官方 FlashOptim/Hugging Face 接口给出执行建议，但不是固定约束，也不代表代码变化或 H100 实测后的精准路线。
执行者可以依据 live code、官方源码、Pod 环境和测试结果采用更优的等强方案；审查者不得把本节偏好升级为验收门。

- 职责契合时直接复用 Plan 054 的 packet/render/tokenizer/window/scalar 实现、Plan 059 的 factory-only consumer/bundle validator，以及 Plan 037 的
  verified tar/SCP、单 Pod lifecycle、billing、pending→completed receipt、下载验真与清理经验。现有 Plan 054 backend 是 inference-only，Plan 037
  runner 是 Ministral QLoRA/adapter；强行复用会扭曲职责时，宜在 Publication Critic namespace 新建小而完整的 full-model trainer。
- 可以优先用数值稳定的 Binary logistic objective 和 `preferred - dispreferred` pairwise logistic/softplus objective 共享 raw logit；loss 权重、margin、
  temperature、batch composition 和 scheduler 不预先锁死，只要语义、有限性和阶段真实消费满足硬约束。
- FlashOptim 官方实现提供标准 PyTorch optimizer API、BF16 参数、首步 Triton JIT、numerics check、压缩 optimizer state 与 full-precision model export/
  import 等能力。执行者应先以 tiny fixture 验证所选 exact 版本的保存/加载语义，再决定是否使用其辅助 API；不要根据 README 假定当前版本一定兼容。
- Stage A 可用 tiny Qwen-like/random scalar model 或职责等价 fixture 验证全流程；不得为此下载或加载本地 Skywork 完整权重，也不得把 fixture 当成
  H100/FlashAdamW 正式证据。
- 先用最小 commissioning 打通加载、一次 update、save/reload，再逐步验证 C1/C2/C3；技术事实稳定后再冻结正式 identity。正式 run 使用新的目录/
  process 并从 exact base 开始，但复用已校验 cache 能节省费用且不损害干净边界。
- micro-batch、accumulation、loader worker、padding、attention implementation、gradient clipping、checkpoint 格式和 activation checkpointing
  由执行者按显存与数值实测选择。优先做最少但信息充分的步骤，不为了多采样扩大 smoke。
- H100 首步/JIT 与稳态 step 分开记录；显存采样在 reset peak 后覆盖 forward/backward/update，必要时分别记录 load、save/reload 峰值。吞吐同时报告
  samples 与 tokens，避免短长序列混合时只报 steps/s。
- 正式 source 可以用 clean Git commit 或明确内容 manifest 冻结；bundle 使用 allowlist、普通 SHA-256、流式大文件 hash 和解包后 verifier 即可，
  不需要签名服务、provenance 数据库或逐事件审计。
- M3-B1c 尚未冻结正式 recipe 时，给出假设透明的低/中/保守区间、剩余预算可承受上限与主要风险；不要为了输出一个漂亮数字提前替 B1c 做训练计划。
- 可使用少量子智能体并行审阅本地 objective/checkpoint 和最终证据，但远端 lifecycle/controller 必须保持单一所有者，避免并发误创建或误清理资源。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 已从 clean `main@60ada10dc6d44c39271f6ec699e599515af3c8df` 建立专用 worktree
  `/home/sjc/desktop/RONDO/.claude/worktrees/060-m3-b1b-publication-critic-training-smoke` 与分支
  `worktree-060-m3-b1b-publication-critic-training-smoke`。
- 已阅读根规则、README/WBS、Plan 037/054/059、Plan 059 v7 冻结数据/consumer、Plan 054 model/render/scalar identity、现有 RunPod runbook 与
  相关测试/日志；并行只读审阅对范围、复用 seam、失败/费用/ignored 边界的结论已纳入本计划。
- 已用 Hugging Face 公开只读 metadata 核对 exact revision 仍解析为同一 commit，safetensors 参数为 1,720,577,024 BF16；没有下载权重、登录或修改
  Hub 状态。
- 本地 full-model trainer 当前包含 objective/collator、FlashOptim 全参数/有效 master 与压缩状态、optimizer/scheduler LR finite、C1/C2/C3 游标、
  完整 checkpoint/new-process、bundle/launcher 和 final receipt 合同；仓库级 `scripts/wait-runpod-readiness.py` 提供可参数化的 Pod/GPU/机房/价格/预算/
  deadline 轮询能力，不属于 Plan 060 bundle 或 direction 私有资产。最新独立复核的 correctness findings 为 `remaining=[]`。
- final-07 已上传、hash 与严格解包验证通过，但 `bootstrap-final-07` 在目标脚本启动前暴露 launcher 内嵌 `bash -c` 单引号破坏；未开始模型下载或训练，
  Pod 已在 `2026-08-24T07:18:59Z` 停止，该 attempt 只作 superseded commissioning 证据。现以专用 argv-preserving worker 消除嵌套 shell source，
  动态覆盖 tricky argv、target-owned status、fallback、退出码与 active lock。
- final-08 后已完成匿名 exact-revision 模型下载、关键 hash 与可导入验证，旧 PCIe Pod 的本机 `/workspace` 保留 exact 模型、venv、FlashOptim、
  HF/Triton cache 与依赖身份。final-10 首次真实进入 `FlashAdamW.step()` 后暴露 fused update 失败；必要小型日志已回收，Pod 停止且没有 checkpoint。
  后续窄修补齐 optimizer/scheduler 诊断、winner-lock、双候选 controller 与终态 provider-chain/卷费合同，未改变模型、objective、optimizer 或训练路线。
- final-12 因 source drift、final-13 因 Standard 卷 mode、final-14/final-15 因实测 FlashOptim numerics 分辨率门已明确 superseded，均禁止再次
  上传或据此重启。final-15 的 `2e-4` 越过首个 maxabs=68 参数后，在下一 maxabs=136 参数处由同一真实门以
  `2e-5 < 3.114e-5` fail-closed；Pod 已立即停止，未产生 checkpoint 或训练更新。当前源码 focused tests 为 97/97；不关闭门禁、不改变
  optimizer/master/state 路线的最小下一倍增 `4e-4` 曾严格重冻为 final-16，但独立复核指出逐参数 lazy gate 仍可能按更大 maxabs 继续暴露，故该 bundle
  已在上传前 superseded。当前新增一次性全参数 numerics preflight：复用 pinned optimizer 的 `recompute_param_stats()` 与同一逐参数 checker，在任何
  objective/update 前检查完整 coverage；失败时用同一 checker 报告全组参数所需的最小二倍增候选。focused tests 为 100/100；新候选
  final-17 经独立复核发现 exact exception class 与 receipt coverage/LR 交叉绑定仍不足，故同样在上传前 superseded。当前以 pinned public/defining
  export 的同一 `NumericsError` 类对象做 exact-type 捕获，拒绝同名同 module spoof；start/resume receipt 同时要求 preflight checked tensor count 等于
  optimizer full coverage，且 configured LR 等于所有 post-update optimizer/scheduler LR。focused tests 为 102/102；新候选
  `bundle-final-18.tar` 已从本地定向门禁后严格冻结：757,760 bytes、archive SHA-256
  `99844cd386e2e1219a268032c98a0dfe2e652d95a6f4e6c6b7e07e76dbc2cfdb`、manifest SHA-256
  `8a86db9913d3d8a6497cd682a677e91092fe76d54143e84813855cebf9440543`、content SHA-256
  `19a95858ea5b320151c8e7ba9ec7e9a15d994f7f5c005943cd96a594e49edd4e`；外部干净 cwd 严格解包与 55 个 regular file 身份验证通过；最终独立
  restart-readiness 复核 `remaining_findings=[]`。它随后完成 commissioning 与一轮正式 start/resume，但并行审查在本地 finalizer/runner
  发现 provider 时序、胜者卷绑定与 winner-lock shape 三项实质缺口，因此 final-18 正式结果只保留为 superseded 诊断证据。
- 已按 High > Medium > Low、同级 PCIe 优先的冻结规则完成首次 RUNNING 身份核验并锁定 `NVIDIA H100 PCIe`；规范 winner lock 位于主物理根
  `eval-data/publication-critic/plan060/controller/winner-lock.json`。胜者 Pod `8vdahxbulczvza` 与旧资产源 Pod `b0fazq4ueaii2k` 当前均为 stopped，
  没有 GPU/CPU active cost；胜者 60GB Standard 卷 `hi3iaz8rsr` 与败者 SXM 60GB Standard 卷 `bbfxl15nqr` 均保留，胜者卷中的 exact
  model/tokenizer、venv、FlashOptim、依赖身份与 cache 已完成 hash/import/hardware 验证。
- 外置 `budget-policy.json` 是唯一预算权威；通用 readiness/start waiter 与 Plan 060 双候选纯决策 controller 已落地。最后一次胜者 Pod 仅用于
  RUNNING/硬件/SSH 身份核验，按用户要求在本地合同收敛前停止，没有上传 bundle 或启动训练。独立 readiness 通过后的一次付费启动已把 final-13、
  exact model/tokenizer、venv、FlashOptim、依赖与 cache 固化并验证到胜者卷；首次 commissioning 在加载模型前因 Standard 卷把已 chmod 0600 的
  winner-lock 副本呈现为 0666 而 fail-closed。final-14 已跨过该门，但 FlashOptim `check_numerics` 实测 `1e-4` 的预测最小步长 `1e-5` 低于
  当前 BF16 权重分辨率 `1.557e-5`，同样在更新前 fail-closed；两次均立即停止 Pod，未产生 checkpoint 或训练更新。
- replacement controller 在完整本地复核后以约 5 秒周期等待，创建并接管 replacement Pod `oe6gbptvq5yhja`；agent 在 300 秒交接保护内完成
  Secure 单卡 H100 PCIe 80GB、US-KS-2、CUDA 13.0、`2.89 USD/h`、胜者 Standard 卷与 exact model/venv/FlashOptim/cache 的 provider/SSH/资产验收。
  controller 只在 RUNNING 后交接，不再因 provider 投影延迟错失库存。
- final-18 commissioning 已证明 C1→C2→C3、311/311 全参数 FlashAdamW、约 10.56GB 完整 checkpoint、新 OS 进程恢复与 step 3→4 继续更新可行。
  审查整改后重新冻结的正式身份为 `bundle-final-19.tar`：768,000 bytes、archive SHA-256
  `066a9f60eb308312bd99f25008ddb66f3fd893e2ea082e920a4e725d3df67a61`、manifest SHA-256
  `735e928ce733e08742f0e03c55497ac1f94f53674ec2855df37ca843e1f43a8d`、content SHA-256
  `699e355e550f17b2efe158b66d4bf50619b7fa3d55194b42c378fefe6b4cb9a1`；独立逐文件复核 `remaining_findings=[]`。
- final-19 已从新目录/新进程完成干净 formal start/resume：C1/C2/C3 与恢复后 C3 各一次真实更新，1,720,577,024 个 BF16 参数及 311 个
  optimizer tensor 完整覆盖，FlashAdamW 压缩 state/有效 master/有限性/LR/阶段消费/新进程证据均通过。正式 start/pending receipts 已回收到主物理根；
  final-19 checkpoint 保留供独立验收，final-18 commissioning/formal checkpoint 已删除。

### 当前工作

- `COMPLETE / TECHNICAL_GO`：final-19 核心训练资格目标已完成并通过独立验收，`remaining correctness/functionality findings=[]`。
  用户决定把当前 RUNNING Pod、胜者卷、final-19 checkpoint 与连续费用总账直接交给 Plan 066，不为 Plan 边界先释放资源。

### 本任务剩余步骤

- 无。资源终态、settled billing 和连续总账的最终收口属于已授权的 Plan 066，不再阻塞 Plan 060 技术结论。

### 阻塞项

- 无。

### 当前验收状态

- `PASS / COMPLETE / TECHNICAL_GO`：H100 BF16 全参数 FlashAdamW commissioning 与 final-19 干净正式 start/resume 均通过；正式 receipt、
  checkpoint、源码/archive 身份和新进程恢复证据闭合，两路独立复核均为 `remaining=[]`。Plan 064 有界预算适配转为 `DATA_GO`，M3-B1c 已解锁。
  资源终态与最终账单按用户决定延后到 Plan 066 连续任务统一收口，不冒充已归零。

### 交接边界

- 执行者在本 worktree 内完成范围内实现、云端闭环、清理、自检和提交后停止，不合并/推送/归档，并把 commit、测试、正式 run/receipt、actual cost、
  远端终态、建议结论、普通失败与未运行项交给计划制定者。
- 交接必须单列主物理根 `eval-data/publication-critic/plan060/` 内本任务实际创建/修改的 ignored 路径、大小、保留/清理状态，并确认未触碰其他任务的
  ignored 资产；这只需人工可读清单，不新增 manifest 系统。
- 本任务完成后冻结此计划。GO 仅把后续交回 `doc/WBS.md` 中另行规划和授权的 M3-B1c；NO-GO 或 BLOCKED 不自动改换路线、扩预算或启动下游。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 060 使用现有专用 worktree；ignored 运行资产统一落主物理根 `eval-data/publication-critic/plan060/` | tracked 交付与 ignored 重资产物理分离，避免 worktree 各建一份私有树 | Git、运行资产 | 已采纳 |
| 002 | 用户交给执行者的提示词一次授权阶段 A—D；阶段 A readiness 是技术门而非第二人工授权门 | 降低重复确认，同时保证准备不足时不创建付费资源 | 授权、阶段 | 已采纳 |
| 003 | 初始合同只允许一个 H100 PCIe Pod；追加授权改为 PCIe/SXM 双候选、最多两个 Standard 卷及同胜者型号的受控 replacement，始终保持 GPU 运行并发 1 | 在稀缺主机库存下把数据与宿主解耦，同时保留可复用资产和单 GPU 费用边界 | 云生命周期 | 已被 017 取代 |
| 004 | 复用 Plan 054/059 输入与数据 seam，新建职责明确的 Publication Critic full-model trainer；不复用 L6 QLoRA/adapter 训练语义 | 输入合同契合而训练目标不契合，专用能力比扭曲旧设施更干净 | 架构、训练 | 已采纳 |
| 005 | Binary 与两类 Pair 共享 `logits[:,0]` raw scalar；具体稳定 loss、权重和 batch 混合留给执行者冻结 | 锁住正确语义，保留依据 H100 实测选择实现的空间 | objective、recipe | 已采纳 |
| 006 | Commissioning 后才冻结正式身份，并从新训练状态完整重跑；允许复用身份未变的 cache | 保留调试进度、减少付费浪费，同时隔离正式证据 | 运行、证据 | 已采纳 |
| 007 | Plan 060 硬上限以外置运行期策略为准；M3-B1c 可用额始终按 `23 - actual_plan060_cost` 计算 | 用户需要在不中断训练身份或重冻 bundle 的前提下灵活调整预算；重试与等待仍如实计费 | 预算、结论 | 已采纳 |
| 008 | 资格终态为 GO/NO-GO；纯设施/账单/清理阻断单列 BLOCKED/INCONCLUSIVE 且不解锁 B1c | 避免把缺失证据误报为路线失败或通过 | 失败、交接 | 已采纳 |
| 009 | 执行者只提交 task worktree；合并、推送、分支归档与 worktree 删除等待用户批准 | 遵守本轮最新交付要求并保留独立验收现场 | Git、交付 | 已采纳 |
| 010 | 首次 Pod 停止后曾要求每个后续付费窗口单独批准；追加授权改为仅受动态预算策略约束 | 当前可在预算内自主断点重试，但付费前本地收敛原则不变 | 运行、预算 | 已被 018 取代 |
| 011 | final-07 将 post-update model/effective-master/optimizer moment/optimizer-scheduler LR finite、阶段与恢复证据 cardinality、固定 C3 cursor 和 provider Pod/window 绑定纳入同一 receipt 合同 | 防止 NaN/Inf、空/缩小 coverage、错误 resume 与 receipt 错绑仍可绿，同时不建设第二套审计体系 | trainer、checkpoint、receipt、bundle | 已采纳 |
| 012 | 本地新增 CPU Torch tiny objective→update→checkpoint save/verify/load→model/optimizer/scheduler/RNG restore→continue seam；它不替代 FlashAdamW/H100 commissioning | 让付费前真实覆盖关键组合路径，同时保持无模型、无 GPU 的轻量边界 | tests、readiness | 已采纳 |
| 013 | detached launcher 改为调用专用 argv-preserving worker，不再把状态 fallback 拼入嵌套 `bash -c` source | final-07 在付费启动后证明内嵌单引号会拆坏 worker 命令；专用 worker 可直接测试 exact argv、status owner 与退出码 | launcher、bundle | 已采纳 |
| 014 | RunPod 容量/费用等待器作为仓库级通用脚本维护，并通过参数绑定现有 Pod、machine GPU/机房、catalog、价格、预算与统一 deadline | 后续同类训练可复用同一 fail-closed 轮询设施，同时不把 Plan 060 私有常量固化为第二套 controller | scripts、tests、运行 | 已采纳 |
| 015 | final-08 HF 网络失败后停止 GPU 计费并保留当时 Pod/本机资产，从首个未完成 seam 继续 | 这是追加网络卷与同型号 replacement 授权前的保护资产决策；当前仍保留其“先保护已验证进度”原则，资源拓扑和清理以 017/018 为准 | 远端生命周期、预算 | 已被 017/018 取代 |
| 016 | 取消固定付费运行窗口，仅由外置 `hard_cap_usd` 控制；正常工作/停机回收/立即删除线按固定清理余量自动推导并逐次重载 | 用户明确允许自主断点重试并延长时间，同时要求预算可实时调整且保留清理与账单延迟余量 | 预算、运行、清理 | 已采纳 |
| 017 | 候选固定为 Secure 单卡 80GB PCIe/SXM；High > Medium > Low、同级 PCIe 优先，第一个 RUNNING 且身份核验通过者写入 `selected-gpu` 后锁定 | 选择不依赖训练结果，允许在稀缺库存中机械决策且防止事后换卡修绿 | GPU 选择、receipt、重试 | 已采纳 |
| 018 | 最多创建两个 task-only 60GB Standard 卷；终态终止全部计算 Pod、删除败者卷和冗余旧本机资产、保留一份规范胜者资产卷；所有动作仅受外置预算策略约束 | 降低后续冷启动和重复下载成本，同时让持续费用可见且可控 | 存储、预算、清理 | 已采纳 |
| 019 | 控制端 winner-lock authority 继续要求 regular 0600；Standard 卷远端副本改以 no-follow regular、大小/读取稳定、严格 schema、启动前 exact SHA 和 receipt hash 绑定，不依赖卷不保真的 POSIX mode | 实测卷把已 chmod 0600 文件呈现为 0666；mode 不是该卷可执行的安全合同，而 task-private replica 的字节/身份绑定仍可完整验证 | winner-lock、远端卷、receipt | 已采纳 |
| 020 | FlashAdamW commissioning candidate LR 由 `1e-4` 调为 `2e-4`，继续启用 `check_numerics=true`，不改 optimizer/master/state/模型路线 | H100 首次实测 numerics gate 给出 `1e-5 < 1.557e-5`；后续更大张量门限由 021 收口 | recipe、commissioning | 已被 021 取代 |
| 021 | FlashAdamW commissioning candidate LR 由 `2e-4` 调为 `4e-4`，仍保留同一 numerics/master/optimizer 合同 | pinned FlashAdamW 对 Adam 逐参数按 `0.1 * LR` 估算；final-15 越过 maxabs=68 后在 maxabs=136 实测 `2e-5 < 3.114e-5`，`4e-4` 是跨过该最新门限的最小下一简单倍增 | recipe、commissioning | 已采纳 |
| 022 | 在 optimizer 构造并完成 exact full-parameter coverage 后、任何 objective/update 前，以 pinned `recompute_param_stats()` 和 `_check_param_numerics` 一次扫描全部参数；仅捕获 public/defining export 同一 exact `NumericsError` 类，失败时继续只读二倍增试探并汇总所需候选；receipt 将 checked count/LR 与 coverage/真实 stage LR 绑定 | FlashOptim 默认 lazy gate 会在首个失败参数终止，final-14/15 已证明可能逐档重复付费；复用 exact dependency 语义可在一次模型加载内收敛，同时不复制公式、不关闭门禁、不修改 optimizer state | runner、model contract、receipt、tests | 已采纳 |
| 023 | stopped 旧 winner compute 在胜者卷/资产再次核验后终止；由通用 replacement controller 约每 5 秒查询 US-KS-2 exact PCIe 容量，并以固定名称、同镜像、同卷顺序创建一个 replacement；create 不确定先 exact-name 查重，RUNNING 后 180 秒无接管即 stop | fixed-Pod waiter 不能把已解耦网络卷调度到机房其他可用主机；保持 winner 型号、机房、单运行 GPU、动态预算和交接看门狗不变即可消除该容量竞态，无需改训练身份或建设第二套调度体系 | scripts、tests、云生命周期 | 已采纳 |
| 024 | replacement controller 抢到精确 Pod 后只核对 ID/name/RUNNING 即交接；完整 provider/SSH/资产验收由 agent 在显式 300 秒看门狗内完成 | Low 库存下前置全量 provider 投影会制造竞态；交接后验收失败仍可安全停止同一 Pod | controller、运行 | 已采纳 |
| 025 | final-18 成功训练后发现的 finalizer 时序/胜者卷绑定与 runner winner-lock shape finding 必须进入新 bundle；final-18 降为诊断证据，final-19 从空训练状态重跑 formal | formal identity 应代表当前完整源码；不能以“只影响 finalizer”为由让正式 bundle 与交付源码漂移 | bundle、runner、finalizer、formal | 已采纳 |
| 026 | 独立验收前保留 final-19 checkpoint；只删除 superseded checkpoint。按用户最新指令，计算 Pod 在再次批准前保持 RUNNING，终态清理与 final receipt 延后 | Standard 卷按配置容量计费，删除最新 checkpoint 不降时薪；保留恢复现场更有利于验收，且不得违背最新资源保留指令 | checkpoint、Pod、清理、交付 | 已采纳 |
| 027 | 独立验收接受 Plan 060 `TECHNICAL_GO`，当前热 Pod/胜者卷/final-19 checkpoint 与原基线连续总账直接交给 Plan 066 | H100 稀缺且训练设施已验证；不为行政任务边界中断热资源，同时由 Plan 066 统一承担最终清理和 settled billing | 验收、预算、资源交接 | 已采纳 |
