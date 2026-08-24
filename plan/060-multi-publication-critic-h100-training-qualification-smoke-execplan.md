# Plan 060：M3-B1b Publication Critic H100 全参数训练资格 Smoke ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只处理 M3-B1b 资格 smoke；M3-B1c 及其后续路线只由 `doc/WBS.md` 与
> `doc/WBS/multi-agent-trusted-evidence.md` 安排。

## 1. 目标

### 最终目标

在整个任务唯一一个 RunPod H100 PCIe 80GB Pod 上，对
`Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`
完成一次有界、可复算的训练资格 smoke，给出 M3-B1b 的 GO/NO-GO：证明 Plan 054 的冻结输入合同与 Plan 059 v7
train-only smoke bundle 能组成 BF16 全参数、FlashOptim/FlashAdamW、C1→C2→C3、完整 checkpoint 和新进程恢复的真实训练链，
并用实测资源与费用判断共享 23 USD 总上限是否仍给 M3-B1c 留有可信余量。

本任务只验证训练路线、资源和工件闭环，不要求 loss 改善、样本排序改善、threshold/质量指标、部署资格或产品收益；GO 也只解锁
另行规划和授权的 M3-B1c。

### 阶段与一次授权

任务按下列四阶段连续执行：

1. **阶段 A——本地零费用准备。** 落地专用 objective/collator、阶段消费、full checkpoint/reload、receipt 与 focused tests；生成
   verified upload bundle；只读核对 RunPod 余额、实时 H100 PCIe 80GB 容量/价格、镜像、磁盘和费用上界。不得下载或加载本地完整模型，
   不运行 Docker、重型 Cargo 或本地训练。readiness 不通过则不创建 Pod。
2. **阶段 B——Commissioning。** 创建整个任务唯一的 task-only Pod，上传 verified code 与 train-only bundle；Pod 内下载 exact public
   model/tokenizer 和候选依赖，先打通 load、forward/backward、FlashAdamW、save/reload。普通设施问题在授权和预算内自主窄修、局部重验；
   commissioning 工件不作为正式 GO 证据。
3. **阶段 C——干净正式资格 smoke。** 设施打通后冻结实际 source、bundle、依赖、image/runtime 和 recipe 身份，使用新的 run/output/checkpoint
   namespace 与新训练进程从初始模型状态完整执行一轮 C1→C2→C3，并完成一次原进程终止后的新进程恢复和继续更新。已验证且身份未变的
   模型/依赖 cache 可以复用，不要求重建 Pod、重新下载或重复安装。
4. **阶段 D——止费、验收与交接。** 回收必要的小型日志、receipt、配置、manifest/hash 和聚合资源事实；完成恢复证明后可删除 smoke
   checkpoint；删除本任务 Pod 和它明确创建的附属对象，确认 task-scoped 活跃计费为零并记录账户级当前运行费事实；执行者自检、同步文档并提交 worktree，交回计划制定者
   独立验收。

本文件的制定与提交不授权外部或付费操作。用户把包含明确一次性授权的执行提示词交给执行者后，该授权同时覆盖阶段 A—D；阶段 A readiness
是技术门，不是要求执行者再停下等待第二次常规批准。只有任务意外需要越过本计划的原则边界、第二个 Pod 或 6 USD 上限时，才重新请求授权。

### 完成/验收标准

- [ ] 本地 focused tests 用 tiny/random fixture 证明：冻结输入投影、Binary/Pair 同 scalar objective、pair direction、C1/C2/C3 累计成员关系、
      full checkpoint/new-process resume 和主要失败语义正确；训练入口和 upload allowlist 均不能触达 validation/unseen-test。
- [ ] verified upload bundle 只含 exact source/配置/依赖合同与 Plan 059 v7 train-only smoke bundle；本地先核对 v7 manifest 和全量冻结源 hash，
      Pod 端再核对传输 hash 与 bundle validator。整个仓库、validation、unseen-test、秘密、模型 cache 和其他 ignored 资产均未上传。
- [ ] 付费前 readiness review 记录实时余额、账户级当前运行费、H100 PCIe 80GB 容量与单价、镜像/runtime、GPU 与临时存储费率、磁盘需求、预计/最坏时长、
      最坏费用和止费余量；结论不满足单 Pod/6 USD 边界时没有创建 Pod。
- [ ] 正式 smoke 身份闭合：模型/tokenizer exact revision 与已核对文件、Plan 054 v4 input/render/window/raw scalar、Plan 059 v7 bundle、正式 source、
      dependency、image/CUDA/PyTorch/FlashOptim、recipe 和 H100 PCIe 80GB 实物均可复算。
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
- [ ] Plan 060 全部 RunPod 费用（GPU、临时/持久存储、下载等待、commissioning、正式 smoke、重试和删除延迟）不超过 6 USD；整个任务只创建
      一个 task-only Pod 对象且 GPU 并发为 1。
- [ ] 无论 GO、NO-GO 或未形成资格结论，必要小型证据回收后都停止并删除本任务 Pod、临时卷和明确创建的附属对象；不触碰既有/来源不明资源，
      并以控制面/账单事实确认 task-scoped 活跃计费为零，同时记录账户级当前运行费及相对基线变化。无法确认时不得写成已清理或已完成；若账户因
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
- 一次执行授权后的 RunPod 只读账户/价格/容量/账单查询，以及整个任务唯一一个 task-only H100 PCIe 80GB Pod 的 create/start/restart/monitor/
  stop/delete、明确的临时磁盘/卷、verified 上传、exact public model/tokenizer 与依赖下载、有界 smoke、checkpoint/reload 和必要小型工件下载。
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
- 第二个或 replacement Pod、其他 GPU、H100 SXM、其他云后端、多 GPU/并发、RunPod Serverless/cluster、长期 volume/service、HF Jobs/Endpoint/Space、
  HF repo/bucket 创建或任何 HF/model/data 写入。
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
   hardware/cloud 或删减训练参数集合换取通过。
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
11. **没有有效正式证据就没有资格结论。** RunPod capacity、凭据、网络、平台、账单未结算、清理失败或 6 USD 内未完成正式 run 只形成
    BLOCKED/INCONCLUSIVE；它既不是 GO，也不是“训练路线已证伪”的 NO-GO，M3-B1c 保持锁定。

### 3.4 单 Pod、费用与外部边界

12. **整个任务只创建一个 Pod 对象。** 必须是 RunPod 上 task-only、单张 H100 PCIe 80GB、GPU 并发 1；创建前核对 returned GPU 型号/显存、价格、
    image/runtime、磁盘和终止保护。允许 stop/start/restart 同一 Pod；create 超时先按 task name/控制面查明是否已创建，禁止直接重发 create。
    该 Pod 不可恢复而需要 replacement 时，先止费并请求新授权；不碰账户中既有或来源不明对象。
13. **6 USD 是全生命周期硬上限。** GPU、container/volume/network storage、下载/编译/JIT 等等待、commissioning、正式 smoke、所有重试和删除延迟
    全部累计。创建前以实时余额/费率和保守最长时长确认可行，运行中持续查看 Pod 状态、日志和 billing，并为回收/删除预留余量；不得等实际越线或
    余额耗尽才停。不得通过新建通用预算服务增加复杂度，简单可复算记录与 provider 账单即可。
14. **Hugging Face 只读。** Pod 只从公开 Hub 读取 exact model/tokenizer revision 与已冻结文件；不得使用浮动 `main`，不得登录、转发 token、创建/
    修改 repo、上传 code/data/model/checkpoint，亦不得使用 HF Jobs/Endpoint/Space/Bucket。普通公开源码/文档和依赖下载允许，但正式依赖必须冻结身份。
15. **finally-style 止费。** 成功、NO-GO、异常或 blocked 都先尽力回收必要小型证据，再 stop/delete 本任务 Pod、临时卷和明确创建的附属对象，并复核
    task-scoped active cost 为零。只下载 receipt/log/config/manifest/hash/聚合资源事实；full smoke checkpoint 在证明恢复后可删，不要求长期回收本地。
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
- 已建立本 ExecPlan 与 WBS 规划指针；本规划阶段没有创建/修改 RunPod 资源、上传数据、下载/加载完整模型、训练、运行 Docker/重型构建或产生
  Plan 060 云费用。

### 当前工作

- ExecPlan 已冻结，等待用户把含阶段 A—D 一次性授权的执行提示词交给执行者，在现有 task worktree 内实施。

### 本任务剩余步骤

- 完成阶段 A 本地设施、focused tests、verified bundle、实时只读 readiness review；不通过则不购买。
- 在一次授权内完成阶段 B commissioning，保留有效进度并修复普通设施问题。
- 冻结最终身份，从干净训练状态完成阶段 C 正式 smoke、full checkpoint 与新进程继续。
- 完成阶段 D 证据回收、止费/删除、费用与 B1c 余量复算、执行者自检、文档/日志和 worktree 提交。
- 由计划制定者独立复核代码、focused tests、正式 receipt/billing、远端终态和结论；整改普通 finding 后完成最终 GO/NO-GO。

### 阻塞项

- 当前无代码阻塞。付费执行尚未由本规划会话启动；执行者只有收到用户明确的一次性授权提示词后才能进入任何 RunPod create/upload/train 动作。

### 当前验收状态

- `NOT_STARTED`：当前只有规划与公开只读 metadata 事实，没有 H100 BF16 全参数、FlashAdamW、C1/C2/C3、checkpoint/new-process、资源、费用或清理证据，
  不构成 M3-B1b GO/NO-GO。

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
| 003 | 整个任务只创建一个 RunPod H100 PCIe 80GB Pod 对象，允许重启同一对象但不允许 replacement | 与本任务单 Pod、单 GPU、无并发边界一致，消除 create 超时后的重复创建风险 | 云生命周期 | 已采纳 |
| 004 | 复用 Plan 054/059 输入与数据 seam，新建职责明确的 Publication Critic full-model trainer；不复用 L6 QLoRA/adapter 训练语义 | 输入合同契合而训练目标不契合，专用能力比扭曲旧设施更干净 | 架构、训练 | 已采纳 |
| 005 | Binary 与两类 Pair 共享 `logits[:,0]` raw scalar；具体稳定 loss、权重和 batch 混合留给执行者冻结 | 锁住正确语义，保留依据 H100 实测选择实现的空间 | objective、recipe | 已采纳 |
| 006 | Commissioning 后才冻结正式身份，并从新训练状态完整重跑；允许复用身份未变的 cache | 保留调试进度、减少付费浪费，同时隔离正式证据 | 运行、证据 | 已采纳 |
| 007 | Plan 060 硬上限 6 USD；M3-B1c 可用额始终按 `23 - actual_plan060_cost` 计算 | 让重试与等待如实计费，不预先虚构固定 17 USD | 预算、结论 | 已采纳 |
| 008 | 资格终态为 GO/NO-GO；纯设施/账单/清理阻断单列 BLOCKED/INCONCLUSIVE 且不解锁 B1c | 避免把缺失证据误报为路线失败或通过 | 失败、交接 | 已采纳 |
| 009 | 执行者只提交 task worktree；合并、推送、分支归档与 worktree 删除等待用户批准 | 遵守本轮最新交付要求并保留独立验收现场 | Git、交付 | 已采纳 |
