# Plan 098 工作包二最终验收首轮审查

## 结论

- **验收不通过；任务目标未完成。** `publication-critic-v9` 当前数据、split、module/review、manifest、consumer 与 smoke
  的实际工件均闭合，但工作包二 finalizer 尚未真正核验工作包一 accepted implementation identity。工作包三继续锁定。
- 本轮只有一项阻断 finding。整改应保持轻量，只补 accepted implementation 的必要语义组件指纹门与 focused regression；不建设通用
  provenance、签名、审计或可信体系，不要求重跑 Rust/Cargo、真实模型、Docker 或全量测试。
- 当前无需代用户决定授权外事项。审查者决定保留既有 `publication-critic-v9` 与 ignored commissioning 资产作为整改/复验基线；是否需要
  重新正式冻结由实际 identity 绑定方式决定，执行者可选择更优且等强的窄实现。

## Finding

### High：accepted implementation commit 只被写入，未被核验

`eval/rondo_eval/publication_critic/successor_build.py` 把
`55342bdb11b09c11b589fd398717f7712fca012c` 作为常量写入 design/manifest/release identity，并核对权威任务合同 Markdown 的内容
SHA；但 `load_build_contracts()` / finalizer 没有核对当前工作树中工作包一的必要实现投影仍与该 accepted commit 相同。随后
`SuccessorRelease.open()` 收到的 expected commit 仍来自同一个常量，因此只是自洽比较，不能发现实现漂移。

结果是：只要权威 Markdown 不变，`successor_task.py`、`successor_data.py`、正式 rubric、input/output/release projection 或其他决定
renderer、标签、loss/gate/evaluation/consumer 语义的必要组件发生漂移，工作包二仍可用 accepted commit 的名义通过 finalizer。这违反
Plan 098 已冻结的“工作包二全链 fail-closed 核对 accepted identity；任何核心合同变化重新锁定工作包二”硬门。

当前提交没有发生这种实际漂移：`55342bdb..1f34c5f` 的工作包一核心源码与模板差异为空，现有 v9 工件也与 commissioning clean-run
逐字节一致。因此整改不需要改任务定义或重做数据语义；需要把已经依赖的 accepted implementation 从声明变成可执行门禁。

最低验收要求：

- 冻结并核对一组足以代表工作包一任务实现语义的必要组件字节/组合 SHA，或采用等强、同样轻量的办法；不能只复核同一个常量或只核对
  权威 Markdown。
- finalizer 在正式写出前 fail-closed 执行该核验，并把绑定纳入现有 design/config/release identity 中合适的一处，避免再造第二套体系。
- 增加 focused regression：权威 Markdown 保持不变、任一受保护核心组件漂移时，build/finalizer 必须拒绝；正常 accepted bytes 继续通过。
- 定向重跑 successor release/contract 与受影响旧回归，确认 v7/v8、产品 typed seam 和 protected split 边界未变化。

## 已验证成立

- 审查基线为 executor commit `1f34c5fa14b6792343c2ed2678972a1757cf713d`；工作树在审查前 clean，未合并、未推送。
- 工作包一合同 SHA 为 `3eb0539b16403ebe20e74ce1b1ea5114d2383c6118f61fef56c9c91426e6a560`；当前 WP1 核心文件与
  accepted implementation commit 无差异。
- `publication-critic-v9` 为 216 candidates / 96 pairs；物理 train/validation/test 行数为 162/27/27 candidates 与
  72/12/12 pairs。全部 split raw SHA/rows 与 manifest 一致。
- manifest SHA 为 `756d7ea4c53673a447860fb4cfc245a98f5c15383569f137b1e07eacf7f90118`，release identity 文件 SHA 为
  `08d854c3b848d2135915c8908d74b27d72000128b8b29e93bab0866564f68a0e`；tracked release 与 commissioning
  `actual-release-check` 逐文件一致。
- 三个模块与三个独立 reviewer 一一对应，最终 review 均绑定模块 SHA、完整 checklist、`accept`、0 finding；tracked freeze record 与
  release identity 绑定成立。实际 `fork_turns=none` 由实施日志和轻量角色/hash 记录证明，按用户偏好不扩展为 agent UUID 或可信链。
- coverage、Boundary、三 split soft-only invariance、hard/soft 四象限、single/multi、continuity 三态、重复/捷径和长度重叠门均达到
  design lock。train consumer 只读 train，validation 为显式入口，不存在 test loader。
- 定向复跑 successor 与旧 contract/training-data/identity 共 `46/46` passed；`git diff --check`、合同/manifest/release hash、v7/v8
  tree identity 与 ignored module/review hash 检查通过。
- 审查未打开 mixed v8、旧 unseen 或 v9 test split 正文；未运行 Rust/Cargo、真实模型、GPU、Docker、API 或产品动作。

## 非阻断审查判断

- 现有 release identity 的各声明 hash 当前均机械一致，tracked release 也已有 clean-run 字节复现。可在整改触及 identity validator 时顺手补齐
  strict readback/hash assertions，但本轮不把通用 identity consumer、第二套审计链或重复的大型 determinism 设施升级为额外阻断要求。
- successor contract 已有删除 validation/test 文件后 `load_train()` 仍成功的负向测试；不再重复要求另一套文件访问审计。

## 阶段状态

- 工作包一：`ACCEPTED_AT_55342BDB`，语义不重开。
- 工作包二：`FINAL_REVIEW_CHANGES_REQUESTED`。
- 完整 Plan 098：`IN_PROGRESS`。
- 工作包三：`LOCKED`。
