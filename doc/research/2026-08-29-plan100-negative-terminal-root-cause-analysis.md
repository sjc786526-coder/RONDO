# Plan 100 负向终态的再归因：`TASK_EXECUTABILITY_INSUFFICIENT` 究竟测到了什么

日期：2026-08-29
性质：形成时点冻结的研究分析，不是当前规划。当前阶段、后续工作包与授权状态只以
[`doc/WBS.md`](../WBS.md) 和
[`doc/WBS/multi-agent-trusted-evidence.md`](../WBS/multi-agent-trusted-evidence.md) 为准。

本报告承接
[`2026-08-27 模型侧失败归因`](2026-08-27-publication-critic-model-side-failure-analysis.md)
与
[`2026-08-26 模型路线结果与根因分析`](2026-08-26-publication-critic-training-route-outcome-analysis.md)。
两份旧报告保留其形成时点的判断，不改写；本报告加入 Plan 100 的 81 条正式 observation 逐条复算，重新评估“负向结论说明了什么”。

## 1. 结论摘要

Plan 100 的执行是干净有效的：81/81 observation 完整、三臂 parse failure 全为 0、费用按 provider usage 逐条结算、独立复算通过。
`TASK_EXECUTABILITY_INSUFFICIENT` 按预冻结规则正确形成，**作为“本次冻结配置未跨过预冻结门”的记录是准确的**。

但把它读成“任务本身不可执行”会明显超出证据。对原始逐条输出复算后，本报告的判断是：

1. **A 臂的结果几乎完全是 prompt 示例锚定的产物，不是标量表达能力的测量。** 27 个候选中有 20 个原样返回了
   output contract 里的示例值 `0.42`，整条曲线只有 `{0.0, 0.42, 0.85}` 三个取值。
   180 个跨类比较中 `105` 个（`58.3%`）是精确并列；在能分辨的 75 个比较里，A 是 `65 胜 / 10 负`（`0.867`）。
   也就是说：**A 一旦真的动，排序是对的；问题是它 27 次里只动了 7 次。** 用这条曲线得出的
   “AUC `0.6528`、无可接受 operating point、Boundary strict `2/9`”，测的是输出退化，不是标量表达。
   C 臂同样有 `13/27` 输出与示例 JSON 逐字节相同。
2. **准入门不具备跨设定可比性。** 门槛整体来自 Plan 099 的**训练**开发门
   （[`development-gate-v1.json`](../../training/publication-critic-plan099/development-gate-v1.json)），
   而训练路径被允许在同一 validation 上从 12 个 decision config 中挑选阈值；Plan 100 的 B/C 直接输出硬标签，没有任何等价调节自由度。
   逐维 failure recall 门又落在 `3–6` 条支持度上：一个逐维检出率 `0.8`、零误报的理想裁判，
   仍有 `56%` 概率过不了五维合取门（`q=0.9` 时才 `0.82`）。
3. **`n=27` 下这些门根本不可分辨。** C 的 balanced accuracy `0.700`，Wilson 区间约 `[0.478, 0.821]`，
   而门槛是 `0.75`——门槛落在噪声区内。本次实验没有能力区分“未达门”与“达门”。
4. **关闭 thinking 不是测量错误，而是结论适用范围的限制；但它的理由不成立。**
   本地 Skywork 1.7B scorer 与 Plan 099 五头模型本来就是“一次 backbone forward”，没有任何推理步骤，
   所以关闭 thinking 恰恰贴近部署目标，不能称为不公平（详见 §3.1）。
   真正的问题有两个：其一，它使“任务本身难判”与“任务在一次前向内难判”无法区分，而终态的名字 claim 的是前者；
   其二，**关闭的理由本身站不住**——思考 token 计入 completion usage、账单精确可结算，
   真正卡住的是一条从未启用的兜底复算自检门（详见 §3.2）。
5. **标签有一小部分确实不由 rubric 唯一决定，但这是局部问题，不是整体问题。** C 的 9 个漏检里，约 6 个标签扎实、模型确实判错；
   约 3 个（`hb-03-qminus`、`soft-020-hard-fail` 的 `scope_and_signal=FAIL`，`019-qminus` 的 `conditional_continuity=FAIL`）
   依赖生成侧约定而非模型可见 rubric 文本。
6. **被终态掩盖的是一个正向信息：五维分解是三臂中最好的一臂。** C 的 candidate balanced accuracy 最高（`0.700`）、
   PASS recall `12/12`、false REWRITE `0/12`、continuity 适用性判断 `12/12` 全对、3 个 soft-invariance pair 全部保持不变；
   B 在同样的 packet 上有 `6/12` false REWRITE 且翻掉了 soft pair。
   路线映射把这条信息丢弃了：`FIVE_DIMENSION_STRONGLY_SUPPORTED` 要求 C 先跨过绝对门，
   而 `TASK_EXECUTABILITY_INSUFFICIENT` 在“三臂绝对门全不过”时吸收一切，
   于是**任务书写明的首要问题（三种表达哪种更支持任务）实际有答案（C），却没有出口被报告出来。**
7. **模型确实存在真实能力缺口，但它比终态名称暗示的小，而且形态是可定位的。** B 的 6 个 false REWRITE 有 5 个集中在
   soft-combinations 家族，该家族每条候选都含“先前发布文本不可用”，而 rubric 明确写了
   “Treat stale, partial, unavailable, and omitted context as visible limits, not proof for or against the candidate”——
   B 把“上下文不可用”本身当成缺陷。这是一个**单一、可解释、可通过 prompt 处理的行为偏差**，不是弥散性的无能力。
   B∪C 共捕获 `12/15` 个真实缺陷，只有 3 个两臂都没抓到；**判别所需信息在 packet 里对至少 12/15 是存在的。**
8. **预算与停机规则共同封死了本可以澄清以上问题的空间。** task-wide 实际消费 `0.0396094 RMB`，
   占 20 RMB 授权额度的 `0.198%`；“首个完整有效 formal 后立即停止 API”这条防挑结果的规则，
   同时也排除了任何重复采样、方差估计或开启 thinking 的对照。

按贡献强度排序是：**示例锚定 > 门槛不可比且不可分辨 > 五维语义重叠导致的归属错误 > 局部标签不一致 > 真实模型能力缺口**；
“关闭 thinking”不进入这个排序，它决定的是结论能覆盖多大范围，不是结论本身对不对。

一句话概括：**Plan 100 得到的不是“这个任务做不了”，而是“在零示范、单次采样、示例值被原样抄回、
并用一套为可调阈值的训练路径设计的门去卡的条件下，一次前向级别的三种输出表达都没跨门；
其中五维分解表现最好，标量臂的结果基本是示例锚定的伪影”。**
旧报告 [`2026-08-27`](2026-08-27-publication-critic-model-side-failure-analysis.md) §6.1 提出的核心疑问——
“任务语义究竟能不能被表达和判别”——**Plan 100 并没有关闭它。**

## 2. 结论口径与证据范围

本报告严格区分四类命题：

- **执行有效性**：Plan 100 的 provider 调用、解析、归档、费用与复算是否真实有效。
- **测量对象**：本次实验实际把什么变量固定、把什么变量置于被测位置。
- **终态正确性**：给定预冻结规则和实测数字，`TASK_EXECUTABILITY_INSUFFICIENT` 是否被正确推出。
- **终态的解释范围**：这个终态可以支持什么样的下游判断。

前三项本报告全部认可为**正向**；本报告的全部异议只在第四项。

### 读取与动作边界

本报告只做只读分析，**没有**调用任何 API、没有加载或推理真实模型、没有训练、没有构建、没有 GPU/Docker/RunPod、没有上传、没有产生费用。

已读取：

- 受跟踪结果与合同：[`plan100-structured-diagnostic-v1.json/.md`](../../eval/results/publication-critic/)、
  [`plan100-diagnostic-contract-v1.json`](../../eval/templates/publication-critic/plan100-diagnostic-contract-v1.json)、
  [`development-gate-v1.json`](../../training/publication-critic-plan099/development-gate-v1.json)。
- 模型可见 prompt 的唯一来源：[`cloud_diagnostic.rs`](../../multidev/codex-rs/publication-critic/src/cloud_diagnostic.rs)；
  thinking 开关落点 `cloud_scorer.rs:358`；离线复算实现
  [`token_recounter.py`](../../eval/rondo_eval/publication_critic/structured_diagnostic/token_recounter.py)。
- 部署侧对照事实：[Plan 099 ExecPlan](../../plan/099-publication-critic-five-head-training-and-candidate-freeze-execplan.md)
  §3.5 与决策 010（一次 backbone forward / 五个 head），以及 [`2026-08-27` 报告](2026-08-27-publication-critic-model-side-failure-analysis.md) §6.5（last-token 单标量读取）。
- v10 **development validation** 全部 27 candidates / 12 pairs 正文与标签（Plan 100 本身即合法消费该集合）。
- 主物理根 ignored 证据 `eval-data/publication-critic/plan100/`：formal run 的 81 条 receipt 与 81 条 terminal（含 exact response text 与 usage），
  以及 Plan 099 的 `evidence/log-tail.txt`、`formal-result.json`。

**没有**读取 `publication-critic-qualification-v1` 正文、v9 test 正文或任何其它冻结 unseen 资产。

### 两条必须声明的限制

1. **本报告对标签的复核不是盲评。** 我在判断前已经看到冻结标签，因此不能报告一个有意义的“独立一致率”。
   §5.3 给出的是**逐条可复核的论证**（引用 packet 原文与 rubric 原文），读者可以自行否决其中任何一条；
   它回答的是“该标签能否由模型可见的 rubric 唯一推出”，不是“我和标签有多一致”。
2. **本报告本身又一次完整看过了 v10 validation。** 该集合此前已被 Plan 098/099/100 反复使用，本次分析进一步加深了它的开发集属性。
   任何未来在该集合上观察到的改善，都必须按“已被多次查看的开发集”折价，不能当作独立泛化证据。

## 3. Plan 100 实际把什么放在了被测位置

任务书的目标是把差异压到“输出任务表达”这一个变量上。合同层面做到了：同一 provider、同一 requested model、同一 packet 字节、
同一 rubric 正文、同一 temperature/timeout/retry、同一数据顺序，唯一 provider-visible 差异是输出指令与 schema。这一点在
`comparison/provider_visible_difference = output_instruction_and_exact_output_schema_only` 有合同记录，逐条 receipt 的 packet hash 也可复核。

但**被固定下来的那些共同条件本身，构成了一个远比“输出表达”更强的约束**：

| 共同冻结条件 | 合同/实测依据 | 对被测能力的影响 |
|---|---|---|
| thinking 全臂关闭 | 合同 `comparison/thinking`；实测 completion token A=7、B=7–8、C=39–44 | 判断过程可用 token 为 0；**贴近部署目标，见 §3.1** |
| zero-shot，无任何示范样本 | `cloud_diagnostic.rs` system message 仅含 rubric + 输出契约 | 无 rubric 语义校准锚 |
| 禁止输出解释/理由 | 三个 output contract 均写 `Emit no ... explanation` | 无法把中间判断外化 |
| `temperature = 0`、`max_attempts = 2`、单次逻辑调用 | descriptor lock | 无方差估计、无自洽性投票 |
| 输出契约含具体示例值 | `{"quality":0.42}` / `{"...":"N/A",...}` | 见 §4.1，实测强锚定 |
| 首个有效 formal 即停 API | `formal/first_complete_valid_formal_stops_new_api_consumption` | 无重复、无消融、无对照 |

### 3.1 关闭 thinking 本身不构成不公平

必须先把一个容易搞混的点讲清楚：**部署目标本来就没有“思考”这一步。**

- 本地 Skywork 1.7B scorer 是从完整渲染输入的 last non-pad token 读出一个标量
  （见 [`2026-08-27` 报告](2026-08-27-publication-critic-model-side-failure-analysis.md) §6.5）。
- Plan 099 的主方案是“一次 backbone forward 只产生 task v2 的五个资格 heads”
  （[Plan 099 ExecPlan](../../plan/099-publication-critic-five-head-training-and-candidate-freeze-execplan.md) §3.5、决策 010）。

两者都是**零推理步骤的单次前向**。因此关闭 thinking 使 DeepSeek 更接近、而不是更远离部署目标，
**不能把它算作对被测对象的额外镣铐**，本报告不把它列入根因排序。

但它确实带来一个结论范围问题：**在一次前向条件下的失败，无法区分“任务本身难判”和“任务在一次前向内难判”**，
而 `TASK_EXECUTABILITY_INSUFFICIENT` 这个名字 claim 的是前者。

而且 Plan 100 自己的数据就显示出一条与“顺序计算量”相关的梯度：

| 对象 | 输出形式 | 实测输出长度 | 结果 |
|---|---|---:|---|
| 本地 1.7B / Plan 099 五头 | 一次前向读出标量 / 五个 head | `0` token | 五个评价点全部 `decision_config_unavailable` |
| Plan 100 **A** | 一个数字 | `7` | 退化（示例锚定），无有效测量 |
| Plan 100 **B** | 一个标签 | `7–8` | balanced accuracy `0.583` |
| Plan 100 **C** | 五个标签依次生成 | `39–44` | balanced accuracy `0.700` |

C 的 43 个 token 意味着五个判断是**依次生成、后者可见前者**，已经是一点点结构化的顺序计算。
A 在结构上最接近本地 scorer，也最退化。这条梯度不构成严格因果证据（A 的退化另有示例锚定的原因），
但它与“该任务对可用顺序计算量敏感”相容，也正是路线映射无处安放的那类信息。

### 3.2 关闭 thinking 的**理由**不成立：账单算得清，卡住的是一条从未启用的兜底自检

Plan 100 决策记录 011 与阶段 B 日志给出的理由是“V4 默认 thinking 会忽略冻结 temperature，
且 reasoning token 无法从最终 JSON 独立复算，影响费用复算”。逐条核对后，这三项都不构成硬阻塞：

**1）费用本身完全算得清。** 阶段 B 日志自己写着 V4“把独立 reasoning 计入 completion usage”——
provider 照常在 `usage` 里报出来，按 usage 结算是精确的。**账单口径与开不开思考无关。**

**2）真正的阻塞来自一条兜底路径的自检门。** 完整因果链是：

- 硬约束 §3.5 规定：响应缺少 `usage` 时**不许**直接按 `0.1 RMB` 兜底，必须用官方 tokenizer 自行分类计数；
- 要让这个自算方法可信，合同 `commissioning/usage_recount_calibration` 要求 B1 的
  `all_usage_present_success_attempts_exact_prompt_and_completion_match`——离线复算的 **prompt 与 completion 都必须与 provider 精确相等**；
- 而离线复算 completion 的实现方式，是把归档的 `response_text` 拿去 tokenize
  （[`token_recounter.py`](../../eval/rondo_eval/publication_critic/structured_diagnostic/token_recounter.py)）；
- 一旦开启 thinking，计费 completion = reasoning + 最终 JSON，而 **reasoning 内容不在 `response_text` 里**，
  离线复算必然系统性偏短 → “completion 精确相等”永远不可能满足 → B1 binding 永远无法生成 → **B2 正式轮根本无法开始**。

所以准确表述不是“费用算不清”，而是：**为了让一条备用计费算法通过自检，被测模型的输出里不能含有任何离线数不到的 token。**

**3）而这条备用路径一次都没有被使用。** 冻结账本记录：

```
settlement_methods:          {provider_usage: 99}
recounted_prompt_tokens:     0
recounted_completion_tokens: 0
```

99 次调用**全部**按 provider usage 结算，离线复算实际贡献的 token 数为 `0`。

**4）另外两条理由同样不硬。** temperature 被忽略这一点对三臂是**共同**的，被测变量（输出表达）仍然隔离，
真正受损的是单次采样的确定性——而这本应由重复采样解决，当时预算尚余 `99.8%`。
“严格短 JSON 合同”也不受影响：reasoning 走独立响应字段，`content` 仍是纯 JSON，严格解析器无需改动。

**这一段的意义超出 Plan 100 本身。** 起点是一条正当的预算安全条款（别让缺 usage 的响应悄悄超支），
经独立审查加固后变成一道“离线复算必须逐 token 精确相等”的准入门，最终**由这道门反过来决定了实验条件**。
20 RMB 授权、3.9 分钱实际支出，为一条从未启用的对账路径的精度，换掉了被测模型的工作方式。
这正是根 `CLAUDE.md` §7 所警示的形态：验证/审计机制自我膨胀并吞掉实验本身。
关闭作用域本身是干净的——`cloud_scorer.rs:358` 仅对 `ResponseProjection::Diagnostic` 生效，产品 scorer 未受影响。

## 4. 逐层归因

### 4.1 最高可信：输出退化与示例锚定，A 臂结果基本无效

27 个 A 臂 formal observation 的标量取值分布：

| 取值 | 次数 | 说明 |
|---:|---:|---|
| `0.42` | 20 | 与 output contract 示例 `{"quality":0.42}` 逐字节相同 |
| `0.0` | 6 | 其中 5 个是真实 REWRITE |
| `0.85` | 1 | 是真实 PASS（`hb-03-qplus`） |

由此直接推出三件事：

1. **operating curve 只有 4 个点**，结果文档记载的“A 的完整四点曲线”不是简洁，而是分辨率崩塌。
2. **9 个 boundary pair 中 7 个是精确并列**（两侧都是 `0.42`）。而 A 的 boundary 门要求
   `required_boundary_strict_wins = 9`，即 `9/9` 全胜。**在模型锚定到示例值的那一刻，A 的 boundary 门在算术上已不可达。**
   实测 `2/9` 不含任何关于标量表达的信息。
3. **AUC `0.6528` 被并列稀释。** 180 个跨类比较中：strict win `65`、tie `105`、loss `10`。
   并列按 0.5 计入贡献了 `52.5`。**只看能分辨的 75 个比较，A 是 `65:10`，即 `0.867`。**

第 3 点是本报告最反直觉、也最重要的一个数字。它说明：**当标量真的给出不同取值时，它的排序方向是对的**；
把 A 判为“标量表达不足以承载该任务”的证据并不成立，实际观察到的是“模型在没有推理预算时倾向于复述示例值”。

C 臂有同类迹象：`13/27` 的 `response_text` 与 output contract 里的示例 JSON **逐字节相同**（含键序与无空格排布），
`21/27` 落在两种全 PASS 形态上；gold continuity 为 `FAIL` 的 3 条里有 2 条被判成示例里的 `N/A`。
A 臂的 `{"quality":0.42}` 同样是与示例逐字节相同的响应。

**这是一个 prompt 工程缺陷**（在严格输出契约里给出一个具体可信的示例值，同时不给推理预算），
不是被测假设的性质。任何后续测量都应改用占位符、多示例或不含合法取值的格式说明。

### 4.2 高可信：准入门不具备跨设定可比性，且在 n=27 上不可分辨

**门的来源问题。** Plan 100 的门整体投影自 Plan 099 的训练开发门，投影方式是
`inference_only_without_decision_config_training_loss_or_step_zero_selection`，
即删去 decision config 选择、training loss 与 step-zero 改善这三项训练专属**条件**，
但**数值阈值原样保留**。而这些阈值当初正是在“训练路径可以在同一 validation 上从
`bounded_validation_pair_closed_grid_v1` 的 12 个 decision config 里挑一个”的前提下标定的——
即模型输出 head logits，阈值另行选择。Plan 100 的 B/C 直接输出硬标签，**没有任何等价的阈值自由度**；
A 名义上有阈值曲线，但因 §4.1 只剩 4 个点。
这不是“同一把尺子量两个对象”，而是把一把为可调系统标定的尺子，用在了不可调的系统上。

**门的统计功率问题。** 逐维 failure recall 门与各维实际支持度：

| 维度 | 门槛 | gold FAIL 支持度 | 需命中 | 实测 |
|---|---:|---:|---:|---:|
| useful_state_transfer | `2/3` | 6 | 4 | 2 |
| honest_uncertainty | `0.8` | 5 | 4 | 2 |
| conditional_continuity | `2/3` | 3 | 2 | 0 |
| scope_and_signal | `2/3` | 6 | 4 | 1 |
| internal_consistency | `0.75` | 4 | 3 | 2 |

假设一个**零误报**、逐维检出率为 `q` 的理想裁判，五维门同时通过的概率为：

| `q` | 0.70 | 0.80 | 0.90 | 0.95 |
|---|---:|---:|---:|---:|
| 五维合取通过概率 | `0.150` | `0.439` | `0.820` | `0.952` |

也就是说，这套门实际要求 `q ≳ 0.9`，且这还没算上 candidate gate（false PASS `≤3/15`）与
“12 个 pair 全闭合”两个额外合取条件。对一个主观编辑性 rubric、支持度只有 3–6 条的判断任务，这是接近天花板的要求。

**候选级门同样不可分辨。** 27 条样本（12 PASS / 15 REWRITE）下的 Wilson 区间：

| 臂 | balanced accuracy | 约 95% 区间 | 门槛 |
|---|---:|---|---:|
| A | `0.625` | `[0.399, 0.784]` | `0.75` |
| B | `0.583` | `[0.335, 0.797]` | `0.75` |
| C | `0.700` | `[0.478, 0.821]` | `0.75` |

三个区间都包含 `0.75`。**本次实验在设计上就没有能力区分“未达门”和“达门”**，
无论结果正负，都只能得到一个不可分辨的观测。这一点与结果本身无关，属于冻结阶段就已确定的性质。

### 4.3 中等可信：五维之间语义重叠，归属错误与漏检被同等惩罚

C 正确判为 REWRITE 的 6 条里，只有 2 条的五维标签集合完全正确。维度层面统计：24 个 gold FAIL 中漏检 17 个，
同时在非 FAIL 位置误报 8 个。典型形态：

- `hb-01-qminus`（"Done: the command-alias deprecation is complete."）
  gold 只有 `useful_state_transfer=FAIL`，C 判 `useful/honest/scope/internal` 四项全 FAIL。
  **整体 gate 判对，四维中三维误报。**
- `hb-02-qminus` gold `honest_uncertainty=FAIL`，C 判 `conditional_continuity=FAIL`。
  **整体 gate 判对，两个维度全错——检出了缺陷但归错了抽屉。**
- `hb-02-multi` gold `PFPPF`，C 判 `FFFFF`。同样是检出后铺开。

这意味着逐维 recall 门混合了两种性质完全不同的失败：**没看见缺陷**，和**看见了但归到相邻维度**。
在 3–6 条支持度上，后者足以单独打掉一个维度门。当前指标口径无法把两者分开报告。

### 4.4 中等可信：部分标签不由模型可见 rubric 唯一决定

模型可见的 rubric（`cloud_diagnostic.rs:16-30`）对 `scope_and_signal` 的 FAIL 定义是
“process dumps, repetition, or off-scope material overwhelms that state”。据此复核：

- `hb-03-qminus`：正文是 "Download resume is not closed. It keeps the offset with the tag unless that changes,
  then this resets before the other check." gold 标 `scope_and_signal=FAIL`。
  这段文字既短、又完全在 scope 内，**没有 dump、没有重复、没有 off-scope**；它的问题是指代含混。
  按模型可见 rubric，这更像 `useful_state_transfer=FAIL`。**标签与 rubric 文本不一致。**
- `soft-020-hard-fail`：与同组 base 的差别是把三件事压进一句并用 "it" 指代。gold 标 `scope_and_signal=FAIL`。
  这是**压缩**，正好是 rubric 所述“overwhelms”的反面。**同类不一致。**
- `019-qminus`：正文明确说 "Remote-store checksum verification remains unfinished; no integration work is recorded."，
  gold 标 `conditional_continuity=FAIL`。rubric 说 “PASS when unfinished work gives usable progress, blockage,
  or the next starting point”——该候选确实陈述了阻塞状态。**属于真实边界模糊，两种读法都站得住。**

作为对照，另外 6 个漏检的标签是扎实的、模型确实判错了，其中最清楚的是
`continuity-context-020-multi`：正文同时含
"looked sound during a whiteboard walkthrough, so operators can rely on it" 与
"No rehearsal outcome was retained, and drain behavior remains unresolved"，
gold 标 `useful/honest/continuity/internal` 四项 FAIL；C 判全 PASS 且 continuity 判 `N/A`。
这是一个白板推演被当作可依赖结论、同时与“未解决”自相矛盾的教科书式案例，
**任何有推理预算的判断都不该漏**——它同时也是 §4.1 结论的最强佐证。

因此本报告的判断是：**标签问题是局部的（约 3/9），不足以解释整体负向；它的意义在于说明逐维门的分母本就不干净，
而不在于把负向结果归因给数据。**

### 4.5 真实存在但被高估的模型能力缺口

扣除 §4.1–4.4 后仍剩下真实缺口，但它的形态是可定位的：

**B 的误报高度集中。** B 的 6 个 false REWRITE 有 5 个落在 soft-combinations 家族。该家族 9 条候选每条都含
“先前发布文本不可用”，B 对其中 8 条判 REWRITE，而 gold 只有 2 条。rubric 明确要求
“Treat stale, partial, unavailable, and omitted context as visible limits, not proof for or against the candidate”。
**B 把“上下文不可用”当成了候选自身的缺陷**，这是一条可命名、可通过指令或示范修正的偏差，
不是“无法判别发布质量”。

**信息在 packet 中是存在的。** 15 个真实 REWRITE 中：B 抓到 10 个，C 抓到 6 个，**B∪C 抓到 12 个**，
只有 3 个（`021-qminus`、`hb-01-multi`、`hb-03-multi`）两臂都没抓到。
同一个模型、同一份 packet、同一份 rubric，只是换了输出表达，就能覆盖 `12/15`——
这直接反驳“packet 证据不足以支撑判别”，同时说明单次无推理采样的**不稳定性**才是主要损失来源。

## 5. 被终态吞掉的正向信息

### 5.1 五维分解在三臂中最好，但没有出口

| 比较轴 | A | B | **C** |
|---|---:|---:|---:|
| candidate balanced accuracy | `0.625` | `0.583` | **`0.700`** |
| PASS recall | `0.917` | `0.500` | **`1.000`** |
| false REWRITE | `1/12` | `6/12` | **`0/12`** |
| pair 闭合 | Boundary `2/9` | `4/12` | **`5/12`** |
| soft-invariance 保持 | 3/3 并列（无信息） | 2/3（其中 1 个翻转） | **3/3 保持且判断正确** |
| continuity 适用性（N/A） | — | — | **`12/12`** |

C 在几乎所有轴上最好，且是唯一一个**从不误伤合格候选**的表达。continuity 适用性 `12/12` 尤其值得注意：
“只有当候选清楚一致地声明工作已完成时才是 N/A”这条规则，模型完全学会了并零错误执行——
这恰恰说明**结构化分解把一部分判断变成了模型能可靠执行的形式**。

路线映射无法报告这一点。`route/priority` 的顺序是：
`FIVE_DIMENSION_STRONGLY_SUPPORTED` 要求 `C_meets_gate AND C 明显优于 B`；
`CONSTRAINT_OR_DATA_ISSUE` 要求 `C_dimensions_generally_good`；
`TASK_EXECUTABILITY_INSUFFICIENT` 只要 `A_B_C_all_fail_arm_basic_gate` 就吸收。
**三条正向/中性路线全部以绝对门为前置，于是绝对门一旦全灭，相对比较信息无处可去。**
任务书 §1 写明的首要问题是“主要问题更支持归因于单标量、直接判定、五维分解，还是任务/数据约束本身”——
这是一个**比较**问题，本次数据对它有答案（C），而终态只报告了**绝对**问题的答案。

### 5.2 终态名称与其证据范围不匹配

`TASK_EXECUTABILITY_INSUFFICIENT` 在合同中的定义是中性的（“A/B/C 均未达到预冻结基本要求”），
但它的**名字**把一个关于“本次冻结测量配置”的观测，命名为关于“任务”的属性，
并在 §3.9 附带了“默认不建议继续付费解冻训练”的路线后果。
考虑到 §4.1（A 臂结果是伪影）、§4.2（门不可比且不可分辨）、§4.5（B∪C 覆盖 12/15），
**这个名字承载的推断强度超过了它的证据。**

### 5.3 预算与停机规则的副作用

task-wide 实际消费 `0.0396094 RMB`，占授权 20 RMB 的 `0.198%`；剩余 `19.96 RMB` 未使用。
“首个完整有效 formal 后立即停止新增 API 消费”这条规则的设计意图是防止挑结果，这个意图是对的；
但它同时排除了：重复采样的方差估计、开启 thinking 的对照臂、修正示例锚定后的重测、
以及任何 few-shot 校准消融。**在授权额度用掉 0.2% 的情况下形成路线终态，是本次设计中信息效率最低的一处。**
更精确地说：防挑结果需要的是“预冻结判据 + 全部轮次都记账并报告”，而不是“只允许一轮”。

## 6. 逐条证据表（27 candidate × 3 臂）

维度顺序 `UST HU CC SS IC`；`P`=PASS，`F`=FAIL，`-`=N/A。

| candidate | C 预测 | gold | C gate | B | A | 真值 |
|---|---|---|---|---|---:|---|
| continuity-context-019-multi | `FPPFF` | `FPFFP` | REWRITE | REWRITE | 0.0 | REWRITE |
| continuity-context-019-qminus | `PP-PP` | `PPFPP` | PASS ✗ | REWRITE | 0.42 | REWRITE |
| continuity-context-019-qplus | `PPPPP` | `PPPPP` | PASS | PASS | 0.42 | PASS |
| continuity-context-020-multi | `PP-PP` | `FFFPF` | PASS ✗ | REWRITE | 0.0 | REWRITE |
| continuity-context-020-qminus | `PPPPF` | `PPPPF` | REWRITE | REWRITE | 0.42 | REWRITE |
| continuity-context-020-qplus | `PPPPP` | `PPPPP` | PASS | PASS | 0.42 | PASS |
| continuity-context-021-multi | `PP-PP` | `FP-FP` | PASS ✗ | REWRITE | 0.42 | REWRITE |
| continuity-context-021-qminus | `PP-PP` | `FP-PP` | PASS ✗ | PASS ✗ | 0.0 | REWRITE |
| continuity-context-021-qplus | `PP-PP` | `PP-PP` | PASS | PASS | 0.42 | PASS |
| hard-boundaries-01-multi | `PP-PP` | `FP-FP` | PASS ✗ | PASS ✗ | 0.42 | REWRITE |
| hard-boundaries-01-qminus | `FF-FF` | `FP-PP` | REWRITE | PASS ✗ | 0.0 | REWRITE |
| hard-boundaries-01-qplus | `PP-PP` | `PP-PP` | PASS | PASS | 0.0 | PASS |
| hard-boundaries-02-multi | `FFFFF` | `PFPPF` | REWRITE | REWRITE | 0.0 | REWRITE |
| hard-boundaries-02-qminus | `PPFPP` | `PFPPP` | REWRITE | PASS ✗ | 0.42 | REWRITE |
| hard-boundaries-02-qplus | `PPPPP` | `PPPPP` | PASS | REWRITE ✗ | 0.42 | PASS |
| hard-boundaries-03-multi | `PP-PP` | `PFPFP` | PASS ✗ | PASS ✗ | 0.42 | REWRITE |
| hard-boundaries-03-qminus | `PPPPP` | `PPPFP` | PASS ✗ | REWRITE | 0.42 | REWRITE |
| hard-boundaries-03-qplus | `PPPPP` | `PPPPP` | PASS | PASS | 0.85 | PASS |
| soft-combinations-019-base | `PP-PP` | `PP-PP` | PASS | REWRITE ✗ | 0.42 | PASS |
| soft-combinations-019-hard-fail | `PF-PP` | `PF-PP` | REWRITE | REWRITE | 0.42 | REWRITE |
| soft-combinations-019-soft-variant | `PP-PP` | `PP-PP` | PASS | REWRITE ✗ | 0.42 | PASS |
| soft-combinations-020-base | `PP-PP` | `PP-PP` | PASS | PASS | 0.42 | PASS |
| soft-combinations-020-hard-fail | `PP-PP` | `PP-FP` | PASS ✗ | REWRITE | 0.42 | REWRITE |
| soft-combinations-020-soft-variant | `PP-PP` | `PP-PP` | PASS | REWRITE ✗ | 0.42 | PASS |
| soft-combinations-021-base | `PPPPP` | `PPPPP` | PASS | REWRITE ✗ | 0.42 | PASS |
| soft-combinations-021-hard-fail | `PPPPP` | `PPPPF` | PASS ✗ | REWRITE | 0.42 | REWRITE |
| soft-combinations-021-soft-variant | `PPPPP` | `PPPPP` | PASS | REWRITE ✗ | 0.42 | PASS |

错误家族分布：

- C 的 9 个错误全部是漏检（false PASS），分布 continuity-context 4 / hard-boundaries 3 / soft-combinations 2，无误报。
- B 的 11 个错误中，6 个是 false REWRITE，其中 5 个集中在 soft-combinations；另 5 个 false PASS 中 4 个在 hard-boundaries。
- 三个两臂都没抓到的缺陷：`021-qminus`（`UST=FAIL`，内容为 "The invoice print styling was fixed and checked."）、
  `hb-01-multi`（长篇流程叙述掩盖技术状态）、`hb-03-multi`（长段落末尾一处单次观测推断为结论）。

## 7. 与既有归因报告的关系

[`2026-08-27` 报告](2026-08-27-publication-critic-model-side-failure-analysis.md) §6.1 把最高可信度给了
“reward-model 家族与 Publication Critic 语义对齐不足”，并把“任务分解是否应由单标量承担”列为最该提高优先级的研究方向。
Plan 100 正是为回答后者而立的。本报告的结论是：

- **Plan 100 没有反驳旧报告，也没有确认它。** 由于 §4.1–4.2，本次实验对“单标量 vs 五维”的绝对能力问题没有得到有效测量。
- **在相对比较层面，Plan 100 的数据倾向于支持旧报告 §9 的方向判断**：结构化分解（C）确实比单标量（A）和直接判定（B）更稳，
  尤其在“不误伤合格候选”和“对纯风格变化保持不变”两点上。这是旧报告预测的方向，只是强度不足以跨过为训练路径标定的门。
- **一个新增的、旧报告没有的事实**：Plan 099 的训练模型在五个评价点上全部是
  `decision_config_unavailable:QualificationError`——**连一个可用的阈值配置都没能形成**，
  尽管 total loss 从 `1.336` 单调降到 `1.036`。把它与 Plan 100 并列看：
  训练侧是“学到了东西但形不成决策配置”，推理侧是“不给推理预算就形不成稳定判断”。
  两边都没有把“任务语义本身能否被判别”这个问题推进多少。

## 8. 不能确认的事项

- 不能宣称 `deepseek-v4-flash` 在开启 thinking、给出示范或允许解释后一定能跨门；本次没有任何该条件下的观测。
- 不能宣称 A 臂在修正示例锚定后会有可用曲线；`65:10` 只是 7 个非锚定取值撑起的观察，样本极小。
- 不能宣称 v10 标签整体有问题；§4.4 只识别出约 3 条与 rubric 文本不一致或边界模糊的标注。
- 不能宣称五维分解优于其它表达是稳健结论；C 与 B 的差距在 `n=27` 上同样不显著。
- 不能把 `12/15` 的 B∪C 覆盖当作某个可实现系统的性能；它是两次独立采样的并集，不是一个可部署的判据。
- 不能据本报告推翻 Plan 100 的验收；执行、复算、费用与终态推导都是有效的。
- 不能从 v10 development validation 推断 qualification、v9 test 或真实 RONDO Multi 发布流的表现；本报告没有读取任何冻结 unseen。
- 不能确认 §4.1–4.5 各因素之间的严格贡献比例；本报告给的是按证据强度的可信度排序，不是因果分摊。

## 9. 对后续研究方向的含义

本节只记录证据导出的研究优先级，不构成现行 WBS、不解锁任何工作包、不申请授权。任何后续动作以
[`doc/WBS.md`](../WBS.md) 与 [`doc/WBS/multi-agent-trusted-evidence.md`](../WBS/multi-agent-trusted-evidence.md) 为唯一来源。

### 优先级应提高

- **先修掉示例锚定与单次采样**：输出契约改用不含合法取值的占位示例（或多个取值不同的示例），并对每个 candidate 重复采样以给出方差。
  这两项都不改变任务、数据、rubric 语义或部署条件，成本与本次同量级。
- **把 thinking 开关本身做成对照变量，而不是隐含前提**：关闭对应部署目标（一次前向），开启对应任务信息上界。
  同一批 packet、唯一差别是该开关，就能把“任务本身难判”与“任务在一次前向内难判”一次性分开——
  这正是旧报告 §6.1 一直没能关闭的问题。开启后按 provider usage 结算即可精确计费；
  若仍要保留缺失 usage 的兜底路径，其自检应只约束可离线复算的部分（如 prompt），不应反过来限定被测模型的输出形态（见 §3.2）。
- **门与设定解耦**：为推理路径单独标定准入门，不复用为“可调 decision config 的训练路径”标定的阈值；
  或者给推理路径一个等价的、预冻结的阈值/聚合自由度。诊断性任务也可以只报数字与区间、不设通过门。
- **报告相对结论的出口**：路线映射需要一个“绝对门未过但相对排序有信息”的合法终态，
  否则以后每次绝对门全灭都会丢掉本次这样的比较信息。
- **把“漏检”和“归属错误”分开计量**：现有逐维 recall 把两者混同，掩盖了 C 实际“能发现问题但放错抽屉”的形态。
- **rubric 与标注约定对齐**：优先复核 `scope_and_signal` 的标注是否与其 rubric 定义一致（§4.4 的两条为已知不一致点）。
- **cohort 分辨率**：`n=27`、逐维支持度 `3–6` 无法支撑 `0.75/0.8` 量级的合取门；
  要么扩大支持度，要么改用与样本量相称的判据。

### 优先级应降低

- 在不改测量配置的前提下换模型重测；那只会重复测到同一个配置伪影。
- 把 `TASK_EXECUTABILITY_INSUFFICIENT` 当作关闭任务表达路线的依据。
- 继续在 v10 validation 上叠加观察而不扩充支持度；该集合已被 Plan 098/099/100 与本报告反复查看。
  若只是做“配置修复前后的同集合对照”，继续使用 v10 是合适的；但其绝对数值不得当作泛化结论。
- 以“单次干净 formal”为荣而不做任何重复采样；在本任务的样本量下，单次观测的方差是主导误差源。
  防止挑结果需要的是“预冻结判据 + 所有轮次全部记账并报告”，而不是“只允许跑一轮”。
- 让计费/对账机制的自检要求反向决定实验条件；对账应服务实验，不应定义实验（§3.2）。

## 10. 最终判断

- **Plan 100 的执行与验收**：有效。81/81 完整、0 parse failure、费用逐 token 结算、独立复算通过，终态按预冻结规则正确推出。
- **失败的直接层**：不是基础设施，不是数据整体，也不是“任务不可表达”。
  按贡献排序是：**示例锚定与单次采样 > 门槛不可比且不可分辨 > 五维语义重叠导致的归属错误 > 局部标签不一致 > 真实模型能力缺口**。
- **关闭 thinking**：不列入上述排序。部署目标（本地 1.7B scorer、Plan 099 五头）本来就是零推理步骤的单次前向，
  关闭它贴近而非远离部署条件。它影响的是**结论覆盖范围**——一次前向下的失败无法区分“任务难判”与“一次前向内难判”。
  但其**冻结理由不成立**：思考 token 计入 completion usage、账单精确可结算，
  真正的阻塞是一条要求“离线复算 completion 与 provider 精确相等”的自检门，而该兜底路径在 99 次调用中一次未被使用（§3.2）。
- **A 臂**：结果无效。`20/27` 复述示例值 `0.42`，boundary 门算术上不可达；在能分辨的比较里反而是 `65:10`。
- **B 臂**：存在一个可命名的偏差——把“先前上下文不可用”当作候选缺陷，与 rubric 明文相反，贡献了它 6 个误报中的 5 个。
- **C 臂**：三臂中最好，且是唯一不误伤合格候选的表达；continuity 适用性判断 `12/12` 全对。
  这条正向信息被路线映射的绝对门前置结构吞掉了。
- **对旧报告的影响**：[`2026-08-27`](2026-08-27-publication-critic-model-side-failure-analysis.md) §6.1/§6.2 提出的
  “模型—任务—数据匹配”疑问**仍然开放**；Plan 100 原本要回答它，实际主要测到了自己的测量配置。
- **一句话**：这次的负向结论**记录正确，命名过强，信息量被设计约束压到了很低**——
  它证明的是“在零示范、单次采样、示例值被原样抄回的条件下，用一把为可调训练路径标定的尺子，
  一次前向级别的三种表达都没跨过去”，而不是“Publication Critic 这个任务判不了”。
