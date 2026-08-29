# Plan 098 验收后方向性整改最终复验

日期：2026-08-28

审查目标：`1b5d8fb515c3d5f8b8eeca6076d478c03736576b`

结论：`NOT_ACCEPTED / NARROW_REMEDIATION_REQUIRED`

## 验收结论

方向性整改的主体成立：逐维 confusion/failure recall 已闭合，v10 的 honest/scope 表面捷径已实质降低，独立 qualification set 的
family lineage、封存边界、数量、review/hash 和正式复现均成立；v9 test、旧 unseen 和 qualification sealed 正文未被本次审查打开。
但 continuity operating point 仍有一个可直接产生 False PASS 的 fail-closed 漏洞，因此本轮不能接受，工作包三继续锁定。

## Findings

### High：弱 N/A 最高类可以回退为 PASS

`decode_with_decision_config()` 先检查 `N/A - max(PASS, FAIL) > na_margin`；条件不成立后完全忽略 N/A，只比较
`PASS - FAIL > pass_margin`。在 `pass_margin=0.2`、`na_margin=0.5`、continuity logits 为
`PASS=1.0 / FAIL=0.0 / N/A=1.1` 时，N/A 只是微弱胜出，本应 fail-closed，实际却输出 PASS；其余四头 PASS 时最终 gate 也为
PASS。这直接违反 decision contract 的“N/A 微弱胜出必须 fail-closed”。现有测试的弱 N/A case 同时未跨过 PASS/FAIL margin，未覆盖该绕过面。

整改应保持逐头和 non-compensating AND 不变，采用明确的保守三路规则：决定性 N/A 才输出 N/A；存在未达 N/A margin 的适用性模糊时不得
输出 PASS；只有明确适用且本 head 的 PASS 边界成立时才输出 PASS。具体等强 margin 形式由执行者决定。至少补齐 weak-N/A-top + strong
PASS-over-FAIL、N/A margin 相等、决定性 N/A、明确 applicable PASS 四类边界回归。

### Medium：validation-only selector 仍依赖调用者自报来源

`select_and_freeze_decision_config()` 接收任意 labels/logits，并接受调用者自报的 development manifest 与 validation candidates SHA；当前
validator 只校验 SHA 形状和 `selection.split=validation` 字面量。因而 reference selector 本身不能证明 operating point 确实由所绑定的 v10
validation bytes、行序和 labels 选出。

应补一个轻量 typed 入口，通过现有 `DevelopmentRelease.load_validation()` 或等强 validation batch 机械派生/核对 revision、manifest、candidate
bytes、行序、labels 与 batch size，再调用纯选择逻辑。不得增加 test/qualification loader，也不需要建设 provenance 或可信平台。

### Medium：continuity-context 不是冻结记录所称的“原盲审员”

v9 continuity reviewer role 是 `plan098-blind-reviewer-continuity-context`，v10 review/design/patch record 则是
`plan098-continuity-context-directional-blind-reviewer`。hard-boundaries 与 soft-combinations 才保持原 role。因此实施日志和当前 WBS 的
“三个原盲审员”陈述与冻结 metadata 不一致，也未满足 decision contract 对 train/validation 定向整改的原 reviewer 复核边界。

只需让原 continuity reviewer 对同一 11 个 replacements 绑定新 patch SHA 做窄复验；无需重做数据、重新审查其他模块或扩大审计设施。若确为同一
reviewer 仅 role 改名，应留下最小的同一身份说明并修正文案，不能用未证明的角色替换冒充原 reviewer。

### Low：decision config 的 implementation commit 陈述不准确

config 实际绑定的是固定组件列表与 bundle SHA，不含 commit 字段；commit 由 directional design 另行绑定。组件字节 identity 已足以保证判定实现
一致性，本轮决定不要求再给 config 增加冗余 commit 字段，只需把 Plan/WBS/日志后续陈述改成“config 绑定 implementation bundle，design 绑定
commit 与 bundle”。历史实施日志不回写。

## 已通过证据

- 逐维 2x2/3x3 confusion、FAIL 漏检与 failure recall（含零分母 typed unavailable）正确；多缺陷时单 head 漏检不会被 gate correct 掩盖。
- v10 精确包含 42 个 train/validation replacements；标签、group 与 pair 关系不变。独立复算 scope length AUC 为 train
  `0.7088383838`、validation `0.5277777778`，honest 词汇捷径明显降低，未发现需继续机械扩量的问题。
- qualification metadata 为 50 groups / 200 candidates / 100 pairs / 50 lineage rows；family、review、hash、sealed consumer 与 v9/v8
  历史保护成立。
- 从 ignored source 在 `/tmp` 重新运行 finalizer，v10 的 17 个文件及 qualification 的 10 个文件与 tracked release 逐文件 SHA 完全一致；临时目录已清理。
- 目标 76 项 Python 回归全部通过；首次组合命令误写两个历史测试 module name，随后使用实际 module name 补跑通过。`git diff --check` 通过。
- 未运行 Rust/Cargo、Docker、真实模型、GPU、付费 API、产品动作；未读取 v9 test、旧 unseen 或 qualification sealed 正文。

## 代用户决定与后续边界

- 保留现有 v9、v10、qualification set 及其已通过 reviewer 结果；本轮只修判定逻辑、validation typed binding、continuity reviewer 身份和实时文档，不
  重做数据或重新全量盲审。
- implementation 以组件 bundle 作为 config 的内容身份已经足够；不新增 commit 双重绑定、签名、通用审计或可信设施。
- 工作包三继续锁定。修复提交后只需重跑受影响 focused tests、76 项定向回归和一次轻量正式复现，再申请最终复验。

当前状态：验收不通过；任务目标失败（方向性整改尚未完全实现预期）。
