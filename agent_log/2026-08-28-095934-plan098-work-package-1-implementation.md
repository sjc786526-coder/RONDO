# Plan 098 工作包一实施日志

## 实质修改

- 新增唯一权威任务合同 `rondo-publication-critic-task@v2`，把现行产品五项 hard requirement 固定为一次 backbone forward 的五个绝对 decision heads；只有 `conditional_continuity` 可为 `N/A`。
- continuity applicability 只从模型可见 candidate 的完成状态陈述判断；successor row 不接受旧 `completion_state`、`public_state`、candidate brief、defect 或 reviewer metadata 作为标签事实。
- 新增 v2 rubric、v3 input、v4 render、task projection、结构化 output 和 successor release schema。现有 `PublicationPacket@v1`、renderer mechanics 与 typed `PASS/REWRITE` 产品 seam 复用但不改写。
- 新增纯函数 reference：完整五维标签、applicability、all-hard-pass、派生 min scalar、loss targets、Boundary/soft-only invariance 闭合、五头/gate/pair 评价以及严格一次-forward 五头输出校验。
- 新增物理 split successor consumer：manifest 绑定任务合同内容 SHA-256 与 accepted commit；train 只打开 train candidate/pair bytes，validation 只有独立入口，不提供训练/选择使用的 test loader。
- 产品合同只增加到新任务合同的职责链接；冻结 v8、旧 scalar objective、旧 validator/render、Rust scorer/wire 与 Team State 行为均未改。

## 关键取舍

- 没有增加 Rust packet 字段。现有 canonical title/summary/handoff、bounded continuity 与 Evidence V1 已足够让模型依据公开文本判断；把隐藏 completion flag 放进 packet 反而会形成可规避的并列事实。
- successor validator 通过仅替换 qualification revision 的内存兼容视图复用冻结 v1 packet 机械校验，原 `contract.py` 字节保持不变，避免破坏 Plan 054/v8 measurement identity。
- 本阶段没有选择后继数据 revision、模块、数量、配比或 split 成员，没有生成正式数据。

## 验证

- successor 合同、schema、reference、renderer/consumer focused tests：`10/10` passed。
- 旧 Publication Critic contract、training-data 与 frozen input identity 定向回归：`31/31` passed。
- 合计 `41/41` passed，0 failure/error/skip。
- `training/publication-critic-v8` Git tree：`63981483baa00c671987d4b82887909fcc320690`，与任务开始时一致；v7 tree：`435c06fba3196bee21d59d88b9e6d6b1a1e1999a`，与任务开始时一致。
- 权威合同内容 SHA-256：`4a0f56a4fc1928a186864a14823eb3e7ead438aad96a746f59f37c9f470e8b0d`。
- 未运行 Rust/Cargo、真实模型、Docker、GPU、付费 API 或冻结测试。

## ignored 资产

- 未创建或修改 `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098/`；工作包一无需 raw/draft/prefreeze 暂存。
