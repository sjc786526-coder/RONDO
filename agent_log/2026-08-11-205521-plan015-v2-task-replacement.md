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

## v3 执行与退役

- 十题 Oracle 再次全部 reward 1；fresh exact-wire canary completed，4 个请求均一次上游 attempt，估算
  `0.226121 USD`。
- 首个 RONDO 任务官方 verifier reward 1、11 个 main 请求全部合法结算，但 producer 错把零 Guardian 的自然完成
  判为 infra。第 2 个任务运行中主动停止，唯一悬挂请求按 `18.885000 USD` 保守结算。
- v3 blocked、reservation 为 0；v3 新增估算 `19.419922 USD`，P2 累计 `58.689250 USD`，
  `actual_usd=null`。v3 identity、state、budget、result、artifact 与 metrics 均保留且不复用。
- 窄修复仅对 campaign 允许全 main 请求序列；若出现 Guardian，RONDO 仍必须有对应 E_final digest。P1 pair 的
  `main → guardian → main` 强制闭环未变。v4 lock 冻结全量 prior debit。

后续证据：待 v4 完整 Oracle、fresh exact-wire canary 与正式 campaign 完成后在本日志收口。
