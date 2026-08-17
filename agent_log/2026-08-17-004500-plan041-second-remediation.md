# Plan 041 第二轮窄修（2026-08-17）

针对 `agent_log/2026-08-17-000121-plan041-remediation-reverification.md` 的两项剩余整改。两项均已复核确认存在，
已窄修并复验。未重判、未重跑本地模型、未修改冻结 Sol 标签，`keep_as_experiment` 决定与 146 条既有判定不变。

## 1. 匿名规则仍放过 `the untuned baseline`（确认存在，已修）

- 复核确认：`the untuned baseline`、`the untuned model`、`an untuned variant`、`the un-tuned side` 在上一轮规则下
  全部返回 `False`。上一轮我只把 `fine` 写成可选前缀之外的必需部分，`untuned` 因此落在规则之外。
- 修法：把 `(?:un[-_\s]?)?fine[-_\s]?tuned` 收紧为 `(?:un[-_\s]?)?(?:fine[-_\s]?)?tuned`，一处改动同时覆盖
  `untuned` / `un-tuned` / `tuned` 三种写法；仍要求后接侧名词，因此 `a fine-tuned configuration`、
  `The command tuned the retry interval in a config file.` 等普通用法继续不误报。
- 比审查建议多覆盖了裸 `tuned + 侧名词`（如 `the tuned model`）。理由：该规则本就要求后接 model/baseline/
  variant/side/candidate 等侧名词，在审批理由语境中这种组合只可能指代模型侧；成本为一个字符，且失败方向是 fail-closed。
- 复验：新增 2 条真阳性回归（`the untuned baseline`、`An untuned model would be stricter here.`），
  既有真阴性全部保留。正式产物按生产口径（只扫候选终态/判定）与整体口径重扫，**均为 0 命中**，
  现有 146 条判定不受影响，**无需重判**。

## 2. 顶层 WBS 仍缺 main 的 Multi M-2 里程碑行（确认存在，已修）

- 复核确认：main 的里程碑表有 `| Multi M-2 | Root 选择性路由 Event，… | 工程验收 | 已完成并合入 main |`，
  041 缺该行。上一轮我按 diff 前 50 行逐条同步 Multi 文本，该行在更靠后的 hunk 中被漏掉。
- 修法：从 `main:doc/WBS.md` 逐字取该行，插入 `Multi M-1` 与 `Multi M-5` 之间（与 main 顺序一致）。
- 复验：`doc/WBS.md` 中所有以 `| Multi` 开头的行现与 main **逐字一致**（diff 无输出）。

## 3. 差异范围描述不准确（确认存在，已修）

- 上一轮我已在整改日志中把差异说明改准确，但**遗漏了 plan 中的同一句**，plan 仍写着“仅余抬头与末尾两处
  append/append 差异”。
- 修法：plan 现如实写明——全部 Multi 内容（含里程碑行）与 main 逐字一致；与 main 的差异只剩
  `doc/WBS.md` 的四处 Local 状态区（抬头行、方向 2 行、3b 工作包段、方向表第 2 行）和
  `doc/WBS-COMPLETED.md` 末尾的 append/append，每处本分支都是更新后的事实。
- 已冻结的两份独立审查/复验报告未改写。

## 复验门禁

- focused unittest **253/253 通过**（同一 7 个模块）；`git diff --check` 通过。
- frozen v1 裁判模板、`eval/results/runs.jsonl`、`mydev/`、`multidev/`、`training/` 未修改；ignored 私有数据未跟踪。
- 结论锁 `eval/locks/local-approval-m4-formal-review-v1.json` 字节未变，仍为 `4e27d06a…1d89`；
  本轮未触碰计数、prompt/schema 身份、私有工件哈希或决定。
- 未运行全量 eval、Cargo、Docker、本地模型或付费测评；未进入其他 worktree；main 未改动。
