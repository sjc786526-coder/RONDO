# Plan 041 正式 Local M4 盲评与人判收口（2026-08-16）

## 结果

- **人判结论：保留为实验**（`keep_as_experiment`）。由用户作出，只作记录；未改动生产默认、provider、
  launcher 或部署开关。tracked body-free 结论锁 `eval/locks/local-approval-m4-formal-review-v1.json`
  （SHA-256 `4e27d06a…1d89`）。
- **synthetic 主体 130 条**：直接消费 Plan 037 已验真的 390 行（`0e8fbbc7…00aa`），未重跑 130×2 推理、
  未重新调用 Sol。两批各 65 条，冻结 v1 裁判合同。未微调侧教师一致 104/130（80.0%）、相对 Opus 误拦 26；
  微调侧 130/130、误拦 0；两侧漏放 0、结构化输出 130/130 成功；理由判“弱”29 → 5，未被偏好 29 → 5。
- **真实 holdout 16 条**：按冻结 manifest 严格重验后物化（重算 manifest/outbound/prepare-receipt 并要求
  逐字节一致 + 复跑 Plan 032 verifier），数量与冻结声明一致，未增删抽样。两种 Local 用与 Plan 037 逐字节
  相同的 pair receipt（`1d57def1…129c`）串行完成 16×2。未微调侧 14/16 合规（2 次结构化输出失败）、
  有效判定内教师一致 8/14、误拦 6；微调侧 16/16 合规、教师一致 15/16、误拦 1；漏放均 0。
- 两分区从不合并分母，各有独立 cohort、seed、mapping、结果与 aggregate。

## 疑难问题与现场窄修

1. **holdout 出现既有失败终态，冻结 v1 包无法表达**。未微调侧 2 条结构化输出失败，v1 judge package 每条
   只能装三个 decision。按硬约束暂停并请示，用户现场授权新增 **holdout 专用** terminal-carrying v2 裁判
   prompt/result/summary 三件套，用于完整表达 16/16。冻结 v1 未修改，synthetic 全程用 v1；无判定候选记为
   `no_decision`/`not_applicable`，禁止进入偏好，也不当作隐含 deny；导入器要求每条评价与包内实际终态一致。
2. **Plan 032 已无法重新推导**：Plan 033 后写入 `runs.jsonl` 的 4 条 shadow 行（24 任务或 `tasks=null`）
   被 `_load_ledger_tasks` 当成 Guardian 证据运行而 fail-closed。窄修为只索引绑定自身 run 工件目录且带
   Guardian identity 的行，其余仍保持严格单任务要求；补了三项 ledger 回归。
3. **holdout 私有 batch id 会经 cohort id 泄漏进裁判包**：`cohort_id` 原为 `m4-holdout-<batch_id>`，而
   Sol 侧 run contract 的 `source_dataset_batch_id` 正是该 id，marker 扫描因此必然命中。改为按 batch id
   摘要派生 cohort id；补了断言 batch id 不出现在包内的回归。
4. **匿名扫描把普通英语 `local` 当作 side 泄漏**：真实语料里出现 "local git history"、"the local label"、
   "local merge" 等 63 处小写用法。原实现是“安全名词白名单”，每换一批语料就会误报。改为只在 `local` 直接
   命名 side（`local-static`/`local model`/`local ft` 等）或写成专有名词大写 `Local` 时判定泄漏；两个语料
   共 63 处小写用法、0 处大写，既有真阳性用例仍全部拦截。
5. **`python -m` 双重导入导致类身份不匹配**：CLI 以 `__main__` 载入 `cross_eval`，而 `holdout_anchor`
   按包名载入，返回的 `CohortBundle` 过不了 isinstance 门。按 Plan 037 对 `FormalL6PairEvidence` 的既有
   先例，在已验证后重新包装当前模块类；补了对应回归。
6. **自造 bug**：`run_formal_pair_bundle` 最后的正式重导入没有把 bundle 透传，holdout 运行完 32 条真实
   终态后被拿去和 synthetic cohort 比对而失败。32 个终态已由 journal 持久化，窄修后 resume 未再加载模型、
   未产生新推理即完成导入；补了“holdout 运行必须按私有 cohort 重验”的回归。

## 裁判执行

- 裁判为经 Claude Code 订阅入口、人在场的 `claude-opus-5`（2026-08-16，时点判定，不宣称可复现）。
- 裁判阶段只读取冻结 prompt/schema、judge request 与匿名包；未读 blinding seed、mapping、三方原始输出或
  模型身份材料。诚实记录一处已知瑕疵：打包前为确认终态分布，曾看到过按 side 汇总的 allow/deny 边际计数
  （不含任何逐条映射）；候选字母按私有 seed 逐条轮换，故不足以反推任一条的身份。
- 外发前做了敏感内容扫描：无凭据、密钥、私钥、公网 IP 或个人路径；命中的邮箱/URL 均为 Terminal-Bench
  公开任务素材与样板值，无需暂停。
- 盲评顺带发现：130 条 synthetic 中有 10 条冻结 Sol 目标的理由断言了证据中不存在的具体事实
  （如“校验和不匹配”、“dry-run 报告”），其结论仍被判成立。

## 结论的两处证据缺口（写入 WBS 与结论锁）

- validation 与 470 条训练数据同源，且每条证据几乎逐字写明判定线索，因此 synthetic 的高一致率很大程度是
  线索匹配而非通用审批判断。
- holdout 的教师标签与裁判独立判断**全部为 allow**，该锚点只能检出误拦与可用性问题，**无法检验过度放行**。

## 验收结果

- focused unittest **253/253 通过**（`test_local_m4_cross_eval`、`test_local_m4_holdout_anchor`、
  `test_l6_paired_outputs`、`test_l6_b10333_pair`、`test_teacher_labels`、`test_shadow_replay`、
  `test_local_approval`）。未跑全量 eval、Cargo、Docker，无 CI/PR。
- 本地模型阶段持共享重型锁 `/run/user/1000/rondo-cargo-build.lock` 串行运行；运行后 llama-server 进程消失、
  端口 18041 关闭、GPU 显存回落至 1,455 MiB 基线，Windows `C:` 实际余量全程在门禁之上（终值约 187 GiB）。
- 私有产物在主工作区 `eval-data/cross-eval/20260816-cross-eval-01-synthetic/` 与 `…-02-holdout/`，
  目录 0700、普通文件 0600，未进入 Git；未进入或修改 040 worktree。
