# Plan 098 工作包一实施日志

## 实质修改

- 新增唯一权威任务合同 `rondo-publication-critic-task@v2`，把现行产品五项 hard requirement 固定为一次 backbone forward 的五个绝对 decision heads；只有 `conditional_continuity` 可为 `N/A`。
- continuity applicability 只从模型可见 candidate 的完成状态陈述判断；successor row 不接受旧 `completion_state`、`public_state`、candidate brief、defect 或 reviewer metadata 作为标签事实。
- 新增 v2 rubric、v3 input、v4 render、task/output schema 和 successor release contract projection。现有 `PublicationPacket@v1`、renderer mechanics 与 typed `PASS/REWRITE` 产品 seam 复用但不改写。
- 新增纯函数 reference：完整五维标签、applicability、all-hard-pass、派生 min scalar、loss targets、Boundary/soft-only invariance 闭合、五头/gate/pair 评价以及严格一次-forward 五头输出校验。
- 新增物理 split successor consumer：manifest 绑定任务合同内容 SHA-256 与 accepted commit；train 只打开 train candidate/pair bytes，validation 只有独立入口，不提供训练/选择使用的 test loader。
- 产品合同只增加到新任务合同的职责链接；冻结 v8、旧 scalar objective、旧 validator/render、Rust scorer/wire 与 Team State 行为均未改。

## 关键取舍

- 没有增加 Rust packet 字段。现有 canonical title/summary/handoff、bounded continuity 与 Evidence V1 已足够让模型依据公开文本判断；把隐藏 completion flag 放进 packet 反而会形成可规避的并列事实。
- successor validator 通过仅替换 qualification revision 的内存兼容视图复用冻结 v1 packet 机械校验，原 `contract.py` 字节保持不变，避免破坏 Plan 054/v8 measurement identity。
- 本阶段没有选择后继数据 revision、模块、数量、配比或 split 成员，没有生成正式数据。

## 首轮审查整改

- 正式 rubric 补齐五头 `PASS/FAIL/N/A` 的模型可执行边界、非补偿 gate 与 soft 禁入规则；渲染测试确认规则进入固定模型输入，而 candidate/group/basis 等 sidecar 值不进入。
- `continuity_label_basis` 改为 `type + field + bounded exact quote`，机械核对引用来自 `candidate.summary/handoff`；语义充分性继续交给工作包二逐块盲审，不引入关键词 NLP 或隐藏完成事实。
- 五头解码冻结为唯一最大值；逐 head 平局和全零均 fail-closed 到 `FAIL`。Boundary reference 同时输出 finite target margin、两端绝对 gate 和非目标预测不变性 targets。
- release 文件改为明确的非 JSON-Schema contract projection；output schema 明示 runtime 跨字段入口。task/release/Python 的 forbidden model-input 字段统一，并保留旧格式拒绝。
- pair 评价增加逐 `pair_id` 闭合状态与简洁失败原因；完整 split fixture 验证真实 soft-only 文本变化保持五维/applicability/gate 不变，hard 漂移会被拒绝。

## 验证

- successor 合同、projection、reference、renderer/consumer focused tests：`11/11` passed。
- 旧 Publication Critic contract、training-data 与 frozen input identity 定向回归：`31/31` passed。
- 合计 `42/42` passed，0 failure/error/skip。
- `training/publication-critic-v8` Git tree：`63981483baa00c671987d4b82887909fcc320690`，与任务开始时一致；v7 tree：`435c06fba3196bee21d59d88b9e6d6b1a1e1999a`，与任务开始时一致。
- 权威合同内容 SHA-256：`3eb0539b16403ebe20e74ce1b1ea5114d2383c6118f61fef56c9c91426e6a560`。
- 未运行 Rust/Cargo、真实模型、Docker、GPU、付费 API 或冻结测试。

## ignored 资产

- 未创建或修改 `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098/`；工作包一无需 raw/draft/prefreeze 暂存。
