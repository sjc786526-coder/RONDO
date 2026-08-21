# Plan 049 主动委派收益对比规划

## 本次工作

- 从干净 `main@e192a58` 创建 `.claude/worktrees/049-multi-proactive-delegation-eval` 与分支
  `worktree-049-multi-proactive-delegation-eval`。
- 阅读根/`multidev` 规则、README、当前 WBS、Multi 子 WBS、计划模板、Plan 044/047/048、A/B 整合记录，以及现有
  M-5、Terminal-Bench、预算/归档/resume、rollout trace 和 Team Lens 设施。
- 制定一个覆盖阶段 A/B 的 Plan 049 合同：当前只允许无费用准备；任务、共同 proactive policy、模型、顺序、activation、
  结果分类、恢复和 100 USD 总硬上限已冻结，阶段 B 仍等待单独授权。

## 关键取舍

- 复用 M-5 runtime-v4、冻结十题 catalog 与现有执行/观测组件，不新建第二套 runner、trace writer、在线服务或大型平台。
- 现有 M-5 的 Codex V1 / RONDO V2 非对称命令和 Terminal-Bench trace 未接线不能原样继承；阶段 A 只需在共同 eval
  层窄接两侧 V2、成员配置与 trace root，不修改冻结 Codex。
- 正式十题各一个有效配对，交替 side-first；pilot 固定三题，双方 policy/trace/Team Lens 均有效且至少一侧出现一次
  trace-backed Root spawn 才进入正式运行。
- 有效任务失败不因分数重跑；infra 可在 5 次/槽、40 次全局恢复池与 100 USD 总上限内自主修复、resume 和重跑。
- “委派倾向”和“委派后结果/成本”分别判读；Team Lens 只作行为描述，文件活动只报告机械可见 coverage。

## ignored 共用根边界

- `eval-data/`、`eval/.venv/`、`.env.local`、`rondo.local.toml` 和冻结上游快照不会复制进链接工作树。后续执行如需使用，
  由 049 工作树通过 Git common root 访问；所有受跟踪编辑仍留在 049。
- `eval-data/` 下可放本任务独立命名空间的模拟/运行/trace/Team Lens 产物，依赖同步才会使用共用 `eval/.venv` 与 uv cache；
  不覆盖或清理来源不明的既有资产。
- `.env.local` 只能静默检查安全属性与所需变量非空，禁止读取、搜索、打印、复制、source 或记录内容。

## 边界与验证

- 本批次只创建计划与规划日志，没有实施测评代码或测试。
- 未运行 Docker、Cargo、真实 API、本地模型、付费样本或全量测试；未创建正式 receipt、账本或结果身份。
- 049 分支本次只本地提交；不合并、不推送、不关闭工作树。
