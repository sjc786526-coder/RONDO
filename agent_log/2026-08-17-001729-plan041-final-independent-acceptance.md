# Plan 041 最终独立验收（2026-08-17）

## 结论

- **验收通过，任务目标完成。** 提交 `9fb340d` 已关闭第二轮两项剩余发现；正式 Local M4 的输入、盲评、
  holdout anchor、解盲聚合、结果锁和用户决定均保持有效。
- 本次只做代码/文档静态复核、正式私有工件的 body-free 哈希/命中计数检查和同一 focused Python 门禁；
  未重判、未重打包、未重跑模型、Cargo、Docker、全量 eval 或付费测评。
- 验收基线：041 `9fb340d681dcec927ec5d45f430115e3f687b8c4`；main 与 origin/main 均为
  `7050121a7998d2b3b444dfd45641ba23135be22a`。041 未合并、未推送。

## 整改闭合

1. **匿名规则闭合。** `untuned`、`un-tuned`、`tuned`、`fine-tuned`、`unfine-tuned` 后接明确 side noun
   均被拒绝；`fine-tuned configuration`、`command tuned the retry interval`、`Local-vs-prod note` 和普通
   小写 `local` 技术英语仍通过。多覆盖裸 `tuned + side noun` 是合理的 fail-closed 窄化，因为规则仍要求
   model/baseline/variant/side/candidate 等直接身份名词，不把普通动词用法扩大为真阳性。
2. **现有裁判结果不受影响。** 四个正式 judge package 在候选终态生产范围与全对象范围均 0 文件命中；四份
   judge result 全对象同样 0 文件命中。146 条既有判定无需重判。
3. **Multi 文档状态闭合。** `doc/WBS.md` 所有 `| Multi` 行与 main 逐字一致，遗漏的 Multi M-2 里程碑已补回；
   `doc/WBS-COMPLETED.md` 的 Multi M-2 完成段与 main 字节一致。实际 merge-tree 的冲突只涉及四处 Local
   新状态和完成历史末尾追加，均应保留本分支的新事实，Multi 上下文无冲突。
4. **结果锁无漂移。** `eval/locks/local-approval-m4-formal-review-v1.json` 仍为
   `4e27d06a…1d89`；14 项列名私有工件现值全部与锁一致，计数、partition、prompt/schema、决定均未改变。

## 验收门禁

- 直接相关 7 个 unittest 模块 **253/253 通过**；`git diff --check` 通过。
- frozen v1 模板、`eval/results/runs.jsonl`、`mydev/`、`multidev/`、`training/` 均未修改，ignored 私有数据
  未进入 Git。
- 当前无 `llama-server`、端口 18041 无监听、无 GPU compute process；Windows `C:` 实际余量约 189.1 GiB。
- 一处非阻断措辞澄清：plan 所称“与 main 的差异只剩四处 Local 状态区和末尾追加”实际描述的是**三方合并冲突**；
  分支相对 main 还按预期新增 P3/Local M4 完成行，但这些可自动合并且内容正确。该歧义不影响实现、合并结果或交接，
  本报告作出准确限定，不再要求第三轮整改。

## 代用户作出的最终决定

1. **维持 `keep_as_experiment`。** 不改为采用或停止，不切换生产默认、provider、launcher，不开展部署。
2. **接受 holdout-only terminal-carrying v2 与现有 146 条 Opus 5 时点判定。** 不重判、不重跑模型、不修改
   冻结 Sol 标签；继续保留同生成器 synthetic、全 allow holdout 和订阅模型不可完全复现等限制。
3. **不再追加审计或重型验收。** 当前证据已足以证明 Plan 041 按合同正确完成；后续真实使用或生产启用必须另行立项，
   不属于本任务。

## 当前状态

- **验收：通过。**
- **任务目标：完成。** Local M4 正式结果和人工决定均已形成并通过独立验收。
- 041 可等待用户批准后再合并 main、推送 origin/main 和归档本地分支；本次验收提交本身不执行这些动作。
