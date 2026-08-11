# Plan 014 正式链路审查修复

## 修改

- 修复 budget proxy 的关闭竞态：活动请求线程不再 daemon 化，关闭与 upstream forward 起点线性化，并等待
  handler 完成结算后再允许 metadata/ledger 生命周期结束。
- 将 main reasoning effort 接入配置、profile SHA、adapter、proxy 和公开结果；正式 completed/M1 统一要求
  `main → guardian → main`，RONDO 同时要求单一 Guardian evidence。
- 修正 M1 对脱敏 public provider schema 的消费，并加入真实 producer→pair ledger→M1 回归。
- 收紧 CLI diagnostic：子进程只接收非密钥环境白名单；请求、最终消息和审批命令均使用精确成功合同；单次
  proxy attempts 按 campaign 剩余 retry 配额缩小，避免先超限发送后报告失败。

## 验收

- focused pure/fake/loopback：148/148 通过。
- `just eval-lock`：85 packages。
- `just eval-test`：321/321 通过。
- `git diff --check`：通过。

本批没有调用真实 API，没有运行 Docker/Cargo，也没有创建或执行新的 paid pair/M1。历史 Sol/Sol 收据保留为
稳定性诊断事实，但旧成功门禁没有消费 `expected_command=false`，不能回填为收紧后的 CLI 或正式 pair 证据。
