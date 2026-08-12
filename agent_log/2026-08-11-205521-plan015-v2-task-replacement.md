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

## v4 执行与退役

- 十题 Oracle 全部 reward 1；fresh exact-wire canary completed，估算 `0.198830 USD`。
- v4 第一轮 10 个首跑后有 5 项 infra；旧合同因此执行全轮 replacement，补跑后仍有 4 项 infra。状态机没有在
  轮末即时判定，错误启动 `aa-rondo-2` 首个 slot；发现后停止，唯一活跃请求按既有合同保守结算。
- v4 已收口为 blocked，budget ledger `99.580057 USD`、reservation 为 0；连同 v2/v3 与 v4 canary，P2 累计
  `158.468137 USD`，`actual_usd=null`。20 条 public run record 已提交到 results 历史；v4 lock/state/budget/
  artifact/result 均只读且不复用。
- `sanitize-git-repo` 的官方 verifier 实际 reward 1，但私有 `agent/codex.txt` 含任务 fixture 形式的 secret，被最终
  artifact scanner 正确拒绝。发布器现先做同一 secret preflight：敏感私有文本不归档，只保存无内容的 bounded
  omission marker；最终 scanner 未放宽。

## v5 合同

- 用户追加 `200 USD`，P2 总硬上限为 `400 USD`；v5 lock 精确带入 `158.468137 USD` prior debit，使用新的
  campaign/batch/161 个 run IDs，任务、profile、bundle、TB commit 与四个基础轮次不变。
- 每个 task 只在首跑 infra 时定点补跑一次；pass/reward 0 不补跑，不再整轮重跑。补跑后每轮最多保留 2 项
  infra，并在进入下一轮前即时检查。
- infra 使用冻结枚举分类；同一类别累计命中 3 个不同 task 时立即熔断。预算停止引发的 publication 失败继承
  ledger stop reason 的上游类别。`sigma`/`delta` 只在四轮共同有效的同一集合上计算，公开精确分母，少于 8 项
  则 M2 blocked。

后续证据：待 v5 完整 Oracle、fresh exact-wire canary 与正式 campaign 完成后在本日志收口。
