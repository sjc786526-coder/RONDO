# Plan 041 整改复验（2026-08-17）

## 结论

- **验收仍暂不通过。** 提交 `c92ad51` 已正确关闭上一轮三项发现的主体部分，正式 M4 结果和
  `keep_as_experiment` 决定继续有效；但匿名扫描仍漏一个同类直接身份短语，且顶层 WBS 同步仍少一行 main
  已有的 Multi M-2 里程碑，同时整改记录对实际差异范围有过度陈述。
- 两个剩余问题都是小而明确的代码/文档窄修，不影响既有 146 条盲评，不需要重判、重打包、重跑模型或扩大设施。
- 复验基线：041 `c92ad512b0b69fb36c4fd2e5c079b54a2b8eba1a`；main 与 origin/main 均为
  `7050121a7998d2b3b444dfd45641ba23135be22a`。041 未合并、未推送。

## 已闭合

1. **结果表述与结论锁已纠正。** “每一项指标都改善”已替换为准确分项，持平的漏放/结构化可用性和
   `sole_preferred` 5 → 0 均明确记录；决定仍为 `keep_as_experiment`。新结论锁实际 SHA-256 为
   `4e27d06a…1d89`，当前执行日志、plan 与完成历史引用一致；旧审查报告保留旧哈希作为时点证据是正确的。
2. **WBS 的主要 Multi 状态已恢复。** 当前方向、工作包和 P5 均已写 M-0—M-2 完成、M-3 为下一阶段；
   `doc/WBS-COMPLETED.md` 的 Multi M-2 完成段与 main 逐字节一致；Local M4 里程碑已改为完成。
3. **上轮列出的身份短语已拦截。** `the local decision`、`the fine-tuned model`、
   `the unfine-tuned baseline`、`the finetuned variant` 现在均返回命中；`Local-vs-prod note`、
   `fine-tuned configuration` 和普通小写 `local` 技术英语仍不误报。
4. **正式结果未被追溯否定。** 按生产口径重扫四个 judge package 的候选终态和四份 judge result，均为 0
   文件命中。结论锁只改 rationale/limitations，partition、计数、prompt/schema、私有工件哈希和决定未变。

## 仍须整改

1. **匿名规则仍放过 `the untuned baseline`。** 该短语直接指明未微调侧，但当前
   `_contains_forbidden_side_identity()` 返回 `False`。在现有 `(un)fine-tuned + side noun` 窄规则中补上
   `untuned + side noun` 并增加一条真阳性回归即可；继续保留现有真阴性，不扩建扫描设施。本次正式包无该命中，
   所以无需重判。
2. **Multi 文档同步仍未完全闭合。** 当前 041 的 `doc/WBS.md` 里程碑表缺少 main 已有的
   `Multi M-2 | Root 选择性路由 Event ... | 已完成并合入 main` 行。实际 merge-tree 会从 main 干净带回该行，
   说明它不是冲突，但当前工作树文档并未做到所声称的 Multi 行逐字同步。另有四处 Local 状态冲突和一处
   `WBS-COMPLETED` 末尾追加冲突，均可按本任务新事实解决；因此 plan 中“仅余抬头和末尾两处差异”的说法不准确。
   应复制 main 的 Multi M-2 里程碑行，并在 plan/后续整改日志中如实更正差异说明；不改写已冻结的独立审查报告。

## 复验门禁

- 直接相关 7 个 unittest 模块 **253/253 通过**；`git diff --check` 通过。
- frozen v1 模板、`runs.jsonl`、`mydev/`、`multidev/`、`training/` 和 ignored 私有数据均未修改或跟踪。
- 当前无 `llama-server`、端口 18041 无监听、无 GPU compute process，GPU 使用约 1628 MiB；Windows `C:`
  实际余量约 189.1 GiB。未运行全量 eval、Cargo、Docker、本地模型或付费测评。

## 代用户作出的复验决定

1. **继续维持 `keep_as_experiment`，不启用生产、不改变 provider/launcher/default，也不部署。**
2. **holdout-only v2 和 146 条现有判定继续有效；不重判、不重跑模型、不修改冻结 Sol 标签。**
3. **下一轮整改只限上述两点。** 补一条匿名模式及回归、补回 main 的 Multi M-2 里程碑并纠正文档说明，随后复跑
   同一 focused 门禁与 `git diff --check` 即可；不要求新增审计/可信设施或任何重型验证。

## 当前状态

- **验收：不通过（待第二轮窄修复验）。**
- **任务目标：完成。** 正式 M4 结果与人工决定已经实现且有效，当前仅是分支交付正确性尚未完全收口。
