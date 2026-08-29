# Plan 098 正式判定与 pair selector 窄整改最终复验

日期：2026-08-28
审查身份：Plan 098 独立审查者
审查对象：`0997f878a14aff2bc14fe0aa0d70ebd06fdd544d`
结论：`FINAL_REVIEW_NOT_ACCEPTED / ONE_MEDIUM_REMEDIATION_REQUIRED`

## 验收摘要

任务规划者提出的两个 Medium 已按目标闭合：旧 raw argmax 已被版本化 formal projection 限定为
zero-margin diagnostic / historical reference，正式四类 call path 唯一指向带 frozen decision config 的
decision v1 decoder；validation selector 也已真实消费 v10 validation candidates 与 pairs，以全部 Boundary 和
soft-only pair 闭合作为原单一 bounded grid 的 hard eligibility，并把 pair bytes SHA、行数和逐 pair 报告冻结进
config。未发现数据正文、v8/v9 历史资产或封存边界回归。

本轮仍不接受最终完成态。独立实现审查发现 1 项 Medium：正式 decision implementation identity 没有覆盖 decoder
实际执行的 accepted-task runtime 依赖。该问题可窄修，不要求重做数据、盲审或建立通用可信设施。

## Finding

### Medium：frozen decision config 未绑定正式 decoder 的实际 task runtime 依赖

`qualification.py` 的正式 decoder 和 selector 直接从 `successor_task.py` 使用 hard dimensions、class order、
structured-output validator、label validator、typed verdict 与 pair evaluator。当前 decision implementation lock 只绑定
decision contract、`qualification.py`、config projection、formal projection 和 metrics projection；它既不绑定
`successor_task.py`，也不在运行时核对 formal projection 所声明的旧 output schema SHA 与实际
`successor-output-schema-v1.json` 字节。

因此，在 frozen config 形成后，如果 `successor_task.py` 的类别顺序、结构校验、gate 或 pair 语义漂移，或者 raw output
schema 漂移，`validate_decision_config` 仍可能接受旧 config，但正式解码/选择语义已经改变。这与“config 绑定正式 decoder
implementation，语义漂移后 fail-closed”的现行合同不一致。问题是正式判定正确性和冻结 operating point 的直接依赖缺口，
不是要求递归建设通用依赖审计。

## 必要窄整改

- 优先复用现有 accepted-task implementation identity，在 decision config 校验和正式 decode 前核对其既有 bundle；也可把
  `successor_task.py` 与 `successor-output-schema-v1.json` 作为明确的两个直接语义依赖纳入 decision component list。
- 补一项 focused 回归：分别漂移 task runtime / raw output schema 后，旧 decision config 必须在正式解码前 fail-closed。
- 按既有生成方式更新受影响的 decision identity、directional design/config 和 v10/qualification release identity；只跑相关
  Python 门及必要的 release 字节复现。
- 不修改 accepted v2/v9 文件字节，不改变五头标签、margin、loss、pair 语义或数据正文；不重做模块生成、盲审或资格集合。

## 独立验证

- focused：directional data、qualification、successor contract，`28/28` passed。
- 相关回归：successor release 与旧 contract/training-data/identity/v7，合计 `76/76` passed。
- `git diff --check 8e194e8f..0997f878` 通过；工作树在审查写入前 clean。
- 独立只读核对确认 12 个真实 validation pairs 均进入报告；破坏 Boundary target/non-target 或 soft-only endpoint 均
  fail-closed。
- 未读取 v9 test、旧 unseen 或 qualification sealed 正文；未运行真实模型、GPU、Docker、付费 API 或产品动作。

## 代用户作出的范围内决定

- 接受新增版本化 formal projection 作为保持 v9 历史 identity 的兼容方案，不要求改写旧 raw schema/helper。
- 接受“全部 validation pairs 闭合后再进入原确定性排序”的轻量策略，不扩大 threshold 路线搜索。
- 本轮只闭合上述两个直接 runtime/schema 依赖；不要求建立递归依赖图、签名、通用审计或可信平台。
- 工作包三继续锁定。ignored Plan 098 namespace 在最终复验前继续保留，不在本轮清理。

## 状态

- 验收：不通过。
- 任务目标：失败（主体与原两项整改正确，但 frozen formal decision identity 尚未语义闭合）。
- 下一步：执行者完成上述窄修、提交并重新申请最终复验。
