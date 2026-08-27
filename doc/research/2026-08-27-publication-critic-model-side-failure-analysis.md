# Publication Critic 模型侧失败归因：Plan 094 后的综合分析

日期：2026-08-27
性质：形成时点冻结的研究分析，不是当前规划。当前阶段、后续工作包与授权状态只以
[`doc/WBS.md`](../WBS.md) 和
[`doc/WBS/multi-agent-trusted-evidence.md`](../WBS/multi-agent-trusted-evidence.md) 为准。

本报告承接并更新
[`2026-08-26 Publication Critic 模型路线结果与根因分析`](2026-08-26-publication-critic-training-route-outcome-analysis.md)。
旧报告保留其形成时点的历史判断，不直接改写；本报告加入 Plan 090 的 Route O 干净重复和 Plan 094 的连续训练终态，重新评估各类解释的
相对可信度。

## 1. 结论摘要

Plan 094 以 `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT` 完成后，Publication Critic 的模型侧失败已经不再适合主要解释为“训练设施尚未
打通”“某个 checkpoint 不可信”或“只差找到正确的参数更新范围”。跨 Plan 066、079、082、087、090、094 的证据已经覆盖：

- exact 1.7B 与同家族 exact 4B 原始 reward base；
- BF16 全参数、FP32 score-head、BF16 多种末层/多层原参数范围；
- 从 `2,048` 个参数到 `1,720,577,024` 个参数的更新尺度；
- 多组学习率、objective 权重、scheduler、weight decay、一步与连续多步更新；
- H100、RTX 4090、L40S 上的真实运行；其中训练路线另有完整 checkpoint、跨进程恢复和同口径评价证据；
- Route O 的搜索发现、两次 clean 数值/执行重复、真实 FP32 条件对照和四步连续训练轨迹。

这些尝试没有形成一个能改变 strict、balanced/operating 或关键排序事件的 better-than-base 候选。Plan 094 更进一步表明，Route O 的一步
弱信号不会随连续更新放大：step 2 起 validation raw Boundary 反转为负，step 1--4 的 balanced accuracy、best balanced accuracy、
false-PASS、Boundary/Within-PASS strict win rate始终不变；训练集自身也没有形成稳定的 raw pair、AUC 或 operating 改善。

因此，当前最可信的综合判断是：

1. **工程链与参数更新执行不是直接失败层。** 参数确实更新，模型确实变化，checkpoint/恢复/评价均有效；Plan 094 的负向终态不是
   infrastructure failure。
2. **单一更新范围、精度或普通超参数不是主要解释。** 宽、窄、中等范围以及 BF16/FP32 都已出现不同形式的失败；继续在相同模型、任务和
   小数据上搜索更多相邻 scope，边际信息价值已经很低。
3. **失败的主要归因重心已经转移到“模型—任务—数据”匹配。** 当前 Skywork reward-model family 对 Publication Critic 的细粒度、
   强上下文依赖发布判断缺乏足够原始可分性；现有任务把多种发布缺陷压进单一标量与相互牵制的监督目标；冻结训练集规模小、同质、pair family
   不平衡，难以把这些语义稳定写入模型。
4. **“模型参数量不够”没有得到支持。** 4B base 与 1.7B base 的 ROC AUC 都约为 `0.62`，4B 没有产生实质质量收益；更像是同一家族的
   任务对齐不足，而不是简单扩大参数量即可解决。
5. **不能宣称某一个因素已经被单独证明为根因。** 现有证据可以把更新工程降级为次要解释，并把研究重点转向模型家族/表示、任务定义与
   数据覆盖，但尚不能在三者之间给出严格比例，也不能证明 1.7B 在任何新数据或新任务表述下都不可能成功。

一句话概括：**Publication Critic 当前不是“训练没有跑起来”，而是“训练链能稳定改变模型，却没有足够、稳定且方向一致的任务信号可供模型
学成有用的排序能力”。**

## 2. 证据范围与结论口径

本报告区分四层结论：

- **设施正确性**：模型载入、梯度、参数更新、checkpoint、恢复、测评和资源收口是否真实有效。
- **训练动态**：模型输出是否按训练推进发生可测变化，以及变化是排序、区分度还是公共 calibration 移动。
- **当前配置的效果**：冻结模型、数据、任务表述和训练 recipe 是否形成同口径 better-than-base 候选。
- **普遍能力结论**：某个模型规模、模型家族、pair 思想或 Publication Critic 产品概念是否在任何合理方案下都不可行。

现有证据对前三层给出了不同性质的结论：设施正确性为正向，训练动态为“有真实变化但没有有效质量事件”，当前冻结配置的效果则为负向；这些
结论仍不足以支持第四层的永久否定。特别是：

- `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT` 只否定 Plan 094 冻结的 exact 1.7B、v8、Route O 与连续训练轨迹；
- 4B 只运行过原始 base 评价，没有接受 Publication Critic 专用训练；
- unseen 始终封存，当前没有独立分布或真实发布流结论；
- Plan 090/094 的冻结路径没有有效 shuffle、dropout 等 seed-sensitive consumer，不构成随机 seed 稳定性试验。

主要证据来源：

- [Plan 075 NO-GO 原因研究](2026-08-25-plan075-publication-critic-no-go-route-decision.md)
- [旧版跨路线根因分析](2026-08-26-publication-critic-training-route-outcome-analysis.md)
- [Plan 073 联合横评](../../eval/results/publication-critic/m3-c2-joint-selection-v1.md)
- [Plan 079 4B base 质量结果](../../eval/results/publication-critic/skywork-reward-v2-qwen3-4b-base-quality-v1.md)
- [Plan 082 连续训练正式记录](../../agent_log/2026-08-26-024217-plan082-stage-b-formal.md)
- [Plan 087 自适应路线搜索](../../eval/results/publication-critic/plan087-adaptive-search-v1.md)
- [Plan 090 Route O 干净确认](../../eval/results/publication-critic/plan090-route-o-confirmation-v1.md)
- [Plan 094 Route O 连续训练](../../eval/results/publication-critic/plan094-route-o-continuous-v1.md)
- [Plan 094 最终独立验收](../../agent_log/2026-08-27-023839-plan094-final-review.md)

本报告只读取已经形成的受跟踪结果、任务日志和 Plan 094 小型正式交接中的 train/validation 聚合；没有运行模型、训练、Cargo、Docker、
真实 API/Judge，也没有读取或释放 unseen。

## 3. Plan 094 新增了什么证据

### 3.1 它关闭了“一步 Route O 也许只是还没训练够”的主要缺口

Plan 087 发现 Route O 时只有一次 full-cohort update。Plan 090 又从 exact base 两次 clean 执行同一个 BF16 一步 recipe，得到了完全相同的
validation signature，但由于正式路径没有真实 seed-sensitive consumer，它只证明执行/数值重复，不能回答继续训练是否会放大效果。

Plan 094 保持 exact 1.7B、v8 train/validation、pair/input/objective family 和 Route O 九张量不变，从 exact base 的干净 fallback 建立
连续正式轨迹。四个观察点都在完整 checkpoint 原子落盘、深读资格化之后测评；step 2 和 step 3 分别由新 OS 进程恢复并继续到下一步。
因此，下表变化是同一有效训练轨迹，而不是进程拼接、工件错绑或测评漂移。

| validation 相对同轮 base | step 1 | step 2 | step 3 | step 4 |
|---|---:|---:|---:|---:|
| raw Boundary mean margin | `+0.003906` | `-0.005140` | `-0.010074` | `-0.010691` |
| projected Boundary | `+0.000861` | `+0.000914` | `+0.001317` | `+0.001419` |
| raw Within-PASS | `-0.003348` | `-0.011161` | `-0.010045` | `-0.006696` |
| projected Within-PASS | `+0.000139` | `-0.000038` | `+0.000183` | `+0.000480` |
| ROC AUC | `+0.001401` | `+0.000700` | `+0.001401` | `+0.000700` |
| meaningful event | `0` | `0` | `0` | `0` |

所有 step 的 balanced accuracy、best balanced accuracy、false-PASS、Boundary strict win 和 Within-PASS strict win 都没有变化。step 2 后
raw Boundary 不仅没有继续上升，反而稳定落到 base 以下；raw Within-PASS 全程没有正向改善。预冻结的连续三个 checkpoint 无 material
improvement 平台规则因此在 step 4 正确形成有效负向终态。

### 3.2 projected 微升与 raw 反转进一步暴露 calibration 假象

step 2--4 的 projected Boundary 继续微升，而 raw Boundary 已经变差。这与 Plan 087 多条路线中“raw 负、sigmoid 后 projected 微正”的
现象一致：base logits 位于较高正值区域时，共同下移或局部压缩会改变 sigmoid 导数，使 projected margin 看似改善，却不一定增加原始
排序间隔。

如果训练真的在稳定学习发布质量，至少应在 raw pair、离散 ordering、strict 或 operating 指标之一形成一致事件。Plan 094 没有观察到这些
变化。因此 projected 微升不能继续作为 Route O 有效训练的代理。

### 3.3 训练集自身也没有出现“先学会、后泛化失败”

Plan 094 首次为 Route O 连续轨迹保留了同口径 train observation。下面是 train 的关键绝对值：

| train 指标 | base | step 1 | step 2 | step 3 | step 4 |
|---|---:|---:|---:|---:|---:|
| raw Boundary mean margin | `0.592305` | `0.593066` | `0.589746` | `0.590078` | `0.589307` |
| raw Within-PASS mean margin | `-0.357422` | `-0.357422` | `-0.357422` | `-0.356445` | `-0.360352` |
| ROC AUC | `0.642575` | `0.641586` | `0.641710` | `0.642081` | `0.642204` |
| best balanced accuracy | `0.618730` | `0.618730` | `0.618730` | `0.618730` | `0.618730` |
| weighted objective loss | `0.846896` | `0.846203` | `0.846661` | `0.845983` | `0.847272` |

step 1 的 train raw Boundary 只增加约 `0.000762`，随后跌到 base 以下；train Within-PASS 在 base 时已经为负，四步间几乎不动，step 4
反而更差；AUC 和 best balanced accuracy 没有形成提升。weighted loss 只在 `≈0.001` 范围振荡，step 4 还高于 base。

这使“模型已经在 train 上学会，只是 validation 分布偏移”不再是完整解释。train/validation shift 仍可能存在，但更直接的现象是：在当前
表示、任务和监督组合下，Route O 连训练集上的目标结构都没有形成强而稳定的可学习改善。

### 3.4 它再次排除了 no-op、恢复和流程错误

Plan 094 的 guarded Plan 090 import 因历史 controller cursor 不兼容而按合同拒绝，正式运行使用预冻结 exact-base fallback，没有拼接部分
状态。steps 1/3/4 checkpoint 均在挂载卷上完成深读资格化；不同进程恢复 step 2、step 3 并继续；finalizer 能只依赖回传小包、资格 receipt
和 zero-Pod 状态重放相同终态。最终独立审查为 0 High / 0 Medium。

因此，Plan 094 的负向结果不是由“旧 checkpoint 没有真正恢复”“训练从错误 cursor 开始”“测评先于 checkpoint”“Pod 中断”或“结果
finalizer 自说自话”造成。

## 4. 跨实验失败图谱

| 实验 | 模型/更新范围 | 主要观察 | 对根因判断的贡献 |
|---|---|---|---|
| Plan 066/073 | 1.7B BF16 全参数，三阶段宏更新 | C1/C3 输出跨度与排序塌缩，AUC 低于 base | 证明宽更新能改变模型，但既有强 recipe 破坏质量 |
| Plan 079 | 4B BF16 原始 base | AUC `0.6218`、best balanced `0.655`，无合格 operating point | 否定“同家族增大参数量自然解决任务” |
| Plan 082 | 1.7B FP32 score head，四步 | 真实参数变化，几乎只产生公共 offset，排序不变 | 证明窄线性头表达/梯度方向不足 |
| Plan 087 A--N | 1.7B BF16，2K--201M 多种 scope/recipe | 大多数 raw pair 退化，strict/operating 不动 | 显著降低单一 scope、LR、scheduler、权重解释 |
| Plan 087 O | 1.7B BF16，33.559M internal-only | 一步 raw Boundary `+0.003906`，但 within 退化、离散指标不动 | 形成值得确认的弱信号，而非有效候选 |
| Plan 090 | O 两次 clean BF16 + 一次 FP32 条件对照 | BF16 弱 signature 可重复；FP32 raw Boundary 为负，raw/projected 分歧 | 证明弱信号是确定性路径结果，同时显示精度敏感但非解决方案 |
| Plan 094 | O 四步 checkpoint-first 连续训练 | step 2--4 raw Boundary 反转，train/validation 均无 material event | 关闭“多训练几步即可放大 O”的主要缺口 |

失败模式并不完全相同：全参数 recipe 会塌缩，head-only 只移动 calibration，中等范围常产生格点化微动，Route O 则在第一步出现可重复但不
具实际意义的局部信号。正因为多种工程路径都能真实改变参数、却都不能形成稳定任务质量，这组证据更符合上游“可供学习的任务信号不足或不
匹配”，而不是下游“训练循环没工作”。

## 5. 已排除或已显著降级的解释

### 5.1 基础设施、训练 no-op 或工件错误

已经有真实梯度、参数变化、完整 checkpoint、跨进程恢复继续、同轮 base、正式评分和逐字节结果复算。Plan 060/066、082、087、090、094
分别从不同角度重复了这些事实。它们足以排除基础设施未执行作为直接原因。

### 5.2 只需调整 threshold 或 calibration

Plan 073/079 已搜索完整 operating curve，AUC 与 pair ordering 仍不达标；Plan 094 中 projected margin 上升而 raw/strict/operating 不动，
进一步说明 calibration 变化不能代替排序能力。threshold 可以移动决策点，不能创造缺失的 ordering。

### 5.3 pair 方向、label sign 或 objective 调用方向反了

既有数据合同、方向测试、非零梯度、preferred-minus-dispreferred 语义及训练/评价复核一致。若方向整体反转，更难解释 base 仍有约
`15/19` Boundary strict wins、Route O 各 pair 有混合改善/不变/退化，以及不同 scope 呈现不同模式。现有证据不支持明显 sign bug。

### 5.4 单一更新范围太窄或太宽

已测试 score head、final norm、单个输出投影、完整末块、末块内部九张量、两个末块、四个末块与全模型。范围大小与质量没有单调关系；
201M 或全参数没有解决问题，2K head 也没有。Route O 是相对最好的一条，但连续训练仍失败。

### 5.5 LoRA、量化或 adapter 限制

这些模型侧训练均更新原模型参数；Plan 082/087/090/094 没有使用 LoRA、QLoRA、其它 PEFT 或量化训练。因此不能把失败归因于 adapter
容量或量化误差。

### 5.6 单纯 BF16 数值分辨率

BF16 格点和 raw/projected 分歧确实存在，也可能掩盖微小更新；但 Plan 082 的 FP32 score-head 路线没有改善排序，Plan 090 的真实 FP32
条件对照也没有通过同一 rubric。数值精度会影响观察形态，却没有证据表明换成 FP32 就能产生缺失的任务能力。

### 5.7 模型参数量不足这一单因素

4B base 的 AUC、balanced accuracy 和 Boundary 不优于 1.7B 到足以改变路线。它改变了 false-PASS/false-REWRITE tradeoff，却没有解决
排序。因而“继续换同家族更大参数量”缺乏已有证据支持。仍不能排除完全不同模型家族、任务专用预训练或训练后的 4B 有不同结果。

## 6. 当前最可信的模型侧原因

以下排序不是严格因果分解，而是依据现有证据给出的可信度排序。

### 6.1 高可信：reward-model 家族与 Publication Critic 语义对齐不足

exact 1.7B 和 exact 4B 原始 base 的 ROC AUC 都约 `0.62`。这说明模型在训练前只含有限的任务可分信号；扩大家族内参数量几乎没有增加
ordering。Publication Critic 要判断的不是一般“回答质量”或偏好，而是拟发布公共状态是否：

- 与既有状态和证据一致；
- 在完成/未完成、旧事件/新事件之间表述准确；
- 传递了足够但不过度的 useful state；
- 保留诚实不确定性、scope 和 continuity；
- 避免遗漏会误导后续协作的关键信息。

这些判断高度依赖长上下文中的项目状态、角色、时间和证据关系。通用 reward model 可能能识别语言流畅度、礼貌、完整感和一般偏好，却未必
已经形成上述“公共状态语义”的稳定内部表示。Plan 082 的线性 head 不能从 frozen representation 中读出更好排序，Plan 087/094 的末层
更新又只能制造微小、方向不稳的变化，均与表示对任务不够可分这一解释相容。

这是一个**模型家族/预训练任务对齐**判断，不是“1.7B 参数绝对不够”。4B 的失败反而说明，当前主要缺口不是同家族容量。

### 6.2 中高可信：当前模型、数据与单标量任务组合呈现结构性冲突

产品最终只需要 PASS/REWRITE，但训练同时包含 binary calibration、Boundary preference 和 Within-PASS preference。三者并非天然同一方向：

- binary 关心跨类别分离和阈值；
- Boundary 关心从不合格到合格的修复方向；
- Within-PASS 关心两个都可发布对象之间的细粒度优先级；
- 一个更“保守”的共同下移可能改善 false-PASS，却损害可发布内容；
- sigmoid 高分区的 projected 改善可能与 raw ordering 退化并存。

Plan 082 的共同下移、Plan 087 多数路线的 pair tradeoff、M/N 极端重权仍失败，以及 Plan 094 train Within-PASS 长期为负，都说明这些目标在
当前模型与数据上的单标量表示没有汇成稳定公共梯度。这里不支持“objective 实现错了”，更像是**当前任务分解、模型表示与单标量监督不够
匹配**。但项目没有完成替代任务表示或多头监督对照，也没有保存足够的逐 objective 梯度关系；因此不能把这种冲突外推为单标量任务定义本身
普遍不可行。

### 6.3 高可信：训练数据规模和覆盖不足以稳定约束当前任务

v8 train 只有 128 candidates、58 pairs，来自 70 个 scenario；其中 Boundary 50 对、Within-PASS 只有 8 对。validation 为 55 candidates、
26 pairs、28 个 scenario。相对于 Route O 的 `33,558,784` 个可训练参数，更不用说 1.7B 全参数，这个监督规模非常小。

更关键的是覆盖结构：

- Within-PASS 只有 8 个 train pairs，却在 Route O objective 中承担很高权重；旧报告估算单个 within pair 的近似梯度杠杆约为单条 binary
  的 224 倍、单个 Boundary 的 17.5 倍。
- 228 个 candidate 的生成/复核元数据来自同一教师模型家族，表达、错误样式和裁决习惯可能同质。
- 121/123 scenario 为合成资产；合成不等于标签错误，但更容易形成模板、措辞和缺陷组合上的窄覆盖。
- 全数据 178,646 tokens 中 candidate 正文约 20,170 tokens，仅 `11.3%`；其余主要是 policy、continuity 和 framing。最大输入约
  2,094 tokens，现有证据不支持截断，但真正需要判别的候选信号在大量相似上下文中占比较低。

Opus 5 与 validation 冻结标签一致 53/55，足以反驳“validation 标签整体失真”，但不能据此证明 train 标签或全数据语义噪声已经得到异构
复核。即便 validation 标签整体可靠，“标签可靠”与“训练数据足够多样、足以学习”仍是不同命题；当前证据更支持覆盖与信息增量不足，而不是
validation 标签整体崩坏。

此外，Plan 087 用同一 development validation 自适应选择 Route O，Plan 090/094 又在该集合上确认和延长路线。重复使用会使观察到的收益偏
乐观，而不是提供独立泛化证据；Route O 连这个开发集合上的弱信号都无法放大，强化了“当前配置无实质改善”的判断，但不能量化新分布表现。

### 6.4 中高可信：数据与任务共同造成 train 信号弱、family 间相互抵消

Plan 094 的 train raw Boundary 在 step 1 只微升，随后转负；train Within-PASS 在 base 就为负并基本不动；best balanced accuracy 完全不变。
这说明问题并非单纯 validation winner's curse。模型在训练样本上也没有获得强而一致的排序改进。

可能的机制包括：

- 不同 defect family 的梯度方向相互抵消；
- 8 个 Within-PASS pair 无法代表 validation 的细粒度偏好；
- 同质样本提供大量重复表面信号，却缺少能改变内部表示的语义差异；
- 单次 full-cohort 聚合把 scenario-specific 信号平均掉；
- reward base 对长上下文中的关键信息位置不敏感，导致训练更多改变 score calibration 而非语义表示。

现有结果没有保存足够的逐 objective 梯度余弦，无法在这些机制间严格排序。但不论是哪一种，都更接近“任务/数据提供的可学习信号结构”而非
checkpoint 或云端工程故障。

### 6.5 中可信：last-token 单标量读取方式可能限制细粒度证据建模

现有 scorer 从完整渲染输入得到单一标量。对于候选占比较低、上下文中包含大量 policy/continuity/evidence framing 的任务，模型必须先在
隐藏状态中整合多个远距离关系，再由一个标量同时表达可发布性和细粒度 pair preference。

Plan 082 说明仅重训最终 score head 基本只能移动公共 offset；Plan 087/094 说明只调整最后 block 的部分内部变换也未形成稳定排序。这与
“任务所需信息没有在最终表示中以简单可读形式出现”相容。不过，本项目没有完成冻结 hidden-state 的分层 probe 或其它表示诊断，所以这仍是
结构性推断，不是已证实的架构根因。

## 7. 为什么不再把参数更新方法作为主要路线

“参数更新方式不是主要解释”不等于“所有优化器和超参数都被穷尽”。现有实验没有系统搜索所有 batch、scheduler、optimizer、loss 或
训练时长，也没有证明另一种完全不同的训练算法必然失败。

但研究优先级应由边际证据决定：

1. 全参数强更新已经证明能大幅改变模型，但会破坏排序。
2. FP32 窄更新证明真实参数变化不等于获得 pair 能力。
3. A--O 已覆盖广泛 scope、LR、权重和 scheduler，未出现稳定双 family raw 改善。
4. Route O 的确定性弱信号经两次 clean 重复后仍只对应一个 ordering，连续训练又在 step 2 起反转。
5. Plan 094 连 train 指标都没有形成稳定改进，说明继续围绕同一小数据调优化细节，容易只是在同一受限信号上寻找偶然点。

因此，新的相邻 optimizer/scope 尝试即使偶尔得到一个 validation 小赢家，也很难改变对泛化与产品价值的判断。除非模型、任务表示或训练数据
至少有一项发生有目的的改变，否则继续参数更新搜索的预期信息收益已经低于成本。

## 8. 仍不能确认或不应越界的结论

- 不能宣称 Skywork 1.7B 在任何 Publication Critic 训练方案下都不可能改善。
- 不能宣称 pair 设计思想失败；现有 pair 很可能正是暴露 calibration 与真实排序差异的关键设施。
- 不能宣称数据标签错误。异构 Judge 高一致率反而支持 validation 标签整体可靠。
- 不能宣称只有扩大数据即可解决；如果模型家族缺乏合适表示或任务标量化不合理，更多同质数据可能只是重复现有问题。
- 不能宣称 4B 训练失败；它只完成 base 测评。
- 不能把 Plan 090 的两次执行称为随机 seed 稳定性。
- 不能从 validation 推断 unseen 或真实 RONDO Multi 发布流表现；unseen 始终没有读取或释放。
- 不能把 `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT` 外推为 Publication Critic 产品概念本身不可行。

## 9. 对后续研究方向的含义

本节只记录证据导出的研究优先级，不构成现行 WBS 或已授权任务。

### 优先级应提高

- **模型/表示适配性**：判断候选模型在不训练或轻量 probe 下是否已经包含 Publication Critic 各 defect family 的可分表示；比较不同预训练
  目标或不同模型家族比继续同家族扩参更有信息价值。
- **任务分解**：重新审视一个标量是否应同时承担 binary gate、Boundary 修复排序和 Within-PASS 细粒度偏好；pair 思想可以保留，但监督
  组织未必必须维持当前单标量组合。
- **数据覆盖与多样性**：增加真实或异构生成来源、defect family 平衡、复杂组合与更丰富 Within-PASS 对；重点是信息增量，不是机械复制
  当前模板。
- **训练信号诊断**：在不建设重型因果平台的前提下，保存各 objective 的 train 改善与必要梯度关系，用于判断新数据/任务表述是否真正提供
  一致信号。

### 优先级应降低

- 在同一 55 条 development validation 上继续追加 Route P/Q/R 或相邻 scope；
- 只调整 threshold、sigmoid 投影或 calibration 后宣称质量改善；
- 继续同家族按参数量扩大 base，而不先验证任务对齐；
- 在现有小数据上做无边界 optimizer/LR 搜索；
- 因 checkpoint 可恢复、loss 微降或 projected margin 微升就把工件升级为候选。

如果未来形成新的模型、任务或数据路线，应继续保留当前有效原则：pair 方向不变、train/validation/unseen 隔离、调试全链打通后再运行干净
正式轮、候选必须越过 raw/ranking/strict/operating 的实质门，而不是复用 Plan 094 的预算或外部授权继续试跑。

## 10. 最终判断

- Plan 094：**验收通过、任务目标完成、`ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT / ZERO_POD`**。
- Route O：一步弱信号可确定性重复，但不能随连续训练扩大；step 2--4 raw Boundary 反转，train/validation 均无 material event，研究路线
  应在当前模型/任务/数据组合下收口。
- 工程与更新执行：训练、checkpoint、恢复、测评和资源链有效；它们不是当前直接失败层。普通参数更新细节仍可能影响数值，但已不应作为首要
  研究方向。
- 模型：Skywork Reward V2 Qwen3 1.7B/4B family 对冻结 Publication Critic 语义只有约 `0.62` AUC 的基础信号，同家族扩参没有解决排序。
- 任务：binary、Boundary、Within-PASS 的多目标语义压进单标量后呈现持续 tradeoff，当前表述可能超出通用 reward 表示的直接可读能力。
- 数据：validation 标签整体可靠，但 train 标签与全数据语义噪声尚未得到充分异构复核；训练规模、Within-PASS 覆盖、来源多样性和候选信号
  占比不足，难以支撑稳定表示更新。
- 综合归因：**当前失败最明显地指向模型家族/表示与任务定义、数据覆盖之间的系统性不匹配，而不是某一个参数更新方法或工程细节。**
  这是一项高可信的研究方向判断，不是三因素间的严格因果分摊，也不是对 Publication Critic 或 pair 监督思想的永久否定。
