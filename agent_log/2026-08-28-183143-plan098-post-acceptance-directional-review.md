# Plan 098 验收后方向性复审

## 结论

- 规划者指出的四类风险均有实质依据。Plan 098 主体成果仍成立，但 `0e04cf0` 的“完整任务最终接受”结论暂停；工作包三在本轮窄整改复验
  通过前不得启动，更不能进入付费训练。
- 不推倒五头、all-hard-pass gate、v9 主体、三负责人/三盲审员或现有 consumer。整改只闭合逐头判定配置、逐维资格指标、开发 split
  的可见捷径，以及独立资格集合四项前置。
- 本轮未读取 v9 test、mixed v8 或旧 unseen。数据判断只使用 train/validation 正文与公开 metadata；test 判断只使用 split 设计、责任划分、
  计数和 hash/关系元数据。

## Finding 1：逐头 operating point 与 continuity N/A 需要显式冻结（High）

当前权威合同和 `decode_structured_output()` 只规定 unique argmax，只有精确平局才回退 `FAIL`。因此若直接把模型 raw logits 作为 decision
logits，`N/A` 仅微弱胜出也会排除 continuity，四个二分类 head 也会隐式固定在零 logit-margin 边界；现有工件没有一个可身份绑定、只由
validation 冻结的逐头 decision config。

规划者所说“完全没有合法 operating-point 空间”略显绝对：head 内 class bias、calibration 或有限 margin 可以在不增加第六 head、
不跨 head 补偿的前提下产生最终 decision logits，再沿用 deterministic decoder。但这条合法路线目前只是隐含可能性，没有合同字段、冻结时点、
N/A 保守回退、身份或 focused tests，不能作为工作包四可复算的判定配置。

最低整改语义：

- 每个 head 只能使用自身 logits/score 形成 PASS/FAIL；`conditional_continuity` 另有保守 N/A 相对 margin 或等强置信规则，证据不足时落到
  适用且 `FAIL`。
- 决策配置只用 validation 选择并在 test 释放前冻结，随 model/task/data identity 绑定；test 不参与搜索或修改。
- 最终 verdict 仍为五个适用 hard decisions 的 AND；禁止 global threshold、跨 head 加权、可补偿标量、soft preference 或第六 head。
- 实现可选择“显式 per-head decoder config”或“冻结 calibrated decision logits/head bias”等等强方案；只要语义可复算、fail-closed 且不靠
  隐含约定。具体 margin/阈值不由本报告预设。

## Finding 2：v9 test 不是充分独立的最终资格集合（High）

现有 v9 已成立的隔离包括：物理 split、group/pair closure、跨组 exact duplicate 为零、0.94 阈值的 cross-group near duplicate 为零，且
train consumer 不暴露 test。它仍是有效的同分布冻结 holdout，不应改写或打开正文。

但 Plan 098 还要求 source/scenario/template/pair/近重复关系按组隔离。当前 source 对所有 group 都只是 `new_synthetic`，schema/finalizer
没有 `source_family`、`scenario_family` 或 `template_family` 等 lineage；同一模块 owner 同时生成其 18/3/3 train/validation/test groups。
这不证明存在行级泄漏，却无法证明改写后的模板/场景家族已经跨 split 隔离。

此外 test 仅 27 candidates：各维 FAIL 支持约为 7/5/6/4/4，Boundary target 支持约为 2/1/3/1/2。它适合作为小型冻结检查，不能单独
支撑工作包四对逐维 failure recall、False PASS 和 Boundary 的 GO/NO-GO。

最低整改语义：

- 保留现有 v9 test 封存并降格为同分布辅助 holdout，不把它用于本轮数据整改或 decision config 选择。
- 在训练前由全新、未接触 v9 生成过程与训练结果的 test-only 负责人和独立盲审员生成一份有界资格确认集，或形成等强窄后继 revision；总执行者
  只做合同、机械冻结和覆盖检查，不读取正文。
- 记录不进入模型输入的轻量 source/scenario/template family lineage，并按 family 整体隔离；数量只需足以支持预定逐维失败召回、Boundary、
  False PASS 和少量 invariance，不机械扩成新平台。
- 资格集在候选与判定配置冻结前完成生成/盲审/封存，正式释放只留给工作包四且不得返调。

## Finding 3：train/validation 存在可利用的标签表面线索（Medium，付费训练前阻断）

只统计 train/validation 后，风险成立：

- `honest_uncertainty=FAIL` 与 proof/certainty/every/forever/guarantee 等词和“treated/generalized as proof”式审查者旁白高度相关；
  validation 的简单 broad-cue 规则接近覆盖全部 FAIL，而 PASS 几乎没有相应反例。若干 FAIL 直接用戏剧化绝对措辞解释错误，模型无需比较
  可见 evidence 与结论强度。
- `scope_and_signal=FAIL` 明显偏长：train/validation 的平均 candidate 文本约 327/312 字符，PASS 约 190/215；长度 AUC 约
  0.854/0.754。FAIL 又集中于 `mostly sign-off`、`buried beneath`、`long stream` 等自我批注模板。
- 现有 shortcut gate 只拒绝监督/metadata token，并要求 typed PASS/REWRITE 总长度区间有交集；没有逐 head 反例或诊断，因此当前
  `shortcut_check=true` 不能证明上述风险已闭合。

最低整改语义：

- 只改受影响的 train/validation groups，不读取或改写 test；由原模块 owner 整改、原盲审员绑定新 SHA 复验，其他已通过语义不全量重审。
- honest 补自然、含蓄的越级 FAIL，以及有完整可见依据但含绝对措辞的 PASS；scope 补简短但信号混乱的 FAIL 与较长但结构清楚的 PASS；多缺陷
  表达减少漫画化旁白。
- 用现有 tags/coverage 或轻量诊断记录反例闭合即可；不把固定词表建成新的标签规则，不建设 NLP 审计平台，也不为机械配平无限扩量。

## Finding 4：逐维评价不足以支撑资格门（Medium，付费训练前阻断）

`evaluate_predictions()` 每维目前只有 total/correct、applicability 和 N/A 计数；缺少 gold FAIL、FAIL→PASS、FAIL→N/A、FAIL recall、
PASS→FAIL 以及固定 confusion matrix。gate False PASS 不能替代：多缺陷样本即使靠另一维保持 REWRITE，也可能已经漏掉某一维 hard failure。

最低整改语义：

- 四个二分类 head 报告固定 2×2 confusion；continuity 报告固定 PASS/FAIL/N/A 3×3 confusion。
- 显式报告 gold PASS/FAIL、fail detected、FAIL→PASS、FAIL→N/A、PASS→FAIL/N/A 和 failure-recall numerator/denominator；零分母使用明确
  typed unavailable/null，不伪造 0 或 1。
- focused fixture 覆盖各 cell，并包含“总体 gate 正确但某 head 漏 FAIL”的多缺陷反例。
- 可扩展现有 evaluator 或建立一个薄的版本化 qualification metrics 层；不得复制第二套评价平台。

## 保留结论与执行边界

- 五头、单 backbone/一次 forward、非补偿 all-hard-pass、derived scalar、loss 职责、soft 退出资格、可见 continuity basis、typed
  PASS/REWRITE、v8 零复用和 v9 合同原生重构均继续成立。
- 当前 v9 主体不作废；只做开发 split 的定向反例整改并补独立资格确认集。现有 test 保持封存。
- 本轮属于用户明确要求的验收后窄整改，沿用 Plan 098 项目内合同、源码、schema、模板、数据、干净子智能体、盲审、测试、文档和 ignored
  暂存授权；不包含真实模型、GPU/RunPod、Docker、付费 API、数据外发、test/unseen 读取或产品动作。
- 工作包一核心组件若变化，accepted implementation bundle、task hash、design/config/release identity 必须按现有漂移门显式更新并重新验收，
  不能绕过或静默修改。

## 状态

- Plan 098：`POST_ACCEPTANCE_DIRECTIONAL_REMEDIATION_REQUIRED / IN_PROGRESS`。
- 既有最终接受：`SUSPENDED_BY_USER_REQUESTED_DIRECTIONAL_REVIEW`。
- 工作包三：`LOCKED / NOT_STARTED`。
