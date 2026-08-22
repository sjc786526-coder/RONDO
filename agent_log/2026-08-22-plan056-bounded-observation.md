# Plan 056 v1 无效 campaign 与设施根因

## 实质修改

- 新增 Plan 056 独立 identity、20-slot round-major 状态机、串行 Docker/Harbor coordinator、每 attempt 未定价兜底、
  task-budget 收口、schema-v2 body-free 结果与安全恢复边界；默认 `status` 不加载配置、密钥、Docker 或 API。
- 从 clean `2765ff8f82ce21262af46bdf93a62c75b381b631` 构建并冻结 RONDO Local legacy、code-mode companion 和
  runtime bundle；10/10 零 API 预检通过。
- 正式第 1 个 slot 发布；第 2 个已发送 slot 因投影完整性失败触发整包 invalid。没有重发、补位、补题、补轮或
  第二个付费 campaign。公共结果固定 1/20、25 attempts、`0.631065 USD`、reservation 0、无候选推断。
- 修复两个真实设施问题：持久 budget state 的只读 totals 汇总；Team Lens 在 runtime-end 晚于 tool-end 时的假阴性。
  后者使用第 2 题原始 trace 只读复放确认修复，但不改写 campaign 终态。

## 验证

- Plan 056 实现阶段相关集合最终 209/209 通过；身份/预算直接测试在关闭路径修复后为 17/17。
- Team Lens + harness observation + Plan 056 相关集合 69/69 通过；乱序实测 trace 的 terminal availability 为
  `available`。Ruff 对新增 Plan 056 文件通过；`py_compile` 与 `git diff --check` 通过。
- Cargo 构建、Docker 和正式 API 均经共享锁/资源看门狗串行执行。未运行全 workspace、CI、PR、Codex 对照、
  validation、holdout、E-A、完整数据集、本地模型、训练、云任务或上传。

## 资源与资产

- 保留 common-root ignored 资产：`eval-data/sources/plan056-rondo-local-2765ff8f/` detached source；约 13 GiB
  build target；三个 frozen bundle；Plan 056 campaign、budget 和各 build/preflight/paid/close metrics。
- 读取既有 v28 lock/Terminal-Bench source、项目局部 `eval/.venv` / `eval-data/uv-cache`、固定 bwrap 资产和 10 个
  pinned task image；未读取 Plan 054/055 私有资产或 `.env.local` 内容。
- Docker 总量与 VHDX 无增长；Plan 056 容器、网络、卷均已清空，镜像保留。Windows `C:` 终态余量
  186,090,741,760 bytes，高于硬门限。

## 后续授权

v1 关闭后，用户把 Plan 056 累计预算提高到 100 USD，并授权真实 rehearsal 与可修复设施问题后的全新 campaign
重启。v1 的费用、公共无效结果和私有工件继续保留；本日志不把后续 rehearsal 或最终 20/20 冒充为 v1 的续跑。
