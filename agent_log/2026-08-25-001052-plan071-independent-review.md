# Plan 071 独立验收审查

## 结论

- 审查状态：`NOT_ACCEPTED`
- 任务状态：`REMEDIATION_REQUIRED`
- v5 真实运行事实本身得到复核：base、C1、C3 均为 `QUALIFIED`，归档结果为
  `BASE_COMPARABILITY_GO`，且从 manifest/raw 机械重建的 observations/result 与正式归档完全一致。
- 当前实现仍有一个会错误区分 `BASE_NOT_COMPARABLE` 与 `INCONCLUSIVE` 的终态分支，因此尚不能把三态资格设施作为完整、可靠的交付验收。

## Finding

### P2：base 与全部锚点同时不合格时错误输出 `BASE_NOT_COMPARABLE`

`eval/rondo_eval/publication_critic/local_deployment/comparability.py` 的 `evaluate_run` 只在 base 为
`QUALIFIED` 时检查 `anchor_qualified`。base 为 `NOT_QUALIFIED` 时，无论 C1/C3 是否仍有一个同口径
`QUALIFIED` 锚点，都会落入 `BASE_NOT_COMPARABLE / base_not_qualified`。

轻量复现把 base、C1、C3 都构造成相同 cross-runtime gate 失败，实际得到：

```text
{'base': 'NOT_QUALIFIED', 'c1': 'NOT_QUALIFIED', 'c3': 'NOT_QUALIFIED'}
BASE_NOT_COMPARABLE base_not_qualified
```

这不符合本任务的共同口径边界：当 C1/C3 都没有保住既有合格锚点时，不能确认当前环境和规则已经建立公平对照，也就不能把 base 的失败归因为可信的
`BASE_NOT_COMPARABLE`。该状态应为带明确原因的 `INCONCLUSIVE`。只有 base `NOT_QUALIFIED` 且至少一个锚点仍
`QUALIFIED` 时，才可输出 `BASE_NOT_COMPARABLE`。

现有测试只覆盖了“base 合格、无合格锚点”，没有覆盖“base 不合格、无合格锚点”，因此 40/40 仍会通过。

## 要求的窄整改

1. 让正式三态逻辑先确认至少一个 C1/C3 锚点 `QUALIFIED`；无合格锚点时，无论 base 是
   `QUALIFIED`、`NOT_QUALIFIED` 还是 `INCONCLUSIVE`，任务终态均不得宣称已建立可比较结论，应返回有明确原因的
   `INCONCLUSIVE`。base `NOT_QUALIFIED` 且存在合格锚点时继续返回 `BASE_NOT_COMPARABLE`。
2. 增加聚焦回归，至少覆盖 base/C1/C3 同为 `NOT_QUALIFIED` 的组合；保留现有 base 失败但锚点合格的
   `BASE_NOT_COMPARABLE` 覆盖。
3. 运行受影响的轻量 unittest、compileall 与 `git diff --check`，并从 v5 manifest/raw 重新聚合一次，确认 v5
   observations/result 仍与归档完全一致。

## 代用户作出的执行决定

本 finding 不改变 v5 实际走过的分支、模型输出、对象结论或服务证据。整改后只要当前 v5 的机械重建仍与归档逐对象、逐结果一致，就保留 v5
作为唯一正式真实模型轮；不要求重新运行真实模型、Cargo 或 Docker，也不新建额外审计设施。若整改意外改变 v5 对象结论、归档结果或正式证据身份，再按事实扩大验证。

## 本轮验证

- Plan 068 qualification/service runner 与 Plan 071 comparability unittest：40/40 通过。
- 从 v5 manifest/raw 重建 observations：与 raw 和 archive 完全一致。
- 用当前 evaluator 重建 v5 result：与 archive 完全一致。
- 复核摘要哈希：freeze canonical
  `02fbb85d9eb3c76a6761fd86b495d46a01720e13ced4fbac0b74e3cd8e831616`、manifest file
  `9706d10142d0c4e92396e710d0e308772c27d361f96728f5d449164d31da6eb0`、observations canonical
  `46d7b4bfc725f61d66d2ca20030b7409f124467020b8201eec114c4cd93eb6ac`、result file
  `66d12dff77995f23927b62d7c181d8eb993511a3a832641b88e9296535a4e20e`，均与执行汇报一致。
- `git diff --check` 通过；未运行真实模型、Cargo、Docker、HF 下载或外部服务。
