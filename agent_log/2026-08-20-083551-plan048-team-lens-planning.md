# Plan 048：RONDO Team Lens 规划

## 本次工作

- 从干净 `main@7ba7eb6` 创建 `.claude/worktrees/048-team-lens` 与分支 `worktree-048-team-lens`。
- 阅读根/`multidev` 开发规则、顶层与 Multi 子 WBS、计划模板，以及原生 rollout trace、既有 M-5 collector 与
  Team State projection/观察面源码。
- 冻结 Team Lens 两阶段合同、A/B 并行写集、body-free `team_view.json`、四态降级、静态 HTML 和条件 hook 门。

## 关键事实

- 冻结 Codex 与 RONDO Multi 的 `codex-rs/rollout-trace` 当前逐文件一致；bundle schema 本身不携带产品身份，
  Team Lens 必须由调用者显式声明 `codex` 或 `rondo-multi`。
- 共有 trace 已提供 thread/turn/inference/tool/terminal/interaction/time 等结构化入口。RONDO Team 关系目前主要通过
  通用 tool dispatch 与 request-only projection 间接出现，是否需要最小 hook 必须由代表性 bundle 的零 hook 验证决定。
- `codex-source-code/`、`eval-data/`、`test-data/` 和 `.claude/` 均为 git-ignored；前三者不会自动出现在 048 工作树。
  实施时只读使用主工作区内指定源码/trace，所有受跟踪编辑和生成物仍留在 048 工作树或临时目录。
- 只核对路径/manifest 存在性后，ignored `eval-data/` 现场有 24 个 RONDO M-5 rollout trace bundle，未发现冻结 Codex
  的现成 bundle；没有打开 payload。Codex 侧应使用冻结源码的原生 fixture/builder 或无 API、无模型离线路径补齐，
  并把合成 fixture 与真实运行证据明确区分。
- 独立审查后补明：projection 自由正文可能伪装结构行，零 hook 必须有对应回归；manifest/raw event/reduced state
  版本分开记录；沿用原生 reader 错误而不扩建通用审计层。
- `just eval-sync` 会写 common-root ignored `eval/.venv` 与 `eval-data/uv-cache`。仅在依赖确需物化时允许这一主工作区
  ignored 写例外，执行者须单独汇报；本计划制定批次未执行同步。

## 边界与验证

- 本批次只创建计划与日志，没有实现代码、没有读取真实 trace 正文、没有运行测试，也没有使用 Docker、API、模型、
  完整数据集或 Cargo。
- 任务 A 的工作树/分支已存在但未触碰；共享 WBS、Team State crate、Rust 锁与主动测试入口留给 A 或最终整合者。
- 048 分支完成实现后只允许本地提交；合并与推送等待用户批准。
