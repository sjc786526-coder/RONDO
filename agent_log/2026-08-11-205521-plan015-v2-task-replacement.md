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

后续证据：待完整十项 Oracle、fresh exact-wire canary 与正式 campaign 完成后在本日志收口。
