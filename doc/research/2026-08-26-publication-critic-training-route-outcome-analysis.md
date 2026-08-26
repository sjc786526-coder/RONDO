# Publication Critic 模型路线结果与根因分析

日期：2026-08-26
性质：形成时点冻结的研究分析，不是当前规划；后续路线只以 `doc/WBS.md` 与 `doc/WBS/*.md` 为准。

## 1. 结论摘要

截至本报告形成时，Publication Critic 的训练与云端执行链已经被反复证明可用，但仍没有一个可以称为“效果可靠”的 better-than-base
候选。Plan 087 的 Route O 达到了该搜索任务约定的 `PROMISING_CANDIDATE_RETAINED` 启发式终点，因此 Plan 087 本身执行成功；不过它的
改善很小、来自第 15 条共用 validation 的自适应路线，尚未经过从 exact base 的干净复现，不能升级为稳定效果、独立泛化或产品候选。

最可信的总体解释不是某一个基础设施故障或单一坏超参数，而是以下几项共同形成了狭窄的“可训练区间”问题：

1. exact 1.7B 与 exact 4B 原始 reward base 在冻结 Publication Critic 语义上的排序能力都只在 ROC AUC 约 `0.62`，模型变大没有自动补足
   任务判别能力。
2. Plan 066 的 `4e-4` BF16 全参数宏更新足以大幅改变输出，却把 logit 区分度和排序压塌；Plan 082 的 FP32 score-head-only 小步更新则
   几乎只学到共同 logit 下移，不能重塑排序。两端分别表现为“过强且破坏性”和“真实但表达力不足”。
3. Plan 087 在末端原参数中寻找中间区间。A–N 大多仍以共同下移、离散微动和 boundary/within-PASS tradeoff 为主；Route O
   排除末块输出投影，仅更新内部输入变换与归一化后出现最好的弱信号。这提示不同末块模块对当前配方的响应不同，但 update 数、objective
   与自适应选择均有混杂，不能判断输出投影是否抵消了 Route O。
4. v8 的 train 只有 128 candidates、50 boundary pairs 和 8 within-PASS pairs；validation 只有 55/19/7。数据标签整体并未显示错误，
   但样本量、合成分布和 pair-family 覆盖是否足以支撑数千万到 17 亿参数的稳定泛化，现有证据不能确认。它很可能放大了优化冲突和
   winner's curse，却不能被单独宣布为根因。
5. Plan 087 连续观察同一 validation 并据此设计 15 条路线，符合本任务的启发式搜索合同，但这批 validation 已实际成为开发集。
   Route O 的小幅赢家信号必须在预先冻结 recipe 后独立复现，才能判断它是真实可重复效果还是搜索噪声。

因此，当前不应得出“1.7B、pair 监督或原参数训练整体失败”的结论。可以确认的是：既有的激进全参数 recipe、4B 原始 base、具体
score-head-only recipe，以及 Plan 087 的 A–N 配方都没有产生可靠提升；Route O 是值得优先复现的研究线索，而不是已确认的解决方案。

## 2. 结论口径与证据范围

本报告把三种结论严格分开：

- **执行/设施成功**：模型、数据、更新、checkpoint、恢复、评测与止费链按合同工作。
- **任务终态成功**：研究任务诚实得到约定终态，例如 `VALID_NO_IMPROVEMENT` 或 `PROMISING_CANDIDATE_RETAINED`。
- **效果可靠**：预先冻结路线从 exact base 干净重跑，能再次产生足够大的同向改善，并经后续独立数据/资格任务确认。

Plan 060、066、082、087 都有有效训练证据；Plan 079 有有效 4B base 推理证据。它们中的“失败”主要指没有可靠 better-than-base
质量效果，不应误写为 GPU、恢复或实现失败。Plan 081 只建立本地 fixture/fake 训练控制设施，没有加载或训练真实模型，不能计为一次模型路线。

v8 的 128 个 train candidates 实际来自 70 个 scenario，55 个 validation candidates 来自 28 个 scenario，split 间 scenario 严格隔离；
同 scenario 的候选/pair 并非完全独立语义单元。全数据 178,646 tokens 中 candidate 正文约 20,170 tokens（`11.3%`），其余主要是
policy、continuity 与 framing。长而相似的规则/上下文是任务所需，不是截断错误，但会提高“从 last non-pad token 的单一标量辨认细粒度差异”
的难度。最大输入约 2,094 tokens，现有证据不支持上下文截断是失败原因。

228 个 candidates 的 generator/reviewer 记录都来自 `gpt-5.6-sol`，说明训练表达和错误分布可能较同质。此前异构盲评与 validation 标签
一致 53/55，只支持 validation 标签整体可靠，不能证明 train 的表达多样性或覆盖充分。

主要权威材料：

- [Plan 075 冻结原因研究](2026-08-25-plan075-publication-critic-no-go-route-decision.md)
- [1.7B base/C1/C3 联合质量结果](../../eval/results/publication-critic/m3-c2-joint-selection-v1.md)
- [4B base 正式质量结果](../../eval/results/publication-critic/skywork-reward-v2-qwen3-4b-base-quality-v1.md)
- [Plan 082 正式执行摘要](../../agent_log/2026-08-26-024217-plan082-stage-b-formal.md)
- [Plan 082 最终审查](../../agent_log/2026-08-26-045732-plan082-final-review.md)
- [Plan 087 路线与终态结果](../../eval/results/publication-critic/plan087-adaptive-search-v1.md)
- [Plan 087 最终验收](../../agent_log/2026-08-26-133503-plan087-final-acceptance.md)

Plan 082/087 的逐 observation、完整 route result 和 checkpoint receipt 位于 git-ignored handoff/运行目录；本报告只读取已有小型证据，
没有重跑模型、训练、unseen 或云资源。

## 3. 历史尝试逐项分析

### 3.1 Plan 060：1.7B 全参数技术资格，不是质量试验

Plan 060 在 exact 1.7B、BF16、单 H100 上使用 FlashAdamW 更新全部 `1,720,577,024` 个参数，并证明 checkpoint 与新进程恢复可行。
其 v7 smoke 只有 6 个 Binary、1 个 Boundary 和 1 个 Within-PASS 样本，C1/C2/C3 各做一次宏更新，学习率为 `4e-4`。

它的正式终态是 `TECHNICAL_GO`，目标只是在预算内证明全参数训练链可运行，不要求 loss、排序或质量改善。因此：

- 能确认：1.7B 全参数 BF16 训练、保存和恢复在单卡上技术可行。
- 不能确认：该 recipe 具备质量价值，或者小 smoke 的输出变化可泛化到 v8。
- 不应称为“训练质量失败”；真正的质量否定来自后续 Plan 066/073。

### 3.2 Plan 066/073：1.7B BF16 全参数更新后的质量塌缩

Plan 066 把同一全参数 recipe 用于 v8 train：128 Binary、50 Boundary、8 Within-PASS，C1/C2/C3 各一次 full-stage 宏更新；LR `4e-4`、
constant scheduler、clip `1.0`，三阶段 objective 从 binary-only 逐步加入 pair 分量。训练执行、311 个 optimizer tensors、三份候选、完整
checkpoint 与新进程恢复都有效。

同口径 validation 的关键结果是：

| 对象 | balanced accuracy | ROC AUC | Boundary strict wins | raw-logit 跨度 |
|---|---:|---:|---:|---:|
| exact base | `0.666` | `0.6169` | `15/19` | 约 `9.56` |
| C1 | `0.524` | `0.3894` | `5/19` | 约 `1.25` |
| C3 | `0.616` | `0.5567` | `10/19` | 约 `0.30` |

三个对象的完整 operating curve 都没有合格点。三个 pre-clip gradient norm 为 `346 / 89.5 / 24.375`，全部被 clip 到 `1.0`；binary mean
loss 为 `1.431 → 10.359 → 7.438`。输出跨度在一次或少数宏更新后急剧压缩，C1 的 AUC 甚至跌到随机以下。

**可确认的直接原因**：候选的 logit 区分度与排序质量塌缩；不是 threshold、部署 runtime、候选身份、漏打分、权重未更新或 checkpoint
损坏。Plan 066 的 `GO` 只是候选可交给下游评价，不是质量 GO。

**最可能但未单独确认的机制**：未经质量开发的全模型 `4e-4` 聚合更新发生 overshoot；大而方向不同的梯度全部被相同 clip 归一后，
每阶段仅一次更新且 objective 构成变化，导致灾难性压缩/遗忘。小型合成 train 相对 1.7B 参数可能放大过拟合，但只有一个 seed/recipe，
无法把 LR、clip、FlashAdamW、objective、scheduler 或数据中的任一项确认为唯一根因。C2 也没有按 Plan 073 同口径单独完成正式质量评价。

### 3.3 Plan 079：4B 原始 base 质量 NO-GO，不是 4B 训练失败

Plan 079 对 exact `Skywork-Reward-V2-Qwen3-4B` BF16 base 完成 55/55 正式评分，typed failure 为 0，且任务明确禁止训练。

| 指标 | 4B base | 冻结门限 | 结果 |
|---|---:|---:|---|
| False PASS | `12/21 = 0.5714` | `≤ 0.25` | 失败 |
| False REWRITE | `4/34 = 0.1176` | `≤ 0.35` | 通过 |
| Balanced accuracy | `0.6555` | `≥ 0.75` | 失败 |
| ROC AUC | `0.62185` | `≥ 0.80` | 失败 |
| Boundary | `13/19 = 0.6842` | `≥ 0.70` | 失败 |
| Within-PASS | `6/7 = 0.8571` | 仅报告 | — |

完整 97 点 threshold curve 没有可行点。raw logits 全部为强正值 `5.03125–15.6875`，PASS 与 REWRITE 大量重叠。与 1.7B base 相比，4B
减少了 false rewrite，却增加了 false pass；AUC 只约增加 `0.0049`，boundary 反而下降 `0.1053`。

**可确认的直接原因**：4B 原始 base 在冻结任务上仍缺乏足够的排序/区分能力，单纯换成同家族更大模型没有提供有效收益。强正 logit 与
sigmoid 饱和是高分偏置的症状，但 offset 不能解释 AUC 和 pair ordering 失败。

**不能确认**：4B 接受 Publication Critic 专用训练后是否能改善；失败来自 reward-model 原训练分布、模板交互、该 revision/head 特性，
还是小 validation 构成。因本任务没有训练 4B，不能写成“4B 训练路线失败”。

### 3.4 Plan 082：score-head-only 真实更新几乎只产生公共 offset

Plan 082 从 exact 1.7B 以 float32 加载，使用 AdamW、LR `1e-5`、weight decay `0.01`、三个 objective 等权，四次更新只训练原生
`score.weight` 的 2,048 个元素。四步参数最大单元素变化均约 `1.0e-5`，step 2 经另一 OS 进程恢复并继续更新，排除了 no-op 和恢复失败。

主指标从 base 到四步严格单调下降：

| step | raw boundary mean margin | 相对 base |
|---:|---:|---:|
| 0 | `0.8252560622` | `0` |
| 1 | `0.8252422810` | `-0.0000137812` |
| 2 | `0.8252285468` | `-0.0000275154` |
| 3 | `0.8252148064` | `-0.0000412558` |
| 4 | `0.8252007961` | `-0.0000552661` |

55/55 个 validation logits 在 step 4 全部下降，平均 `-0.1420861`，范围仅 `-0.1427257…-0.1410513`；样本间标准差约
`0.0004288`。26 个冻结 pair 没有 strict outcome 翻转；AUC、strict wins、threshold balanced accuracy 与 false-pass 都不变。

**可确认的直接原因**：更新几乎只改变全体分数基线，非公共残差太小，无法重塑 pair margin/排序；主比较指标还轻微退化，因此终态正确地是
`VALID_NO_IMPROVEMENT`。

**机制解释**：pair loss 只依赖 `preferred - dispreferred`，对共同 offset 不敏感；binary loss 对共同 offset 敏感。固定 backbone 后，
2,048 元素线性头只能重新投影既有 hidden representation。当前组合梯度找到了强公共下移方向，而 pair discrimination 方向很弱。
这比“LR 太小所以没有更新”更符合证据，但现有材料没有按分量保存梯度，不能严格断言 binary objective 是唯一来源，也不能区分 head 表达力、
训练动态和 train/validation shift 的贡献。

### 3.5 Plan 087：15 条中等范围原参数路线

Plan 087 固定 exact 1.7B、BF16、v8 train/validation、pair/input 语义与 unseen 隔离，从 exact base 分别启动 A–O。除 F 为两次更新外，
每条路线都只进行一次完整 train cohort 宏更新。所有路线的 base observation 完全一致；因此路线间变化不是 base 或 validation 漂移。

共同 base：raw boundary `0.810444`、raw within-PASS `0.375000`、projected boundary `0.083556`、projected within-PASS `0.015237`、
ROC AUC `0.620448`、strict wins `15/19` 与 `6/7`、report balanced accuracy `0.571429`。Plan 082 的 base 数值不能与这里直接解释为漂移，
因为 Plan 082 是 float32、Plan 087 是 BF16；有效比较都是各自正式轮内的 base-relative delta。

#### 3.5.1 全路线结果

权重顺序为 Binary / Boundary / Within-PASS；delta 均相对本路线 exact base。

| 路线 | 原参数 scope / 数量 | 关键 recipe | 更新 | Δ raw boundary | Δ raw within | Δ projected boundary / within | Δ ROC | 结论 |
|---|---|---|---:|---:|---:|---:|---:|---|
| A | score + final norm + block 27 / `50.340M` | `5e-6`, `.20/.50/.30`, WD `.01` | 1 | `-0.005962` | `-0.004464` | `+0.001092 / +0.000268` | `-0.000700` | 两类 raw margin 都退化 |
| B | score + final norm + blocks 26–27 / `100.676M` | `3e-6`, `.40/.35/.25`, warmup-decay | 1 | `-0.003701` | `-0.006696` | `+0.000928 / +0.000085` | `+0.002801` | projected/ROC 微动，raw 双退化 |
| C | score + final norm / `4,096` | `2e-5`, `.10/.50/.40` | 1 | `-0.006168` | `-0.005580` | `+0.000483 / ≈0` | `+0.000700` | final norm 没有形成排序能力 |
| D | score only / `2,048` | `1e-5`, `.10/.50/.40` | 1 | `-0.003084` | `-0.003348` | `+0.000095 / ≈0` | `+0.000700` | BF16 版窄 head 仍退化 |
| E | score + block 27 / `50.338M` | `3e-6`, `.70/.15/.15` | 1 | `-0.001028` | `-0.006696` | `+0.000604 / -0.000277` | `+0.000700` | binary-heavy 未解决 tradeoff |
| F | 完整 block 27 / `50.336M` | `5e-6`, `.05/.25/.70` | 2 | `-0.009663` | `-0.006696` | `+0.001645 / +0.000769` | `+0.000700` | step 1 弱 boundary 信号后在 step 2 反转 |
| G | `o_proj + down_proj` / `16.777M` | `5e-6`, `.05/.45/.50` | 1 | `-0.002673` | `-0.003348` | `+0.000589 / +0.000049` | `+0.000700` | 输出投影双退化 |
| H | attention `o_proj` / `4.194M` | `5e-6`, `.05/.60/.35` | 1 | `-0.001234` | `-0.006696` | `+0.000164 / -0.000185` | `0` | attention 输出对 within 尤其不利 |
| I | MLP `down_proj` / `12.583M` | `5e-6`, `.05/.30/.65` | 1 | `-0.002878` | `-0.004464` | `+0.000424 / +0.000018` | `0` | MLP 输出仍双退化 |
| J | 完整 block 27 / `50.336M` | `3e-6`, `.05/.70/.25` | 1 | `-0.004317` | `0` | `+0.000239 / -0.000099` | `0` | 降 LR/重 boundary 只保住 within 均值 |
| K | 完整 block 27 / `50.336M` | `3e-6`, `.05/.25/.70` | 1 | `+0.000822` | `-0.006696` | `+0.000497 / -0.000308` | `+0.001401` | boundary 太小且 within 明显回退 |
| L | blocks 24–27 / `201.344M` | `1e-6`, `.05/.25/.70` | 1 | `-0.006579` | `-0.021205` | `+0.000026 / -0.001284` | `0` | 扩大四层反而放大退化 |
| M | 完整 block 27 / `50.336M` | `3e-6`, `0/.01/.99` | 1 | `-0.006990` | `-0.012277` | `-0.000352 / -0.000647` | `+0.001401` | 极端 within-only 近似配方也双退化 |
| N | 完整 block 27 / `50.336M` | `3e-6`, `0/.99/.01` | 1 | `-0.000411` | `-0.010045` | `+0.000188 / -0.000428` | `0` | 极端 boundary-only 近似配方仍伤 within |
| O | block 27 内部变换/归一化九张量 / `33.559M` | `5e-6`, `.05/.25/.70` | 1 | `+0.003906` | `-0.003348` | `+0.000861 / +0.000139` | `+0.001401` | 任务内 promising；可靠性未确认 |

所有 A–O 的最终观测中，strict wins、report threshold 错误和 best operating balanced accuracy 都没有改善；K/O 之外的 raw boundary 都不为正，
raw within 没有一条为正。很多路线出现“raw margin 负、sigmoid projected margin 微正”，原因是高正 logit 区的非线性投影与共同下移，
不能把它当作排序改善。

#### 3.5.2 A–E：宽度、final norm、scheduler 与简单权重调整没有解决共同下移

A–E 横跨 2,048 到 100.676M 参数，有/无 final norm、有/无 weight decay、constant/warmup-decay、binary-heavy 与 pair-heavy 配方，
但五条路线的两类 raw pair margin 都下降，strict/threshold 指标不动。所有 pair-connected logits 只下降或不变。

这能排除“仅由 weight decay、scheduler、final norm 或 scope 宽度单独造成”的简单解释；scope 大小也不与质量单调相关。由于这些路线同时
改变多个变量且未保留逐 tensor/逐分量梯度与 train loss，不能进一步把失败归给某一个模块或 objective。

#### 3.5.3 F–K：输出投影、公共下移与 BF16 格点化

F 的完整末块在 step 1 曾出现很弱的 raw boundary 正信号，但 within 已退化；step 2 后 boundary 也反转。G/H/I 分别更新
`o_proj + down_proj`、`o_proj`、`down_proj`，两类 raw margin 一致退化。J/K 表明简单降低学习率或重新加权不能解决两类 pair 的 tradeoff。

F/G/I 分别有 55/55、47/55、46/55 个 logits 下移；H 有 39/55、J 有 23/55 个 row 完全不变。raw logit/pair delta 大量落在
`0.00390625 / 0.0078125 / 0.015625` 等离散格点。只能确认最终 BF16 scoring 的 outputs/deltas 呈格点化且有大量不变 row；没有
FP32 candidate scoring 或 master-weight/update 对照，无法区分 forward 输出量化、参数更新分辨率与真实小效应，更不能把 BF16 宣布为主因。

F 的完整 scope 可以按元素集合拆成 G 的两个残差输出投影与 O 的内部变换/归一化。被测 output-projection 配方 G/H/I 均为负向，
internal-only O 则成为搜索中最优路线，提示 module-specific sensitivity。它不是互补单变量消融：F 的表格终态是 step 2，O 只有 step 1，
G 与 O 的 objective 权重也不同，且 O 是看过前序 validation 后设计；因此不能把 F = G + O 当作效果可加关系，也不能确认输出投影抵消了 O。

#### 3.5.4 L–N：更宽 scope 和极端 pair 权重仍未解除 tradeoff

L 把末端范围扩大到四层、参数达 201.344M，同时把 LR 降到 `1e-6`，两类 raw margin 反而出现本任务最大级别回退。M/N 去掉 binary，
分别把 `99%` 权重给 within 或 boundary，也没有让对应目标在 validation 上改善。

实现是对三个 component 各自求均值再乘权重，不按原始样本数混合。以 Route O 为例，单个 binary/boundary/within 训练单元的近似权重分别为
`0.05/128`、`0.25/50`、`0.70/8`；单个 within pair 的梯度杠杆约是单条 binary 的 224 倍、单个 boundary 的 17.5 倍。这不是合同错误，
但意味着 8 个 within train pairs 会强烈决定一次更新，而验证要在另外 7 个 scenario-held-out pairs 上泛化。

因此，失败不能简化为“binary 一定压过 pair，所以去掉 binary 即可”，也不能简化为“scope 越宽越好”。M/N 只是否定两个极端配方，
不能证明整个 pair-only objective 家族无效；缺少每个分量的 train 改善和梯度余弦，无法区分 train/validation shift、pair-family 冲突和数值动态。

#### 3.5.5 Route O：为什么是 promising，又为什么还不可靠

Route O 更新末块 Q/K/V、Q/K norm、gate/up 与两处内部 norm 共九张量，排除 `o_proj/down_proj`。19 个 boundary pair 中 raw margin
7 改善、9 不变、3 变差；变化不是严格统一 offset。候选 checkpoint 已由另一 OS 进程做 no-update 精确恢复，资产可供后续任务复用。

但其可靠性边界非常明确：

- raw boundary 均值改善 `0.00390625`，pair-level 描述性标准误约 `0.00415`，大于均值；pair 还共享 candidate，独立性假设会过于乐观。
- AUC `+0.00140056` 恰好等于 `1 / (34 × 21)`，只相当于 714 个跨类比较中净改善一个 ordering。
- raw within-PASS 同时下降 `0.00334821`；strict wins、固定阈值错误和 best operating balanced accuracy 全部不变。
- 55 个 logits 中 42 个下降、13 个不变，平均约 `-0.01740`；虽有五种不同变化幅度而非纯 offset，公共下移仍很明显。
- Route O 是同一 validation 上连续观察并自适应设计的第 15 条路线，存在多重查看与 winner's curse。
- fresh-process no-update recovery 证明 checkpoint 完整，不证明从 exact base 再训练一次会重现改善；当前只有一个 seed、一次宏更新。

所以 `PROMISING_CANDIDATE_RETAINED` 是正确的 Plan 087 任务终态，而“Route O 有可靠提升”仍是未确认命题。

## 4. 跨路线根因分层

### 4.1 已确认的直接原因

1. **基础模型的任务判别力不足**：1.7B 与 4B base 的 AUC 都约 `0.62`，远低于 `0.80` 质量底线；完整 threshold 搜索不能修复排序不足。
2. **Plan 066 更新过后输出/排序塌缩**：raw-logit 跨度急剧收窄，AUC 与 boundary 明显低于 base。
3. **Plan 082 scope 的有效更新主要是公共 calibration 移动**：参数真实变化，但 55 个 logit 近乎等量下移，pair 结构几乎不变。
4. **Plan 087 A–N 没有形成双 pair-family 的 raw 净改善**：大多数路线公共下移，projected/ROC 微步没有落到 strict 或 threshold 改善。
5. **Route O 只有小型、经自适应选择的弱信号**：足以保留研究候选，不足以证明重复性或泛化。

### 4.2 最可能的深层机制

按当前证据强弱排序：

1. **优化强度与可表达 scope 之间没有稳定落入安全区间。** 全参数高 LR 能改排序但破坏性过强；head-only 只能移动已有表示的投影；
   中等末层 scope 的一步更新又常被公共方向和小型离散变化主导。这是跨 Plan 066/082/087 最一致的解释。
2. **末块模块对当前配方的响应可能不同。** G–I 的 output-projection 配方持续负向，O 的 internal-only scope 产生唯一保留信号；
   update 数、objective 与自适应选择均混杂，只能作为模块敏感性线索，不能确认两组职责相反或输出投影抵消 O。
3. **binary calibration 与 pair discrimination 的梯度存在公共方向/冲突。** Plan 082 的共同下移、Plan 087 多数路线的下降偏置与 base 的
   false-pass/high-logit 形态一致；M/N 失败又说明简单去掉 binary 或极端重权不能解决。缺乏逐分量梯度，所以只能列为高概率机制。
4. **数据覆盖不足与 train/validation shift。** 128/50/8 的 train 对数千万至 17 亿可训练参数很小，within-PASS 尤其只有 8 对；
   合成语料可能缺少发布质量语义的多样性。它能解释高方差和 family tradeoff，但当前没有 train metric/第二 cohort 证明。
5. **BF16 scoring/更新精度可能限制弱信号的可观测性。** 大量不变 row 与离散格点已确认，但 forward 量化、参数更新分辨率和真实效应尚未
   分离，只能保留为待 FP32 对照验证的解释。
6. **同一小 validation 的自适应选择偏差。** 这是 O 不可靠的确定性流程原因，不代表 O 一定是假阳性，但会使 observed best 高估真实效果。

### 4.3 不能确认的事项

- LR、clip、optimizer、scheduler、某个 objective 权重或某层是否是唯一根因。
- v8 train 是否已在各路线真正改善，因为多数终态没有保留逐分量 train loss、梯度方向与 update-to-weight 比例。
- 合成数据、base reward 预训练分布、prompt/template、模型容量中各自的贡献。
- Route O 能否在同 seed clean replay、第二 seed 或独立 cohort 上重现。
- 4B 经相同任务训练后是否优于 1.7B；现有 4B 证据只有 base。
- unseen 或真实发布流表现；它们始终没有进入本轮适配与选择。

### 4.4 已排除或缺乏支持的解释

- **基础设施/训练未执行**：真实参数变化、checkpoint、恢复和完整评分均有证据。
- **pair 方向或 objective sign 反了**：代码合同、数据 pair 语义与历史复核一致，没有支持证据。
- **只需换 threshold**：AUC 与 pair ordering 失败，完整 operating curve 也无合格点。
- **artifact 损坏或候选错绑**：正式身份、exact revision、恢复和结果投影已复核。
- **validation 进入梯度或 unseen 泄漏**：训练消费与回传 bundle 保持隔离，unseen 未读取。
- **LoRA/量化导致能力受限**：这些路线均是原参数更新，Plan 087 也未使用量化训练。
- **标签整体错误**：此前独立复核对 55 条 validation 的一致率为 53/55；这不证明数据足够，但不支持“全体标签颠倒/错误”。
- **模型越大自然越好**：exact 4B base 已直接否定这一简单假设。

## 5. 最有价值的后续确认方向

下一步应是独立立项、重新授权的 **Route O 干净正式复现**，而不是继续在同一 validation 上扩大搜索。建议只冻结必要事实，给执行者保留实现自由：

1. 复现前可先做低成本、无梯度对照：以相同 batch 对 exact base 与现有 Route O checkpoint 重复 BF16 scoring，并在可行时增加 FP32
   scoring；若优势随精度或重复执行消失，应优先判为数值分辨率/执行噪声。这个对照不替代从 base 重新训练。
2. 同时只读计算 base/Route O 的 train 与 validation 三类指标。若 train 明显改善而 validation 不稳，数据覆盖/泛化更可疑；若 train 也不改善，
   optimizer、scope、objective 或数值精度限制更可疑。
3. 在看新训练结果前冻结 exact model、v8 train/validation、Route O scope、seed/recipe、更新数、候选判据和停止边界，从 exact base 干净重跑。
4. 至少先回答“同 seed 同 recipe 能否重现方向和量级”；若不能，直接把 O 降级为搜索噪声，不进入 unseen/产品链。
5. 若同 seed 可重现，再以极少量第二 seed 或独立确认 cohort 判断稳定性；不要一开始建设大规模调参或统计平台。
6. 在现有训练 hooks 上补充高价值的轻量诊断：每个 objective 的 train loss 前后、pre-clip norm、逐分量梯度方向/余弦、各 scope
   changed-element fraction、update-to-weight ratio，以及公共 logit offset 与去均值后的 pair 变化。它们用于区分冲突、过冲和 BF16 格点，
   不需要新建审计/可信体系。
7. 如果仍无法区分“隐藏表示不足”和“当前优化方式无效”，可以冻结 base hidden states 做带正则、按 scenario 分组的轻量线性 probe；
   它只回答表示可分性，不应演变成第二套训练平台或用 validation 反复调参。
8. 只有复现信号明显且伴随指标不塌缩，才另行决定 unseen、M3-C1/M3-C2 或产品资格；Plan 087 的剩余预算不自动转移。

当前最应避免的是：继续在同一 55 条 validation 上试更多路线后挑最好者、因 projected margin 微增而忽略 raw/strict 指标、把 checkpoint
可恢复误写成效果可复现，或在未确认 O 前重新投入全参数/4B 大搜索。先用一次干净复现把最大不确定性压下来，信息价值最高。

## 6. 最终判断

- Plan 087：**验收通过、任务目标完成、`PROMISING_CANDIDATE_RETAINED`**。
- Publication Critic 研究：**存在值得复现的 Route O，但尚无效果可靠候选**。
- 直接失败层：历史全参数候选质量塌缩、4B base 判别不足、head-only 只改公共 offset、A–N 未形成稳定 raw pair 改善。
- 最可能根因：任务对齐不足与小数据背景下，优化强度、module-specific response、objective 梯度及可能的数值精度限制共同造成狭窄且不稳定的有效更新区间。
- 下一研究问题：预冻结 Route O 后能否从 exact base 干净重现；在它得到回答前，不解锁 unseen、M3-C1/M3-C2、产品启用或 M3-D。
