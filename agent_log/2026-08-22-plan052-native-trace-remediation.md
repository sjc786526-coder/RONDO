# Plan 052 原生 trace 观测链整改

## 结果

- 删除首版 `--rondo-local-observation` 及 `codex-exec` 专用 collector；最终分支相对规划基线不含 `codex-exec`
  产品改动。
- 复用原生 rollout trace、API metadata、Team Lens 严格 reader/reducer 与 Terminal-Bench 发布链。新增明确的
  `local_harness_measurement_request` campaign projector；普通历史 campaign、Codex 和 RONDO Multi 均不启用。
- 发布前生成固定 `harness-observation.json`，只含版本、覆盖、计数、token、时长、有限枚举和 body-free 输出
  render 事实；原始 prompt、命令、输出、参数、路径、ID 不进入该安全投影或 tracked/public 结果，raw rollout
  trace 不进入结果归档。既有私有 API metadata 仍按原发布合同归档，不冒充公共 body-free 结果。
- 原生 trace 只补两项现有事实源缺失的决策必要能力：writer 完整性终态，以及 direct-model/code-mode-runtime
  真实渲染边界的字节、预算、presentation truncation 与 collection omission。关闭 trace 时不计算或保存这些
  metadata，模型可见输出保持逐字节一致。
- 离线投影要求唯一 exec bundle、允许复用 Guardian trunk 的多终态 turn；核对 trace/API 的 main/Guardian population
  与 completed terminal 总数，仅在 API usage 覆盖完整时核对聚合 usage，缺失 usage 则标为不可测。缺失、重复、
  残缺、schema 漂移或 writer dropped operation 均失败关闭。compact 原因、Guardian 细节和
  完成声明—验证关系继续标为不可测。
- 历史普查拒绝空 API requests，以及缺少、重复、冲突或终态后继续写入的 exec 生命周期，避免残缺样本误计为
  “测得的零”。修复后 v28 census 与 tracked 冻结 JSON 逐字节一致。

## 四问交接

1. 当前不能证据充分地回答“最值得处理”的单一浪费。v28 中 C2 出现在 2/24 个可读 run，C1 弱代理出现在
   1/24；两者都缺少足够影响归因，C11 在 30 run/311 请求中未观察到，C7 当前不可测。
2. 判断来自 schema-v7 v28 的 10 个真实 canary、每题 3 次 Local 运行：API metadata 30/30，exec JSONL 24/30，
   后者覆盖 8/10 任务；6 个集中在 2 个任务的脱敏缺口不计为 0。教师实现只提供候选先验，不进入发生率分母。
3. 下一轮唯一变量是为同一 10 题 × 2 Local round 开启原生 trace 与安全投影；产品行为不变。预期改善 C1/C2/C11
   的任务级覆盖和影响归因，不承诺成功率或耗时收益；main Terra medium、Guardian Terra low、硬上限 20 USD。
4. 20/20 个预定 run 均产生唯一完整投影才有效；任一完整性、schema、来源核对、资源或预算门失败即停止且整包
   无效。观测引入新 infra 失败时关闭 opt-in。候选须满足 WBS 的跨轮/跨任务与影响门槛；后续单变量行为实验若
   主指标恶化或丢失任一原通过任务即回滚。

## 验证与边界

- Python：最终相关集合 277/277 通过；独立复核另以 142 项轻量集合确认关键路径，并确认实时 census 与 tracked
  JSON 一致。
- Rust：`codex-rollout-trace` 62/62；`codex-core` output context 3/3、code-mode 5/5、tool-dispatch trace 4/4。
  首次 code-mode 关闭态测试编译因测试模块漏导入两个符号失败，补齐导入后同一窄集合通过。
- 静态/格式：受影响 `codex-tools`、`codex-rollout-trace`、`codex-core` 的 `just fix` 通过；`just fmt` 首次因默认
  uv 缓存位于只读宿主目录失败，改用项目缓存后通过。formatter 产生的一处任务外旧格式差异已恢复。
- 一次误触发的宽 `codex-core` crate 测试在环境代理导致多项无关网络 fixture 失败后于 2202/3322 中止：当时
  2163 通过、37 失败、2 超时、8 skipped，1120 未运行；不作为本任务通过或失败证据。另一次错误的 nextest
  filter 选中 0 项并返回 4，随后正确拆分的窄集合均通过。
- 未运行 Docker、真实 API、本地模型、训练、validation、holdout、完整数据集、全 workspace、CI 或 PR。

## ignored 与工作树

修复阶段只从任务 worktree 发起、在主物理根按 tracked v28 身份只读 30 份 Local private summary/API metadata、
24 份 exec JSONL 与 6 份 redaction marker；正文仅由分析器在内存中最小处理，未进入终端或 Git。临时
`eval-data/plan052-temp/` 与 `/tmp/rondo-plan052-runtime` 均已删除；未改写、移动或删除既有 ignored 资产。
修复阶段进入时，主工作区来源不明的 `doc/WBS.md` 与 `doc/WBS/multi-agent-trusted-evidence.md` 修改保持原样；
交付复核时外部流程已提交这些变更，主工作区为 clean `main@ea03202` 且 ahead `origin/main` 1。本任务未打开其
差异、未修改或提交主工作区。

## 独立复核

最终只读复核发现并推动修复三项窄问题：复用 Guardian trunk 的多 turn 被误拒、正式 measurement builder 未接入
Local opt-in、trace 关闭时顶层 code-mode 仍计算 metadata。修复及相关门禁重跑后，独立复核结论为 PASS，无剩余
correctness/functionality finding。
