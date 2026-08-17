# Plan 041 独立审查整改（2026-08-17）

针对 `agent_log/2026-08-16-234043-plan041-independent-acceptance-review.md` 的三项必须整改。三项均已复核确认
存在，已窄修并复验。未重判、未重跑本地模型、未修改冻结 Sol 标签、未改变 `keep_as_experiment` 决定。

## 1. 顶层权威文档未吸收 Multi M-2（确认存在，已修）

- 复核结果属实：抬头已写 M-2 完成、M-3 下一阶段，但第 28、82—83、108、183 行仍写“M-2 待实施”，
  自相矛盾；第 190 行的 Local M4 里程碑还写着“未完成”。原因是我当时为规避合并冲突刻意不碰 Multi 行，
  却又改了抬头，反而制造了内部矛盾。
- 修法：把 `doc/WBS.md` 的 Multi 行逐字换成 main 当前文本（M-0—M-2 已完成、下一阶段 M-3、M-3—M-5 三个阶段），
  把 main 追加的 `## Multi M-2：选择性路由（Plan 039）` 整段按原字节插入 `doc/WBS-COMPLETED.md`，
  放在本任务 M4 段落之前；再补上 Local M4 里程碑行的完成状态。
- 复验：`doc/WBS.md` 已无“M-2 待实施 / 下一阶段是 M-2”残留；`doc/WBS-COMPLETED.md` 现为
  `base + main 的 M-2 段（逐字节一致）+ 本任务 M4 段`。
- 与 main 的三方合并现已**不再有任何 Multi 行冲突**——Multi 段落两侧逐字节相同。剩余冲突区只有两类，
  且每一处的“ours”都是本任务的新事实、“theirs”都是 M4 之前的旧文本，取本分支即正确：
  1. `doc/WBS.md` 四处 Local 状态区（抬头行、方向 2 行、3b 工作包段、方向表第 2 行）。抬头行本分支同时
     写明 M-2 已合入、下一阶段 M-3 与 Local M4 收口，是 main 抬头的超集。
  2. `doc/WBS-COMPLETED.md` 文件末尾的 append/append：本分支为 `base + main 的 M-2 段（逐字节一致）+
     本任务 M4 段`，两分支在同一锚点各自追加，属固有情形。
  因交付边界禁止在本分支执行 `git merge`，未以合并提交方式消除这些区域。

## 2. 匿名扫描漏掉直接身份措辞（确认存在，已修）

- 复核确认 `the local decision`、`the fine-tuned model`、`the unfine-tuned baseline`、
  `unlike the finetuned variant` 均能通过旧规则。
- 修法：`local` 名词表补 decision/judgment/verdict/assessment/rationale 等；新增
  `(un)fine-tuned + 侧名词` 规则（保留 `a fine-tuned configuration` 这类普通用法）。
- 顺带修掉一个新引入的误报源：真实 Guardian policy 含 `Local-vs-prod note:`，会被“大写 Local”规则命中。
  现把大写 `Local` 后紧跟连字符加小写词的复合词排除；`Local-static` 这类侧名仍由不区分大小写的侧名词规则拦截。
- 复验：正式产物按**生产口径**（只扫候选终态/判定）重扫，四个 package 均 **0 命中**，与审查结论一致，
  **无需重判**；四份 judge result 整体扫描也是 0 命中，即收紧后的规则不会追溯否定已记录结果。
  另把整包整体扫描的 2 处命中定位为 `Local-vs-prod note:`，位于三侧共享的 approval input，
  不可能区分候选身份，且不在生产扫描范围内。
- 回归：既有 side-leak 用例扩充为 10 条真阳性与 7 条真阴性（含真实 policy 措辞）。

## 3. “每一项指标都改善”表述失真（确认存在，已修）

- 复核计数：synthetic 漏放 0 → 0、结构化可用性 130/130 → 130/130 均为持平；`sole_preferred` 5 → 0 为下降
  （一致度提高把这些样本移入并列）；holdout 漏放同为 0 → 0。概括表述确实过强。
- 修法：`doc/WBS.md` 方向 2 行与结论锁 `decision.rationale` 改为准确分项——明确列出教师/裁判一致、误拦、
  理由质量与 holdout 结构化可用性的改善幅度，并同时写明持平项与 `sole_preferred` 的下降；
  另在锁的 `limitations` 增加两条（漏放为 0 是“本队列无证据”而非安全性证明；偏好计数须合并解读）。
- 结论锁重发布后 SHA-256 由 `2c8af519…cd3e` 变为 `4e27d06a…1d89`，`doc/WBS-COMPLETED.md`、
  本任务执行日志与 plan 状态中的引用已同步。审查报告本身作为日期冻结的历史证据未改动，其中记录的旧哈希
  仍对应审查时点的 `8fe4e71`。

## 验收结果

- focused unittest **253/253 通过**（同一 7 个模块）。`git diff --check` 通过。
- 未运行全量 eval、Cargo、Docker、本地模型或付费测评；未进入其他 worktree；main 未改动。
- 私有目录与文件权限、进程/端口/显存现场与上一轮一致，本轮未加载模型。
