# Plan 075：Publication Critic `NO-GO` 原因调研与路线决策

日期：2026-08-25

本报告冻结 Plan 075 形成时点的证据与判断。当前阶段、后续工作包及授权状态只以
[`doc/WBS.md`](../WBS.md) 和
[`doc/WBS/multi-agent-trusted-evidence.md`](../WBS/multi-agent-trusted-evidence.md) 为准。

## 决策

选择任务合同阶段 D 的第 2 类结论：**现有证据足以决定返回训练质量形成环节，但不足以可靠指定一个单一根因；唯一建议的
下一工作包是“Plan 076：Publication Critic 训练动态与质量门有界诊断”。**

Plan 076 只回答一个问题：以 exact base 作为复现 Plan 066 问题的历史诊断 control，在冻结 v8 train+validation 和现有产品输入
语义不变的条件下，是否存在一条短程训练动态，能避免已观测到的输出/排序塌缩，并相对 pre-update control 保持或改善
validation 排序质量。exact base 不是对未来正式候选底模的选择；该任务不做正式训练、不生产候选，也不预选未来底模、优化器、
objective、学习率或数据扩展方案。

本任务不追加模型运行或诊断训练。原因不是证据已经证明了具体 recipe 缺陷，而是当前证据已经把下一步唯一收敛到“先取得受控的
训练动态和训练期质量门证据”：再跑同一正式训练、扩数据、换底模或重做 M3-C2 都缺少依据；而在 Plan 075 内临时增加任意一轮模型
实验，也不能在未冻结对照和停止条件时可靠区分这些路线。

Publication Critic 继续 default-off，M3-D 继续锁定；Plan 076 只是待授权建议，不在本任务中启动。

## 证据地图

| 链路 | 正式、可作为结论基础的事实 | 辅助事实 | 尚未测量或不能据此判断 |
|---|---|---|---|
| 产品与评价合同 | Plan 053 产品语义、v8 validation 身份、Plan 073 事前冻结质量底线和完整 operating-curve 搜索 | Plan 054 的 16 条工程基线 | 未来真实产品分布表现；unseen-test 表现 |
| 数据与监督 | v8 冻结 228 candidate、104 pair，train/validation/unseen-test 为 128/55/45；Plan 066 body-free bundle 只含 train+validation，validation 不进梯度 | 数据生成、独立 review、coverage/shortcut/consumer 测试；Opus 5 对 validation 55 条的盲评 | 128 条训练监督对 17 亿全参数模型是否充足；合成分布外泛化；全部语义噪声是否消除 |
| 训练 | Plan 066 exact base、C1→C2→C3、三次全参数更新、工件/恢复/梯度/有限值证据和固定 validation receipt | Plan 060 技术 smoke 与 FlashAdamW 数值资格 | 哪一个 recipe 因素造成退化；受控短程轨迹是否可以避免退化 |
| 本地资格 | Plan 071 exact base/C1/C3 同一 deployment 规则均 `QUALIFIED`，C2 保持 Plan 068 历史 `NOT_QUALIFIED` | Plan 068 CPU FP32 与 CUDA BF16 的 raw/ranking 分布 | 资格不测冻结标签质量，因此不能证明候选“判得对” |
| 联合横评 | Plan 073 正式 validation、三份完整 score、Judge package/aggregate、结果重算和最终 `NO_GO` | commissioning、Plan 054/068 的历史 cohort 与路径复核 | C2 的 Plan 073 同口径质量；任何新 recipe、模型或数据路线的质量 |

## 已确认事实

### 1. Plan 073 没有可接受选择的直接原因

唯一正式轮 `plan073-formal-20260825T084317Z-selection-v1` 在同一 55 条 validation（34 PASS、21 REWRITE）、19 个
boundary pair 和 7 个 within-PASS pair 上比较 exact base、C1、C3。冻结门限为 False PASS ≤`0.25`、False REWRITE
≤`0.35`、balanced accuracy ≥`0.75`、ROC AUC ≥`0.80`、boundary strict win ≥`0.70`、typed failure=`0`。

| 对象 | False PASS | False REWRITE | 最佳 balanced accuracy | ROC AUC | boundary strict win |
|---|---:|---:|---:|---:|---:|
| base | 6/21 = `0.286` | 13/34 = `0.382` | `0.666` | `0.6169` | 15/19 = `0.789` |
| C1 | 20/21 = `0.952` | 0/34 = `0.000` | `0.524` | `0.3894` | 5/19 = `0.263` |
| C3 | 5/21 = `0.238` | 18/34 = `0.529` | `0.616` | `0.5567` | 10/19 = `0.526` |

三者完整 operating curve 分别搜索 105、21、43 个点，没有可行点；最高 balanced accuracy 仍低于底线。因此失败不是
threshold 选取问题，也不存在可接受的 base fallback。`ranking=[]`、`selected=null`、`runner_up=null`，终态为
`NO_GO`，没有 selection lock。

三对象均完成 55 条打分、typed failure 为 0；load `2.85–3.16s`、warm p95 `219–222ms`、RSS 约 `4.30GB`、
VRAM `3.64GB`，运行门全部通过且彼此接近。部署、延迟、资源或不完整打分不是未选择的原因。

### 2. 训练技术成功不等于形成了质量合格候选

Plan 060 的目标是证明单卡 H100、BF16 全参数 FlashAdamW、保存/恢复与继续更新在技术上可行；其 `TECHNICAL_GO` 不要求
loss 或排序质量改善。Plan 066 按合同生产正式工件，但其 `GO` 同样只证明完整训练链与资产成立，质量选择明确留给下游。

Plan 066 沿用了 Plan 060 为数值资格确定的核心 recipe：固定 LR `4e-4`、constant scheduler、clip norm `1.0`，C1/C2/C3
各做一次 full-stage update。正式 receipt 显示三次 pre-clip gradient norm 为 `346`、`89.5`、`24.375`，均被裁剪；binary
mean loss 为 `1.431 → 10.359 → 7.438`。不参与梯度的同一 validation 在三个阶段的 zero-threshold correct 为
`21/55 → 34/55 → 21/55`，并出现大量 pair ties。

Plan 073 对同一工件哈希的正式结果进一步显示：base raw logit 跨度约 `9.56`，C1 约 `1.25`，C3 约 `0.30`；C1 的 AUC
低于随机，C3 也低于 base。这里能够确认的是**训练后的两个合格部署候选输出区分度和排序质量退化**，不能把其中任一
超参数、裁剪、单次更新、objective、optimizer 或数据规模单独宣布为根因。

### 3. 数据链和评价链没有已证实的 correctness 故障

v8 的内容摘要为 `a9a31a61…6cb98`，冻结 123 scenario、228 candidate、104 pair、178,646 tokens；train/validation/
unseen-test 分别为 128/55/45。Plan 066 正式导出摘要为 `5b887f60…51cf`，只含 128 条 train、55 条 validation 和对应
58/26 个 pair，unseen body file/row 均为 0。训练与 Plan 073 最终 validation 使用的是同一份物理无 unseen 的 canonical bundle。

现有 freeze、split/group、review、pair、consumer、token/shortcut 与完整性测试没有留下系统性 finding。训练 objective 中
PASS/REWRITE 符号、preferred/dispreferred 顺序和 runner 调用方向相互一致，且有方向回归与非零梯度证据；没有证据支持
“标签符号反了”或“pair 顺序反了”。候选哈希与正式工件一致，也没有 commissioning/formal 混用、权重未更新或工件损坏证据。

Claude Opus 5 对 validation 全部 55 条进行盲评，与冻结 GPT-5.6-sol 标签一致 53/55（`0.964`）；这足以反驳
“validation 标签整体失真”作为本轮失败的主要解释，但不能把合成数据当作普遍真值。v8 的 123 个 scenario 中 121 个是合成资产，
generator/reviewer 均来自同一模型家族；train+validation 的 multi-defect REWRITE、自然混合案例和 C3 within-PASS pair 数量有限。
这些是数据充分性与泛化风险，不是已验证的数据故障。

### 4. 部署资格只证明可复现，不证明判断正确

Plan 068/071 的 ranking、direction、drift、fresh worker 和 service parity 比较候选在不同 runtime/产品路径是否复现自身参考，
不与冻结 PASS/REWRITE 标签做质量门。Plan 071 使 exact base、C1、C3 取得同口径部署资格，合法进入 Plan 073；这与 Plan 073
判定三者质量不合格没有矛盾。Plan 068 的早期 24 条 cohort 已出现 C1/C2/C3 raw 范围收窄，只是该阶段按职责不能把它当作
发布质量失败。

### 5. 正式结果可复算，历史限制不改变结论

最终 Plan 073 路径从物理无 unseen 的 Plan 066 bundle 重建 validation release，并从 freeze、release、三份 raw score 与成对
Judge package/aggregate 重算结果；release、result、tracked JSON 的 SHA-256 分别为 `757dd624…71a91`、
`2b36eb4b…8915`、`f97fcdcc…8e4`，最终独立验收 60/60 通过。

原正式 score 未内嵌整个 snapshot 的 tokenizer/config 摘要，这是已知历史 provenance 限制。Plan 073 当时直接核验、Plan 075
再次静态复核的 `tokenizer.json`、`tokenizer_config.json`、`vocab.json`、`merges.txt`、`added_tokens.json`、
`chat_template.jinja`、`config.json` 七项在 base/C1/C3 间逐字节一致；`special_tokens_map.json` 只是同一
`<|vision_pad|>` 的字符串/对象等价序列化。正式日志还记录三对象 55 行 token count/omission 逐值一致。因此该限制不构成当前
路线 blocker，也不值得为此重跑重型模型。

历史上 Plan 073 的首版 reader 曾在过滤前解析 mixed v8，首版 lock 也可被自证式结果伪造；它们随后被整改为物理无 unseen 的
bundle 读取和基于正式输入重算的严格 lock。原 Judge package id 含 `validation` 明文，只泄露正式 split 名而不含答案，后续规则已
禁止且没有重问 Judge。这里记录历史边界，不把旧实现冒充最终路径，也不改写 Plan 073 指标或 `NO_GO`。

## 解释分级

### 有充分证据支持

1. **现有 exact base 对当前冻结 validation 本身能力不足。** 它的完整曲线最高 balanced accuracy `0.666`、AUC `0.6169`，
   因此“保留 base 并重选 threshold”不是可行路线。
2. **Plan 066 的技术资格 recipe 未经质量开发就用于正式候选生产，且训练期没有阻止质量退化的门。** 三次强裁剪单步更新、
   receipt 中的振荡/ties 与 Plan 073 的 logit/ranking 退化形成同一证据链。缺失质量门使技术有效但质量退化的 C1/C3 合法流入
   M3-C2；这不表示 Plan 060/066 的既有技术验收错误。
3. **继续同一正式 recipe 缺乏依据。** 现有候选没有显示出随阶段稳定改善的信号；直接再训练不能回答退化来自何处，也没有
   预先的停止门保护预算和候选质量。

### 已排除为本轮直接原因

- threshold 选取、base fallback、运行资源/延迟、typed failure 或打分缺失；
- Plan 071 部署不可达或 service 路径不一致；
- obvious objective sign / pair direction 实现错误；
- 正式候选工件身份错配、未更新、损坏或 commissioning/formal 混用；
- validation 标签整体崩坏或 Judge 缺失；
- 已发现的数据 split、consumer、shared-input identity 或 label-text shortcut correctness 故障；shared-input identity 的结论仍受
  上述旧 score 未内嵌完整 snapshot 摘要这一历史 provenance 限制。

“已排除”只针对能够直接解释这次正式结果的现有假说，不外推为数据、模型或训练设施永久无风险。

### 仍无法判断

- LR、optimizer、clip、一次 full-stage update、objective 组合、stage 权重、scheduler 中哪一项或哪组是主要机制；
- 训练样本规模、合成监督分布、少量复杂案例与模型容量各自贡献多大；
- C2 若按 Plan 073 协议评价会取得什么指标；Plan 066 receipt 的饱和/ties 只是辅助证据；
- 是否需要换底模、改数据或改 objective；在训练动态未被有界测量前，没有一条有证据优势；
- unseen-test 和未来真实 RONDO 发布流的表现。Plan 075 未读取 unseen-test 正文、逐行 label 或 pair 方向，未 render、score、
  Judge 或释放其内容；只核对过冻结 split 的 assignment/聚合 metadata。

这些未知阻止“单一根因”结论，却不阻止下一路线决策：所有候选生产方案都应先通过短程、受控、逐更新的质量诊断。

## 后续交接

唯一建议为 Plan 076：先用受控短程轨迹判断能否避免 Plan 066 已观测到的训练质量退化，并形成训练期质量停止门；其结果不能
冒充正式候选、资格或联合选择证据。具体目标边界、数值资源上限、终态和授权状态只写入
[`doc/WBS.md`](../WBS.md) 与
[`doc/WBS/multi-agent-trusted-evidence.md`](../WBS/multi-agent-trusted-evidence.md)，本冻结报告不复制下游规划。

## Plan 075 执行边界

本调研只做静态读取、摘要/指标复算和普通 Python 定向测试；未加载模型、未运行 GPU、Docker、Cargo、真实 API、HF 网络操作或
云资源，未改训练数据、模型、Plan 073 结果、产品代码或并行 worktree。没有创建补测 namespace，也没有实施 Plan 076。
