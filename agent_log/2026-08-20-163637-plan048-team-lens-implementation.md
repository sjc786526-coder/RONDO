# Plan 048：RONDO Team Lens 实现

## 实质修改

- 新增 `eval/rondo_eval/team_lens/`：严格读取原生 v1 rollout bundle，按显式 `codex` / `rondo-multi`
  白名单归约为确定性 `team_view.json`，并从该合同生成自包含单文件 HTML；无依赖变更。
- 共有视图覆盖 Agent/thread、turn、inference/usage、tool、terminal、interaction、sequence/time；RONDO 视图只从
  typed Team tool result、canonical projection 外壳及 `team_inspect dump` 提取 revision、Event/Version、route、Fact
  与 attention 关系。prompt/response/reasoning、工具参数/结果正文、命令/输出/路径和 Team 自由正文不进入输出。
- 新增临时目录原生 fixture 与定向测试。Codex fixture 是与冻结源码 schema 一致的合成证据，不冒充真实运行；未提交
  真实 raw trace 或生成的 `team_view.json` / `team_report.html`。

## 零 hook 结论

- 冻结 Codex 与 RONDO 当前 `codex-rs/rollout-trace` 逐文件一致。
- 同一消费者读取指定 24/24 个 RONDO M-5 原生 bundle 成功；全部重复归约/渲染字节一致，11 个 bundle 的五类 Team
  视图全 `available`，其余按现场缺少完整 dump 或 Team 观察显式 `partial`。
- 现有原生字段足够形成核心视图；未触发 hook，未修改 `multidev/`、Team State、Rust 依赖/锁或任务 A 写集。

## 验证与边界

- `PYTHONPATH=eval python3 -m unittest -v eval/tests/test_team_lens.py`：12/12 通过。
- 未运行 M-5 测试（未修改共用 M-5 reader）、Cargo、Docker、真实 API、模型或全量测试。
- 未执行 `just eval-sync`，没有 common-root ignored Python 环境/缓存写入。
- 首个实现提交后仍按用户追加要求进行干净上下文独立正确性/功能性审查；本日志不提前记为独立验收通过。
