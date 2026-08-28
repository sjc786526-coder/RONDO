# Plan 098 工作包一首轮审查

## 结论

- 审查对象：`d4cdec9921405ca3863bf1512163c4332dab856c`。
- 权威合同：`rondo-publication-critic-task@v2`，申报 SHA-256
  `4a0f56a4fc1928a186864a14823eb3e7ead438aad96a746f59f37c9f470e8b0d`；复算一致。
- 状态：**验收不通过 / 工作包一任务目标失败**。工作包二继续锁定；整改复验后可重新判定。
- 总体判断：五头、非补偿 gate、派生 scalar、typed 外部 seam、物理 split consumer 和历史隔离主方向正确；但正式模型输入、applicability、head 解码与 Boundary loss 仍有会造成语义漂移或 false PASS 的缺口，不能把当前提交冻结为工作包二前置。

## Findings

### High 1：正式 rubric 没有向模型定义五个 hard heads

权威合同在 `doc/rondo-multi-publication-critic-task-contract-v2.md:40` 定义了五项 PASS/FAIL 边界，但正式 renderer 只把固定 rubric 与 packet 交给模型；`qualification-rubric-v2.md:3-9` 只列 head 名称和总体规则，没有解释 `useful_state_transfer`、`honest_uncertainty`、`scope_and_signal`、`internal_consistency` 的具体判定含义。模型无法读取仓库中的权威 Markdown，因此“合同存在”不等于“正式输入可执行”。

整改要求：把五项紧凑、无歧义的绝对判定边界、continuity 适用规则、非补偿规则和 soft 禁入规则写入正式 v2 rubric；补 focused test，直接证明正式渲染消息包含这些规则且仍不包含监督/生成元数据。不要求新增解释协议或第二套 renderer。

### High 2：continuity `N/A` 的模型可见依据仍是标签自证

权威合同 `:29-38` 要求 `N/A` 只能来自 candidate 明确且一致的完成陈述，依据能逐字指回正式 packet；但 `successor_data.py:181-188` 只根据标签反推一个通用枚举字符串，未锚定 `candidate.summary/handoff`。审查者已复现：candidate 明确写着 “Work is still in progress and the failure remains unresolved.”，同时标 `conditional_continuity=N/A` 与 `model_visible_complete_claim`，validator 仍接受。该标签随后会从 gate 排除 continuity。

整改要求：为 applicability basis 增加 bounded、可机械核对且确实来自模型可见 candidate 的 field/quote/span 或等强引用；validator 至少验证引用存在于正式 summary/handoff、标签与 basis 类型一致、隐藏 completion metadata 仍被拒绝。引用语义是否充分由工作包二盲审判断，不要实现关键词 NLP、严格因果或复杂可信设施。补完成、明确未完成、冲突/错误 basis 的回归用例。

### High 3：平局 logits 当前 fail-open 为全 `PASS`

`successor_task.py:369-379` 使用 class 顺序上的首个最大值；所有 classes 都以 `PASS` 开头。审查者复现全零 logits 被解码为五头全 `PASS`，最终 gate 为 `PASS`。权威合同没有冻结这一行为，且它违背资格判定对不确定输出的保守方向。

整改要求：在权威合同与 reference 中冻结简单、确定性的逐头离散/tie 规则；平局不得静默成为 `PASS`，建议 fail-closed 为该 head `FAIL`。补全零和局部平局测试。无需改变训练期连续近似的自主选择。

### Medium 1：Boundary loss 职责没有完整落到权威文字与 reference target

Plan/WBS 要求 Boundary 同时监督目标 hard head、两端绝对资格和非目标维度不变性。当前权威合同 `:91-93` 把后两者主要写成 pair validator 前置，并称其“只推动 target head”；reference 只有 pair 合法性校验，没有给训练者一个闭合的 Boundary target/reference，后续仍需猜测 `L_boundary` 是否只等于 target margin。

整改要求：明确 `L_boundary` 包含有限 target margin、两端绝对 gate 约束和非目标 head 预测不变性，且不取代主体 `L_dim`；提供轻量 pair-loss target/reference 与定向测试。具体公式、权重和 margin 仍由后续执行者自主决定。

### Medium 2：machine projection 自相矛盾

- `successor-release-schema-v1.json` 声明 Draft 2020-12 JSON Schema，但没有标准 `type/properties/required` 约束；标准 validator 会把其中自定义字段当 annotation，从而接受空对象或旧对象。
- 权威禁止的 `source/generator/candidate_brief/hidden_generation_intent` 等来源，在 task projection、release projection 和 Python exact list 中集合不一致。
- output JSON Schema 无法表达 logits 行数等于 `batch_size`，而 runtime 会严格拒绝；目前没有明确谁负责跨字段约束。

整改要求：不建设新 schema 平台。可以把 release 文件补成真实可执行 schema，也可以明确改为非 JSON-Schema contract projection 并移除错误的 Draft 声明；无论哪种方案，必须明确 runtime validator 是跨字段/关系约束的权威执行入口。统一禁止来源集合，并增加 projection/runtime parity 与旧格式拒绝测试。

### Medium 3：invariance 与逐 pair 评价测试尚未证明合同语义

现有 soft-only 测试只比较两份相同 labels，没有通过完整 split 构造真实不同的 soft-only candidate 文本。pair evaluator 也只返回 kind 聚合计数，未兑现合同“每个 Boundary 是否闭合”的报告语义。

整改要求：增加一对 public context 相同、candidate 文本确实发生 soft-only 变化的完整 split fixture，证明两端 hard labels/applicability/gate 不变且任一 hard 漂移会被拒绝；评价结果应能定位每个输入 pair 的闭合状态和简洁失败原因。保持轻量，不增加审计数据库或历史流水设施。

## 已确认通过的部分

- 单 backbone/一次-forward 元数据、恰好五 heads、无 global head、旧 `[B,1]` 拒绝方向正确。
- 任一适用 hard fail 不可补偿，`quality=min(applicable satisfaction)` 与 continuity `N/A` 排除规则的纯函数正确。
- Boundary 标签端点的 `Q+ PASS && Q- REWRITE`、目标 PASS→FAIL 和非目标标签不变校验正确。
- train loader 不打开 validation/test bytes，validation 使用独立入口且没有 test loader。
- 产品 Rust typed seam、旧 scalar/runtime/template 路径未改；v8 tree `63981483baa00c671987d4b82887909fcc320690`、v7 tree `435c06fba3196bee21d59d88b9e6d6b1a1e1999a` 保持不变。

## 验证

- 审查者重跑 successor 10 项和旧 contract/training-data/identity 31 项：`41/41` passed，0 failure/error/skip。
- 四份新 JSON 均可解析；提交 diff check 通过；审查前 worktree clean。
- 额外轻量反例确认：缺少可见完成声明的 `N/A` row 被接受；全零 logits 解码为全 `PASS`。
- 未运行 Rust/Cargo、Docker、真实模型、GPU、API、冻结测试或旧 unseen。

## 代用户作出的范围内决定

1. 接受“不修改 Rust product seam、只使用模型可见 candidate/public packet 操作化 completion applicability”的总体路线；但必须在产品/任务合同中明确这一可观察边界，以及虚假、冲突或无支撑的完成声明如何由其他 hard heads 处理，并落实上述可见 basis 引用。无需新增权威隐藏完成字段。
2. 不要求建立完整通用 JSON Schema/审计平台；执行者可在“真实 schema”与“明确的 contract projection + strict runtime validator”之间选更干净方案。
3. 整改只需重跑 successor focused tests 和直接受影响的旧合同/identity 回归，不要求 Rust 或全量重型测试。

## 复验入口

执行者应只在工作包一范围内修复上述 findings，更新权威合同 SHA-256、实施日志、Plan/WBS 状态并提交 clean worktree；随后按既定 Codex queue 协议申请复验。工作包二在明确复验通过前不得开始。
