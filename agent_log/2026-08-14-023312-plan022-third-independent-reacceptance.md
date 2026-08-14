# Plan 022 第二轮修复独立复验报告

复验时间：2026-08-14（America/Los_Angeles）

复验对象：`worktree-023-rondo-multi-bootstrap@20b8e7874635b12e19a2c12ba4d3f9be1eb2d2de`

父提交：`c5eb380148ffbc0b838a24031d07ee31e99a79a6`

外部边界：未运行 Cargo、Docker、真实 no-API、真实 API、模型、付费测评或全 workspace；未合并、未推送、
未清理 ignored 现场。

## 验收结论

**不通过，暂不合并。**

`20b8e787` 已关闭上一轮大部分反例：v7 缺失 campaign product 会在 finalize 前拒绝；成功和失败 publication
都会写与 tracked row 等值的版本化 `run-summary.json`；journal recovery 能拒绝摘要篡改；aggregate 不再因
private/tracked 两份 aggregate 自洽而早退；state、budget、record digest、selected profile、replay 与当前 shadow
映射的既有反例均已关闭。

仍有两个直接属于 Plan 022 硬约束 7 的阻断缺口：publisher 只验证 context 自洽，没有在落盘前绑定冻结 campaign
lock 的真实产品；aggregate 使用的 campaign reader 又绕过新增的私有摘要校验。这两项都可用现有身份和 reader
收口，不需要新增审计设施。

## 阻断项

### B1. publication 没有把 context 声明的产品绑定到冻结 campaign identity

严重度：**BLOCKER**

- `eval/rondo_eval/terminal_bench/pair.py:903-959` 只验证 `CampaignPublicationContext` 内部的 schema/product
  字段是否同时存在，并不能证明这些字段来自 `campaign_lock_sha256` 对应的冻结 identity。
- `eval/rondo_eval/terminal_bench/results.py:1085-1110` 只把 context 的 product 与当前 RunSpec/binary 比较。
  Codex 侧的期望产品固定为 `None`，因此 context 声明 Local 或 Multi 都不会影响这项比较。
- 正常 `baseline_cli.py:2359-2376` 调用点会从真实 identity 正确构造 context，但 publisher 是最终落盘边界；
  只保证当前调用点诚实，不能阻止 context 与冻结 lock 同步分叉。后续 campaign consumer 虽会拒绝，错误 row 和
  私有目录已经 finalize。

独立探针使用真实 v7 Local identity 的 campaign ID 与 lock SHA，给 Codex publication 注入自洽但错误的 Multi
context，实际结果：

```text
codex_wrong_frozen_campaign_product=ACCEPTED
frozen_product=rondo-local
recorded_campaign_product=rondo-multi
target_exists=True
```

必须修复：publication 在任何 `ArtifactWriter.finalize()` 前接收并验证可信的 `CampaignIdentity` 或等价冻结身份，
至少交叉核对 campaign ID、lock SHA、schema、product、side 与 slot；不能只相信 context 自报。增加 Codex 与
RONDO 两侧“正确 lock + 错误 product”的负向回归。可复用现有 `CampaignIdentity` 校验，不建立新的身份系统。

### B2. aggregate 的 campaign durable reader 绕过私有摘要合同

严重度：**BLOCKER**

- 通用 durable reader `eval/rondo_eval/artifacts.py:868-900` 会依次运行完整 record 校验和
  `_validate_private_run_summary()`，能拒绝私有摘要缺失或与 tracked row 不等值。
- aggregate 使用的 `baseline_cli._campaign_records()`（`baseline_cli.py:2911-2942`）却直接解析 JSONL，
  只调用产品/冻结 profile 校验，不调用完整 record/private-summary reader。
- `_validate_terminal_result_sources()`（`baseline_cli.py:2668-2731`）只绑定 state、budget、record digest 与
  campaign/binary；`_campaign_usage()` 对 `metadata_ready=false` 的失败行允许没有 API metadata，因此也不会
  顺带证明私有目录或 `run-summary.json` 存在。

独立探针构造正确 v7 Local 产品、manifest、selected profile、slot、state digest 与失败预算记录；同一条 record
被通用摘要 validator 拒绝，却被 campaign reader 和 aggregate source validator 接受：

```text
generic_private_summary_validator=REJECTED private run summary differs from its tracked record
campaign_reader_same_record=ACCEPTED 1
campaign_sources_without_private_summary=ACCEPTED
```

另一独立探针在私有 artifact tree 完全不存在时也得到：

```text
aggregate_prewrite_missing_private_tree=ACCEPTED
artifact_exists=False
```

因此 terminal aggregate/recovery 仍能绕过 B2 新增的版本化私有摘要门，B2 与 B3 尚未真正闭环。

必须修复：让 campaign 的全部结果索引读取路径复用通用完整 record + private-summary validator，至少覆盖
`_campaign_records()`、continuation 和 terminal digest/recovery 使用的同类入口；补删除摘要、篡改摘要、删除整个
私有目录三类 aggregate recovery 负向测试。应复用一个共享 reader，不再堆叠平行校验函数。

## 次要遗漏

### M1. 数字 schema 与冻结 profile 比较仍接受 Python 布尔值

严重度：**MINOR（建议随上述窄修复一并关闭）**

- `artifacts.py:492-495`、`469`、`580` 使用与整数 `1` 的普通相等比较，Python 中 `True == 1`，所以
  `private_summary_schema_version`、私有摘要 schema 和 `auto_review_config.schema_version` 可用布尔值冒充。
- `baseline_cli.py:2980-2982` 对 selected profile 也只做普通相等比较，冻结的浮点 `1.0` 可被 JSON `true`
  冒充。实探针分别得到 `boolean_schema_versions=ACCEPTED` 与
  `selected_profile_bool_for_float=ACCEPTED`。

这是常见的 Python JSON 类型边界，直接加 bool 排除或复用现有 typed profile parser 即可；不需要扩大为新的 schema
或审计框架。本项本身不单独决定验收，但应避免下一轮继续留下同类严格性漏洞。

### D1. 非阻塞文档笔误

`doc/eval-data-layout.md:87` 的“`models-manager/models.json` 催化路径”应为“catalog 路径”或“目录”。不影响
当前能力和合同判断。

## 已确认闭合

- v7 Local/Multi/Codex publication 缺失 `campaign_product` 时均在 finalize 前拒绝。
- 成功与失败 publication 都写八键 `run-summary.json`；Local、Multi、Codex 的 config/summary/tasks 与 tracked
  row 等值。
- finalize、journal recovery 和通用 `_read_index()` 会校验新私有摘要；历史无 marker 行保持只读兼容。
- aggregate 已删除“private/tracked 两份自洽即返回”的早退；缺 runs index、缺结果、错误 digest、预算与 state
  漂移、冻结 selected profile 漂移和 Local/Multi 混绑均拒绝。
- replay 的 product/binary/auto-review 合同与当前 `local-static` / `local-ft-static` 仅 Local 映射已收紧。
- 当前历史 `runs.jsonl` 244/244 可由新通用 reader 读取，均未被回填 product。

## 审查者实际验证

定向运行四个直接受影响模块：

```text
test_config_and_artifacts
test_fair_comparison
test_terminal_bench_baseline
test_terminal_bench_results
合计：231/231，OK
```

代理变量已按 no-API 测试要求清除；无 skip。另运行了上述两个 synthetic/in-memory 反例，不调用 Docker、API 或
模型，也不写正式结果。

执行者报告同一提交的八模块 focused 319/319、完整无 API eval 607/607、`just eval-lock` 85 packages、两侧
watchdog helper 各 9/9；本轮未重复完整套件和未受本提交影响的门禁。

## Git、复制、文档与现场

- `20b8e787` 的父提交是 `c5eb380`；本提交修改 15 个允许范围内文件，未触碰 `mydev/`、`multidev/`、watchdog、
  lock、历史结果或秘密示例。
- 修复提交自身及从 Plan 基线排除 `multidev/**` 的全部手写差异通过 `git diff --check`。
- `mydev/` 与 `multidev/` 各 6,011 项，规范化后的 path/type/mode/blob 映射为空差异：5,951 个 `100644`、
  59 个 `100755`、1 个 symlink；六个排除残留未进入。
- watchdog 仍是保持 blob/mode 的 100% rename，现行入口使用根路径；历史 bundle 无法按旧 wrapper 路径
  re-verify 是已采纳决策 008 的明确代价。
- WBS、子 WBS、Plan 与执行日志准确保持“第二轮修复、待独立复审、工作包 3 未启动”；
  `WBS-COMPLETED` 保留未通过批次历史是正确的。
- worktree 与主工作区受跟踪状态均干净；`main == origin/main == d84632f`。ignored 现场与执行日志一致，未清理。
- 文档把 `eval-data/bin/rondo-multi/` 口语化写作“为空”，现场实际是目录不存在；两者表达的“尚无 Multi bundle”
  事实一致，不构成能力误报。

## 决策 011 建议

**建议用户接受严格窄例外。**

完整 Plan diff 的 `git diff --check` 为 `rc=2`，只来自 `multidev/` 中与 `mydev/` 精确相同的 419 个文件、
6,479 个位置、12,707 行诊断；目录外诊断为零。清理这些上游原始尾空格会破坏更强的精确复制合同，用
`.gitattributes` 隐藏诊断也只会扩大范围。

建议授权把 Plan §1 的完成标准改成：

> 所有非 `multidev/**` 手写差异必须通过 `git diff --check`；`multidev/` 的复制内容以相对 path、Git type/mode、
> blob ID 和工作树字节逐项等同 `mydev/` 为门禁。仅满足该可复算等同条件的复制内容获得例外。

随后把决策 011 标为“已采纳”。不得修改复制文件来消除尾空格，也不应增加 `.gitattributes` 掩盖诊断。

本决定只关闭复制合同冲突，不豁免 B1/B2；代码阻断项修复并复验通过前仍不得合并。

## 下一轮最小复审准入

1. publication 在 finalize 前绑定真实 `CampaignIdentity`，补错误 lock/product 组合负测。
2. aggregate/campaign 结果读取复用完整 private-summary reader，补删除/篡改摘要和目录负测。
3. 顺手拒绝 bool 冒充 schema/profile 数字并修正文档笔误。
4. 执行者运行新增负测、上述四模块与一次完整无 API eval；未改 Rust 时仍无需 Cargo，独立复审无需扩大到
   Docker/API/model。
5. 不改写本报告；新增修复日志。复验通过后，再同步 WBS 为“复审通过、待合并”并向
   `doc/WBS-COMPLETED.md` 收口最终完成证据。
