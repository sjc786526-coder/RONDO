# RONDO Multi Publication Critic decision and qualification contract v1

本文是 `rondo-publication-critic-task@v2` 的正式判定与资格评价合同，身份为
`rondo-publication-critic-decision@v1`。v2 task contract 继续唯一权威定义模型可见输入、五个 hard heads、绝对标签、loss、
非补偿 gate 与产品 typed verdict；本文只闭合 raw head logits 之后的 operating point、冻结时点和资格指标，不改变任务标签或增加
第六 head。

## 1. 逐 head 判定

正式判定配置只能让每个 head 使用自己的 finite raw logits：

- 四个二分类 head 各冻结一个非负 `pass_over_fail_margin`。只有
  `PASS logit - FAIL logit > margin` 才判 `PASS`，否则 fail-closed 为 `FAIL`。
- `conditional_continuity` 同样冻结非负 `pass_over_fail_margin`，并另冻结严格为正的
  `na_over_applicable_margin`。只有 `N/A logit - max(PASS logit, FAIL logit) > na margin` 才排除该 head；
  未达到排除 margin 时，只有 `PASS logit > N/A logit` 且 `PASS logit - FAIL logit > pass margin` 才判
  `PASS`；其余适用性模糊、平局或未达 PASS 边界都 fail-closed 为 `FAIL`。
- 不允许 global threshold、跨 head 分数、加权或平均补偿、soft preference、自由 scalar、第六资格 head 或第二次 backbone forward。
  margin 只移动本 head 的 operating point，不能改变其他 head。

精确平局、margin 边界相等、N/A 微弱胜出和无法形成合法配置都必须 fail-closed。最终 typed verdict 仍由 v2 task contract 的
all-applicable-heads AND 唯一派生。

## 2. 配置身份与冻结时点

正式 decision config 必须是可 canonical 序列化的严格对象，并绑定：

- `rondo-publication-critic-task@v2` 权威内容 SHA-256；
- 本 decision contract 的版本与内容 SHA-256；
- decision decoder、config projection 与 qualification metrics 的固定组件列表和组合 SHA-256；
- 单个 model artifact SHA-256；
- 单个 development data revision、manifest SHA-256 与 validation candidate bytes SHA-256；
- 五个逐 head margin；
- `selection.split=validation`、有界选择方法、`test_access=forbidden` 和 `frozen=true`。

margin 可由训练阶段在显式候选集合中使用 validation 确定。标准 reference selector 只接收 validation labels 与 logits，以逐 head
macro recall 的最弱项为第一目标，再依次偏好更少 gate False PASS、更高 gate correct、更少 False REWRITE，并用 canonical config
bytes 确定性破同分；它不提供 test 参数或 test loader。调用者也可采用等强的 validation-only 选择法，但最终 config 必须通过同一
strict validator 并在任何资格集合释放前冻结。

test、现有 v9 同分布辅助 holdout、独立 qualification set 都不得参与 margin 搜索、候选淘汰或 config 修改。model、task、decision
contract、decision implementation bundle 或 development data 任一身份变化都使已冻结 config 失效，必须重新使用 validation 选择；
资格结果不得反向调参。运行时必须先核对固定组件字节，不能只凭 Markdown 或版本字符串接受旧 config。

## 3. 固定资格指标

每次资格评价必须按固定类别顺序报告逐 head confusion：四个 binary heads 为 `PASS/FAIL` 2×2，continuity 为
`PASS/FAIL/N/A` 3×3。每个 head 还必须显式报告：

- `gold_pass`、`gold_fail`、`fail_detected`；
- `FAIL→PASS`、`FAIL→N/A`、`PASS→FAIL`、`PASS→N/A`；
- failure recall 的 numerator、denominator、status 与 value。

`gold_fail=0` 时 failure recall 必须为 `status=unavailable`、`value=null`，不得伪造 0 或 1。continuity 的其余 N/A 错误由完整
3×3 confusion 固定保存。gate 继续报告 total、correct、False PASS 与 False REWRITE；多缺陷样本即使 gate 仍正确，某 head 的
`FAIL→PASS/N/A` 仍必须计入该 head 漏检。

Boundary 和 soft-only invariance 继续沿用 v2 task contract 的逐 pair 绝对闭合指标。旧 ROC AUC、自由阈值或 PASS 内排序只能作为
诊断，不能替代本节指标。

## 4. 数据与 holdout 边界

- development consumer 只暴露 train 与显式 validation。validation 可用于模型开发和 decision config 选择，但不得冒充最终资格。
- `publication-critic-v9` 的既有 test 保持原字节封存，只作为同分布辅助 holdout；本合同不提供读取入口，也不允许本轮数据整改使用它。
- 独立 qualification set 必须由未接触 v9 生成过程、训练结果和 decision config 的 test-only 负责人生成，并由另一位独立盲审员接受。
  非模型输入 sidecar 必须记录 source/scenario/template family；整个 family namespace 与 development generation 分离。
- qualification set 在训练前完成生成、盲审和封存，但正式读取只属于后续资格工作包。它不参与训练、validation 选择或阈值调整，结果也不得
  反向修改 model/config/data。

开发数据可以针对已确认的表面捷径做有界 train/validation 反例整改。整改必须保留绝对标签与 pair 关系，只由原模块负责人修改、原盲审员
复核；不得打开现有 test。固定词表和长度统计只作轻量诊断，不成为新的标签判定器。

## 5. 产品与完成边界

本文不改变产品 `PASS/REWRITE` wire、重写/fallback/cancel/canonical commit 或 Team State 行为，也不授予模型质量、产品价值、默认启用
或生产资格。真实训练、test/qualification 释放和产品动作仍分别服从后续 ExecPlan 与授权门。
