# Plan 022 修复提交独立复验报告

复验时间：2026-08-14（America/Los_Angeles）

复验对象：`worktree-023-rondo-multi-bootstrap@c5eb380148ffbc0b838a24031d07ee31e99a79a6`

修复基线：`d2c16073beb94b45f2bacceb8b0fbae41ad65204`

计划基线：`66116831becaf4adfa3dd28396e07441617fe1d1`

外部边界：未运行 Cargo、Docker、真实 no-API 双侧、真实 API、模型或付费测评；未合并、未推送、未清理 ignored 现场。

## 验收结论

**不通过，拒绝合并。**

`c5eb380` 已修通上一轮 B1、B2、B3 的正常输入链：新旧 manifest 能进入生产 loader，campaign 正常 request、
manifest、RunSpec 与结果链携带产品，Multi no-API CLI 也不再固定绑定 Local bundle。上一轮指出的事实问题不是
“完全未修”。

但持久化和异常路径仍未满足 Plan 022 硬约束 7、8：campaign 产品字段在 publication 边界仍可缺失，失败
publication 的私有归档没有产品摘要，终态 aggregate 恢复可以跳过全部结果行校验；另外 campaign consumer、
replay 与 shadow 仍有产品合同漏检。现有测试覆盖正常投影和若干单字段篡改，却未覆盖字段整组缺失、同步伪造及
终态恢复捷径。

## 阻断项

### B1. campaign publication 可以先落盘一条缺失 campaign 产品绑定的记录

严重度：**BLOCKER**

- `eval/rondo_eval/terminal_bench/pair.py:903-945` 把 `CampaignPublicationContext.campaign_product` 定义为
  可选字段且默认 `None`。
- `eval/rondo_eval/terminal_bench/results.py:1070-1089` 只在该字段非空时核对产品；
  `results.py:1131-1155` 也只在非空时投影到结果。
- `eval/rondo_eval/artifacts.py:440-464` 对 campaign 绑定采用同样的可选语义：带顶层 `product` 的行可以完全
  缺少 `campaign_product`；没有顶层产品的任意 side 又可以携带任意合法 `campaign_product`。
- 正常 `baseline_cli.py:2363-2375` 确实传入了 v7 identity 的产品，但这只保证当前调用点不犯错，不能代替
  publication/durable 合同。后续 `_result_record_sha256()` 或 `_campaign_records()` 才拒绝时，
  `ArtifactWriter.finalize()` 已经把错误行和私有目录持久化，拒绝发生得太晚。

审查者用现有真实 synthetic producer 复现 Multi campaign publication：

```text
publisher_missing_campaign_product=ACCEPTED
top=rondo-multi
record_campaign=None
summary_campaign=None
```

另用一条完整历史 TB 行仅增加 `config.campaign_product="rondo-multi"`，同时保持顶层 `product` 缺失，完整
`_validate_record()` 仍接受：

```text
full_tracked_validator_missing_product=ACCEPTED
```

必须修复：让 publication context 明确携带足以区分历史 campaign 与当前 v7 的身份；v7 两侧都必须绑定
campaign product，RONDO 侧还必须与 RunSpec/binary/record product 相等，Codex 侧不得获得顶层产品。
校验必须在任何 `ArtifactWriter.finalize()` 前完成。generic reader 对无顶层产品的 `campaign_product` 不能继续
无条件放行；至少只允许符合历史读取合同的精确形状和 v7 Codex 形状。

### B2. Multi 异常 publication 的私有归档没有产品身份摘要

严重度：**BLOCKER**

`publish_terminal_bench_failure()` 会让 tracked row 正确携带 `product`、`binary_product` 和
`auto_review_config`，但 `eval/rondo_eval/terminal_bench/results.py:694-705` 写出的 `run-failure.json`
只有 schema、run ID、outcome、failure stage 与诊断；异常路径不写 `run-summary.json`，私有目录内没有任何文件
记录 product/config/auto-review。

复用仓库现有失败 producer 的实际探针：

```text
failure_private_files=api-metadata-unavailable.json,run-failure.json
run_summary_exists=False
```

这直接违反硬约束 7 的“运行记录和私有归档摘要必须一致，缺失也 fail-closed”。同时，
`results.py:1110-1114` 声称正常与失败归档共用 `_product_config()`，与实际文件路径不符。

必须修复：异常 publication 也写经过严格 schema 校验的私有摘要，并让其 product/config/auto-review 与 tracked row
来自同一投影；或者把 `run-failure.json` 升级为明确的私有摘要合同并增加等值校验。正向、失败和 journal recovery
都要覆盖 Local、Multi、Codex。

### B3. 已存在的终态 aggregate 可绕过 runs index 与 result digest 校验

严重度：**BLOCKER**

- `_recover_terminal_aggregate()` 在 `baseline_cli.py:689-696` 看到
  `_restore_tracked_aggregate_from_local()` 返回 `restored=True` 后立即按终态退出。
- `_restore_tracked_aggregate_from_local()`（`baseline_cli.py:2713-2758`）在 private/tracked aggregate 都存在时，
  只核对 campaign ID、lock、status、product，以及两份 aggregate 自身字节一致；它不调用
  `_campaign_records()` / `_continuation_records()`，不核对 state、budget 或 `result_record_sha256` 指向的真实结果。
- 对抗探针构造 product 正确、但 `result_record_sha256` 指向不存在 run 且完全没有 `runs.jsonl` 的成对 aggregate，
  该恢复路径仍返回：

```text
restored=True
runs_index_exists=False
```

因此 aggregate 虽然表面写了 `rondo-multi`，却不能证明其汇总的记录、binary 与 campaign 也是 Multi，修复日志所称
“publication/replay/aggregate 逐层绑定”不成立。

必须修复：已有 aggregate 也必须从 terminal state、budget、runs index、continuation 和冻结 identity 重新构造
期望值后逐字节核对；不能因为 local/tracked 两份彼此相等就跳过来源校验。补无 index、缺 run、错误 digest、
Local/Multi 混绑四类恢复负向回归。

## 主要遗漏

### M1. campaign consumer 接受同步伪造的 Guardian / auto-review 配置

严重度：**MAJOR**

`artifacts.py:481-500` 对 Local 只证明 `auto_review_config` 与同一 record 内的 `guardian_model/guardian_effort`
自洽；`baseline_cli.py:2858-2916` 又没有把这些值与 campaign lock 的 `selected_profile` 比较。把三处一起改成相同
伪值即可绕过。

对抗探针使用完整 schema、正确 v7 slot、真实 manifest/binary/campaign/product，只同步篡改 Guardian model、effort
和 auto-review block，结果先通过生产 `_read_index()`，再被 `_campaign_records()` 接受：

```text
full_index_and_campaign_forged_guardian_auto=ACCEPTED
record_guardian=forged-guardian
frozen_guardian=gpt-5.6-sol
```

pair reconcile 已有 selected-profile 二次绑定；campaign reader 应采用同等级约束，并增加同步伪造负向测试。

### M2. replay 产品合同在 generic validator 中提前返回

严重度：**MAJOR**

`artifacts.py:465` 对所有非 TB 记录直接返回。因此 replay 行只需顶层与 `config.product` 相等，就可携带相反的
`binary_product`、非法版本或完全伪造的 `auto_review_config`；生产 `_read_index()` 接受，journal recovery 也会
正式发布。虽然 replay 当前随 E-A 挂起，但修复日志明确声称 replay durable consumer 已闭合，当前实现和声明不符。

应明确 replay 是否记录 binary/auto-review：若记录就严格等值校验；若不记录就拒绝这些字段，而不是忽略。

### M3. 当前 shadow side/product 映射未按数据布局收紧

严重度：**CONTRACT GAP**

`doc/eval-data-layout.md:219-232` 规定当前 `local-static` / `local-ft-static` 都是 `rondo-local`；未来 Multi shadow
需另行按 §3.1 明确身份。当前 `artifacts.py:450-465` 却允许两个 `local-*` side 声明 `rondo-multi`，随后因非 TB
提前返回，不要求 binary/auto-review。

实际最小探针：

```text
local_shadow_claims_multi=ACCEPTED
```

应先明确未来 Multi shadow 的 side 命名，再把当前 side/product 映射写成可测试的精确表；不能让 Local side
直接冒充 Multi。

## 文档与完成合同

### D1. WBS 仍有一处当前状态矛盾

`doc/WBS.md:143` 仍写 P5“产品基线已建立（工作包 2）”，与同文件 16、28、35-43、68、84 行的“实现待独立复审、
工作包 3 未启动”矛盾。复审未通过时应保持“实现待修复与复审”；最终通过但未合并时应写“复审通过、待合并”。

### C1. 完整 `git diff --check` 的窄例外仍待用户确认

Plan 022 §1 仍要求完整 `git diff --check` 通过。当前：

```text
git diff --check d2c16073..c5eb380        -> pass
git diff --check 6611683..c5eb380         -> rc=2
完整 Plan diff 唯一来源：multidev/ 精确复制
419 files / 6,479 locations / 12,707 output lines
```

Plan 决策 011 和修复日志已经诚实记录该例外及“待用户确认”，这比首版状态准确；但用户尚未明确接受，所以即使代码
问题全部关闭，也不能宣称完成标准已全部通过。技术上建议接受这项窄例外：清理这些空白会破坏更强的 Git blob
精确复制约束。接受范围只能是与 `mydev/` 对应 blob 完全相同的 `multidev/` 新增内容，手写差异继续必须全绿。

## 已确认通过

### 上一轮问题的正常路径修复

- B1 writer/loader：历史 Local、新 Local、Multi 与 Codex 四种 runtime manifest 形状均被严格处理；Codex 不再写
  `product:null`，未知字段、非法产品和显式 null 均拒绝。
- B2 正常 campaign 链：当前生产入口能把 v7 identity.product 投影到 RONDO request，Codex 保持无产品；
  manifest、RunSpec、preflight、正常 publication、continuation 与 aggregate 的正确输入路径均携带产品。
- B3 正常 no-API 链：Multi 从 `rondo-multi` namespace 读取 manifest，核对三份 runtime 文件摘要，request 与
  receipt 写 Multi；Local/Codex 继续使用历史 pair identity。Multi 目前只有 namespace + 自描述 manifest + 文件
  摘要合同，不等同于已冻结 bundle 的 provenance；在本任务明确“bundle 仍为空”的边界下不另列缺陷。
- Codex no-API safe summary 已省略 product 与 auto-review block。
- successor generator 拒绝把声明 Multi 的 successor 绑定到继承的 Local bundles。

### 审查者实际测试

使用本 worktree 源码和主仓库 ignored venv，最终定向集合：

```text
test_binary_freeze.py                  35/35
test_config_and_artifacts.py           31/31
test_fair_comparison.py                90/90
test_terminal_bench.py                 34/34
test_terminal_bench_baseline.py        50/50
test_terminal_bench_docker_smoke.py     9/9
test_terminal_bench_pair.py            10/10
test_terminal_bench_results.py         53/53
合计                                   312/312
```

首次运行 `test_fair_comparison` 时继承的代理变量把 3 个 loopback 请求转成 502；按仓库 no-API 规则清除大小写
HTTP/HTTPS/ALL_PROXY 并设置 `NO_PROXY=127.0.0.1,localhost` 后，该模块 90/90 通过。这是环境重跑，不计代码失败。

执行者在同一提交报告完整无 API eval 600/600、`just eval-lock` 85 packages、两侧 helper 各 9/9；本轮差量复审
没有重复这些已覆盖或未受修改的门禁。修复提交没有 Rust 产品源码改动，因此没有重复 20 GB Cargo 构建。

### Git、复制与现场

- `c5eb380` 的父提交精确为 `d2c16073`；26 个修复文件位于允许的 eval/tests/Plan/WBS/log 范围。
- 修复提交自身和排除 `multidev/**` 的全部手写差异通过 `git diff --check`。
- `mydev/` 与 `multidev/` 仍为 6,011/6,011 项逐条相同的 path/type/mode/blob 映射：5,951 个 `100644`、
  59 个 `100755`、1 个 symlink；六个排除残留未进入。
- worktree 与主工作区受跟踪状态在写本报告前均干净；`main == origin/main == d84632f`。
- ignored 现场仍是约 20 GB Multi target、两份 build metrics、约 32 KB uv cache 与五处 `__pycache__`；Local target
  不存在。未创建正式 identity、run/result、budget。

## 未运行

- 未重跑完整 600 项 eval（执行者已在同一提交运行，本轮用 312 项差量门禁复核）。
- 未运行 `just eval-lock`、watchdog helper（修复没有修改锁或脚本）。
- 未运行 Cargo、Docker、真实 no-API 双侧、真实 API、真实模型、付费测评或全 workspace。
- skip/未运行项不计为通过。

## 下一轮复审准入条件

1. 在落盘前关闭 B1，并覆盖 campaign product 整组缺失、Codex 正形及 journal recovery。
2. 让失败私有摘要与 tracked row 共用同一产品投影，关闭 B2。
3. 删除 aggregate 的无来源早退，按真实 state/budget/result digests 重建后核对，关闭 B3。
4. campaign consumer 绑定完整 selected profile；明确并收紧 replay、shadow 合同。
5. 修正 `doc/WBS.md:143`，同步 Plan/修复日志，不改写本报告。
6. 执行者重跑受影响 focused 与一次完整无 API eval；若仍不改 Rust，无需重复 Cargo。独立复审只需复跑新增负向
   回归和必要 focused，不扩大到 Docker/API/model。
7. 所有代码问题通过后，由用户明确接受或拒绝 Plan 决策 011 的精确复制窄例外；在此之前保持合同挂起。
