# RONDO Multi Publication Critic task contract v2

本文是 Publication Critic 后继训练任务的**唯一权威语义合同**，身份为
`rondo-publication-critic-task@v2`。产品的发布、重写、fallback、取消和 Team State 语义仍由
[`rondo-multi-publication-critic-product-contract.md`](rondo-multi-publication-critic-product-contract.md)
负责；本文只把该稳定产品边界投影成可训练、可评价的五头 hard-decision 任务。

`eval/templates/publication-critic/` 下的 v2 rubric、v3 input contract、v4 render contract、task/output schema 与 release projection
以及 `eval/rondo_eval/publication_critic/successor_*.py` 都只是本文的机器投影或实现。发生冲突时以本文为准。
冻结的 v8、旧 `[B, 1]` scalar objective、历史结果和 cloud/local engineering fixture 不实现本文，也不得冒充
后继任务。

## 1. 正式输入与适用性

正式模型输入复用经过严格机械校验的 `rondo-publication-packet@v1` 公共字段，并绑定
`rondo-publication-qualification@v2`。模型只看到固定 rubric 与以下 bounded、permission-scoped 内容：

- 权威 `actor_role`、`target_kind`、canonical local-scope title；
- canonical candidate summary 与 optional handoff；
- existing Event 的有界 continuity envelope，或 new Event 的 `not_applicable` continuity；
- Evidence V1 的 body-free policy、coverage、freshness 与 omission 状态。

输入继续排除 private transcript/reasoning、全 Team State、raw evidence、Fact 正文、密钥以及 `completion_state`、
`public_state`、candidate brief、hidden generation intent、split、labels、defects、source、generator、reviewer、
pair direction、rationale 等监督或生成元数据。renderer 只接受 packet 与固定 rubric，不接受 supervision 参数。

### conditional continuity 的适用性

`conditional_continuity` 是否适用只由上述**模型可见 candidate 自身**表达的工作状态决定：

- candidate 明确、内部一致地声明事项已经完成时，该维度为 `N/A`；缺少 handoff 不能因此失败；
- candidate 明确仍未完成，或完成状态没有被模型可见文本明确闭合时，该维度适用，必须判为 `PASS` 或 `FAIL`；
- candidate 的完成/未完成陈述互相冲突时，不得标 `N/A`；至少 `internal_consistency=FAIL`，并按实际 continuity
  质量给出适用的 `conditional_continuity` 标签。

因此 successor supervision 不接受旧 `completion_state`、scenario `public_state`、candidate brief 或隐藏生成意图
作为标签事实。`N/A` 的审查依据必须能逐字指回正式 packet。旧 packet 中名为 `continuity` 的字段是 prior
publication context，不是完成状态标签，也不能自动决定该 head 是否适用。

数据侧的 `continuity_label_basis` 必须记录 `type + candidate.summary/candidate.handoff + bounded exact quote`，
validator 机械确认引用确实存在于该模型可见字段、且 basis type 与 `N/A`/适用标签一致；quote 本身不进入模型输入。
引用是否足以表达完成、未完成或未闭合由数据盲审负责，不用关键词 NLP 或隐藏事实替代。若 candidate 的完成声明与同一
packet 可见内容冲突，continuity 继续适用并至少令 `internal_consistency=FAIL`；若它对可见限制发生确定性越级，还令
`honest_uncertainty=FAIL`。只有私有/隐藏世界才知道的真假不进入本任务，不能改变 applicability。

## 2. 五个 hard decision heads

一个 backbone 在一次 forward 中产生且只产生以下五个资格 heads：

| head | 合法绝对标签 | `PASS` | `FAIL` |
|---|---|---|---|
| `useful_state_transfer` | `PASS / FAIL` | local scope 内有可依赖或可继续的具体状态 | 只有空泛进度或没有可用状态 |
| `honest_uncertainty` | `PASS / FAIL` | observation、inference、suspected、unknown 的确定性被诚实保留 | 对模型可见限制发生确定性越级 |
| `conditional_continuity` | `PASS / FAIL / N/A` | 适用时给出进展、卡点或下一起点 | 适用但无法接续；`N/A` 仅按 §1 使用 |
| `scope_and_signal` | `PASS / FAIL` | 核心公共状态在 local scope 内清晰可辨 | 过程 dump、重复或离题内容淹没信号 |
| `internal_consistency` | `PASS / FAIL` | title、summary、handoff 和所给 continuity 的关键状态相容 | 完成状态、验证状态或下一动作发生关键冲突 |

四个二分类 heads 永远适用，不能输出 `N/A`、`UNKNOWN` 或 `ABSTAIN`。模型输出合同不得加入自由
global-quality、第六资格 head 或第二次 backbone forward。结构化 logits 的合法宽度是四个二分类 head 各 2，
`conditional_continuity` 3；旧 scalar `[B, 1]` 不是合法 successor 输出。

逐 head 解码只接受唯一最大 logit；最大值平局（包括全零）一律把该 head 解码为 `FAIL`。该 fail-closed 规则不创造
新标签或第六 head，也不限制后续训练期连续近似的具体实现。

## 3. 确定性 gate 与投影

正式资格判定是非补偿合取：

```text
applicable = all heads except conditional_continuity when it is N/A
PASS       = every applicable head is PASS
REWRITE    = any applicable head is FAIL
```

`N/A` 只排除确实不适用的 continuity head，不提供正向分数。其他 head 的高置信度、文风、长度或 soft
preference 不能补偿任一 hard failure。产品外部仍只消费 typed `PASS/REWRITE`。

若内部兼容接缝需要连续 scalar，唯一合法投影为：

```text
quality = min(applicable PASS satisfaction)
        = 1 - max(applicable violation)
```

它是五头 gate 的派生诊断，不是可独立学习或决定资格的 overall-quality head。正式 typed verdict 由离散
all-hard-pass 规则产生，不由平均、加权和、平滑近似或自由 threshold 替代。误判 `N/A` 是
`conditional_continuity` 分类错误，必须在 per-head/applicability 与 gate False PASS 指标中显式计入。

## 4. 监督与 loss 职责

训练结构固定为：

```text
L = L_dim + lambda_gate L_gate + lambda_boundary L_boundary + lambda_inv L_invariance
```

- `L_dim` 是主体，输入为每个 candidate 完整五维绝对标签；未列 defect 不得推定其他维度 `PASS`。
- `L_gate` 只监督由五维标签和五头输出派生的合取 gate，不创建第六 head。训练期连续近似可以使用已标注的
  applicability mask，但正式推理必须回到 §3 的离散规则。
- `L_boundary` 只接收通过严格 pair validator 的 Boundary：`Q+` 的全部适用 heads 为 `PASS`，`Q-` 的
  target head 为 `FAIL`，非目标 heads（含 continuity `N/A`）绝对标签完全相同。其辅助约束同时包含 target head
  的有限 margin、两端 `Q+ PASS && Q- REWRITE` 的绝对 gate 约束，以及全部非目标 head 的预测不变性；达到有限
  margin 后不继续无界扩大。它不取代两端各自完整的 `L_dim`。
- `L_invariance` 只接收 soft-only / Within-PASS pair：两端均为 typed `PASS`，五维标签和 applicability
  完全相同；它约束五头与派生 gate 不随 soft 变化漂移，不训练 preferred PASS 取得更高资格分。

精确连续近似、lambda、margin 和优化器留给后续主训练方案冻结，但不得改变上述合法输入和方向。soft
preference 完全退出资格 loss、threshold、typed verdict 与 PASS 内资格排序；未来若有真实排序消费者，须另立独立任务。

## 5. 数据与 consumer 接口

successor candidate 必须同时携带：严格 `PublicationPacket@v1`、完整五维标签、由模型可见字段和 exact quote 支持的
continuity label basis，以及关系闭包用 group identity。监督与 packet 物理分离于 renderer API；任何 row 都不得用
隐藏完成状态、defect 列表或 reviewer rationale 补足模型看不到的判断事实。

Boundary 与 invariance pair 必须满足 §4 的绝对端点条件。candidate/pair 按 split 物理分文件；manifest 只记录
各文件的相对路径、SHA-256 与行数。默认 train consumer 只打开 train candidate/pair bytes；validation 只有显式独立
入口；本任务不提供面向训练或方案选择的 test loader。新 release 必须自包含，不要求调用者跨目录拼 v8 或旧 validation。

后继 release contract、精确 revision、模块、数量、配比和 split 在 Plan 098 工作包二由本合同导出并冻结；本文不预先
选择 revision 或生成正式数据。

release JSON 是明确标注的 contract projection，不冒充通用 JSON Schema；`successor_data.py` 是跨字段、文件哈希、
endpoint 关系和物理读取约束的权威 runtime validator。结构化 output 使用标准 JSON Schema 固定局部 shape；
`successor_task.py#validate_structured_output` 权威执行 batch-size 相等与 finite logits，随后
`successor_task.py#decode_structured_output` 执行逐 head tie fail-closed。

## 6. 评价语义

资格评价至少独立报告：

- 每个 head 的适用样本分类结果；continuity 另报 applicability / `N/A` 正确性；
- typed gate 的 False PASS、False REWRITE 与两类绝对计数；
- 每个 Boundary 是否同时满足 target 定向、非目标不变、`Q+ PASS && Q- REWRITE`；
- soft-only pair 的五头/applicability/gate invariance；
- 关键输入、标签和组合覆盖。

旧 ROC AUC、自由单阈值和 PASS 内 strict-win 只能作为历史诊断，不能替代上述资格语义。validation 用于开发，
test 不进入训练、方案选择或 threshold 调整。通过本任务合同或其纯函数测试不授予模型质量、产品价值、默认启用或生产资格。

## 7. 历史与产品边界

- `training/publication-critic-v8/`、旧模板/manifest、旧 scalar objective 和历史计划保持不可变、可按原身份复算。
- successor task 不改变 `PublicationScorer -> service -> typed client -> team_publish` 的外部 typed verdict，也不改变
  Producer 重写、infra fallback、取消、canonical commit、Root 或 Team State 不变量。
- 内部五头诊断不得扩张为自由解释、自动改写、第二套在线 decision service 或新的 Team State。
- 本合同只冻结工作包一语义。后继数据、训练和资格仍服从 WBS 与各自授权门。
