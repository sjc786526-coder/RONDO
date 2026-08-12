# Plan 015 v2 task replacement

- P2 v1 attempt 8 在真实 API 前停止：`terminal-bench/build-cython-ext` 的官方 reference solution 可运行，
  但官方 verifier 返回 reward 0。没有创建 campaign budget/state，P2 API 本地估算费用仍为 0。
- 经批准仅交换 canary/validation 中的 `build-cython-ext` 与 `openssl-selfsigned-cert`；18 个 holdout ID 与其
  SHA-256 保持不变，分区仍为 10/61/18。
- `openssl-selfsigned-cert` 固定于 TB commit `ffccbe05`，source digest 为
  `d4afa2bd2a9ba1420db8d6cfde42ffdb4873ae2d955c35014e8da94444c83302`，运行元数据为 `/app`、2 GiB、
  agent/verifier 900 秒。linux/amd64 exact image 为
  `alexgshaw/openssl-selfsigned-cert@sha256:4c948a4e630af2435ae0a19108fc0814a946ac2fa29a512469e0fc77b38c8c12`。
- 新 v2 campaign/batch/161 个派生 run IDs 与 taskset/catalog SHA 独立冻结；v1 lock 字节保留为退役历史。
- 镜像拉取前后 Docker 均为 0 容器，Windows C: 约 190.5 GiB 可用；只新增获批镜像，未运行 Cargo/API。

## v2 执行与退役

- v2 no-API Oracle 的 10 个任务最终全部 reward 1；fresh exact-wire canary completed，估算
  `0.180523 USD`。
- 正式首轮前 8 个 RONDO slot 暴露三项通用缺陷：非 Git 镜像仍执行 `git config`；proxy digest 未采用
  RONDO E_final 的规范化；中断 campaign 缺少显式历史终态。发现系统性 infra 后未运行整轮 replacement，
  而是停止并保守恢复唯一悬挂 reservation。
- v2 状态为 blocked，预算 reservation 为 0；累计估算 `39.269328 USD`，包含一次计费不明的完整
  reservation，`actual_usd=null`。v2 lock、state、budget、run result、artifact 与 metrics 均保留且不复用。
- `423e09a` 修复上述合同；137 项 focused unittest 通过。v3 使用全新 campaign/batch/run IDs，并在 lock 中
  冻结 v2 prior debit，P2 200 USD 总硬上限不重置。

后续证据：待 v3 完整 Oracle、fresh exact-wire canary 与正式 campaign 完成后在本日志收口。
