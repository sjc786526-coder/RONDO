# Plan 010：v6 paid pair 执行日志

时间：2026-08-10 21:03–21:23（Asia/Shanghai）
范围：按授权执行唯一 `fix-git` v6 paid pair；RONDO 首槽失败后立即停止，未运行 Codex 或 M1。

## 1. 授权与冻结参数

- harness：clean commit `1d36eab9bf2b5462347cb304116656f47ef9c2af`；measurement：detached clean
  `cb652e1418e06d53171755963ad9eb8075259ffc`；results 使用同 readiness commit 的独立 worktree。
- pair/batch：`p1-fix-git-pair-v6` / `p1-fix-git-b3-m1-v1`；任务 `terminal-bench/fix-git`；固定 image digest
  `sha256:389b9c8247610c2c5be080b1ac00429007c2c69bf57f7f26c79f0f75ba2d5c74` 已在本机，未 pull/build。
- 拓扑：RONDO slot 1 → Codex slot 2，各一轮、零重试；主 Agent 与 Guardian 均为 `gpt-5.6-luna`，Guardian
  effort `low`；5 USD/run，本 pair 最多 10 USD，底层 ledger hard cap 20 USD。
- 官方模型页再次核对 Standard rates 为 input 0.20、cached input 0.02、output 1.20 USD/百万 token，冻结最大
  request reservation 为 0.755400 USD。
- 严格 loader 以无输出方式确认 provider secret 可用；未打开、搜索、打印、复制或记录 `.env.local` 内容。

执行前 v6 pair/budget/run/results/metrics 路径均不存在。Docker 基线为 14 images / 4.908GB、0 containers、
0 local volumes、13.22GB build cache；项目文件系统可用 846GB。

## 2. 实际运行

21:03 在项目 `with-build-lock.sh` watchdog 内启动 RONDO run
`20260810-230000000-tb-rondo-r1`。watchdog 使用 MemoryHigh/Max 19/21GB、swap max 5GB、项目
195/200GB stop/max；Docker supervisor 共记录 132 个 samples、0 warning。

约 975 秒后 run 以 `AgentTimeoutError` / `infra_failed` 终止：

- Harbor host return code 为 0，但单 trial 为 infra failure、reward 0；RONDO transcript 只有
  `thread.started` / `turn.started`，没有模型响应、tool call、Guardian 或 `E_final`。
- 预算代理收到并 reserve 一个 main 请求，但未收到 upstream response 或 usage；metadata 未形成，verified
  main/guardian roles 均为 0。
- paid pair ledger 原子收敛为 slot 1 `failed`、`blocked=true`、`next_slot=1`。canonical shell 的 `set -e`
  随即停止，因此 Codex slot 2 和 `assess_m1` 均未运行，也没有替代 pair 或重试。
- 结果已追加到独立 results worktree，私有 artifact 位于
  `eval-data/runs/20260810-230000000-tb-rondo-r1`。

watchdog `wrapper_status=complete`、`run_rc=final_rc=70`、`stop_reason=cleanup_reason=none`。项目采样从
12,492,500,992 增至 12,496,617,472 bytes；memory peak 2,007,523,328 bytes，non-reclaimable peak
157,523,968 bytes，swap peak 0，cgroup/host full PSI avg10 peak 均为 0。

运行后 Docker 仍为 0 containers / 0 local volumes，images 4.908GB、build cache 13.22GB，与基线一致；该 run
精确 label 下无容器、网络或卷，项目盘仍可用 846GB。未删除来源不明对象。

关键耐久文件 SHA-256：paid pair ledger `3be48c0a6a210712ded616130b204b32fba470abe71e178fe09bd871f365a6ed`，
budget ledger `d8bcf03e04d7a46b4a11aca8e58a68c56687d27e7734e4065f129641c9fdbba5`，watchdog summary
`83ec8604845bad5b1886d557cf56f56d379a90e60916ba4512d50df2ddd35b2e`，新增 JSONL record（含末尾换行）
`2e98aafb11ca11fdb90813004e10123304619f9be3f4c0ce49a154d46b3c3190`。

## 3. 费用事实

budget ledger 当前只登记一个 request：`reserved_usd=0.755400`、`charged_usd=null`、`usage_valid=null`、
`status=reserved`；run/batch 的已结算 `spent_usd=0.000000`，未承诺余额为 19.244600 USD。

这表示代理没有拿到可结算 usage，不等价于账单明确为 0。没有查询 OpenAI invoice，所以本日志只报告
“0.755400 USD 仍被本地预算保留、实际计费未知”，不把结果记录里的 0 解释为已确认实扣。

## 4. 直接原因与最小修复

现有 canonical shell 在启动 watchdog 前显式 `env -u` 清除了大小写 HTTP(S)/ALL proxy。预算代理的
`urllib` transport 在同一 host 进程里访问官方 endpoint，因此也失去了当前机器必需的宿主网络路径；请求一直等待，
最终由 Harbor agent timeout 收敛。

无认证、无 key、无费用的对照探测：

- 清除所有 proxy 后访问 `https://api.openai.com/v1/models`：15.010 秒超时，HTTP 000；
- 保留当前宿主网络环境：0.494 秒返回 HTTP 401（无认证请求的预期响应）。

最小修复限定为未来 paid canonical shell 保留宿主 HTTP(S) proxy，只设置
`NO_PROXY/no_proxy=127.0.0.1,localhost`，使 Codex→host loopback 不绕出、host budget proxy→官方 API 使用正常
宿主出口。Harbor/Docker 子进程仍由 runner 的最小环境白名单控制；不修改预算、归档、证据或 Docker 体系。

v6 已按零重试合同永久失败，本轮不会用修正后的命令复跑。继续 B3 必须另行冻结新 pair，并再次取得明确真实 API
批量授权。

### 后续配置事实修正

用户随后确认 v6 的真实 provider 并非官方 OpenAI endpoint。无认证探测证明当前配置的 OpenAI-compatible provider
在保留或清除宿主 proxy 时都能快速返回 401，因此上文把“清除 proxy”判断为根因并不成立。实际断链是 v6 的 ignored
config、tracked pair lock 和 budget proxy 都错误固定 `https://api.openai.com/v1`。Plan 011 保留这段历史探测，但
废止“未来必须保留宿主 proxy”的建议：provider 改由 ignored 本地配置决定，canonical shell 继续清除 ambient proxy，
只为 loopback 设置 `NO_PROXY`。v6 结果、ledger、reservation 与 append-only 行均不改写。

## 5. 验收边界

- 真实运行：RONDO 1 次，infra_failed；Codex 0 次；M1 未运行/未通过。
- API：一个 main 请求被本地代理接收并尝试上游传输，但无 upstream response/usage；Guardian 请求 0。
- 费用：本地 settled 0 USD、reservation 0.755400 USD、实际账单未知。
- Docker：真实运行，watchdog/Docker supervision 与精确 cleanup 正常；未 pull/build。
- 未运行：Cargo、本地模型、自动重试、第二侧、M1。

本批没有修改生产代码或 schema。只修正文档中的未来网络调用方式，并保留原 v6 命令作为实际执行历史。

## 6. 交付

- 独立 results 分支以提交 `6db9259` 保存唯一新增的 append-only run record；没有合并或推送。
- 两个 worktree 的 `git diff --check` 与基于严格 loader 的 exact-key diff 扫描通过。
- 本批只改文档/日志，没有为诊断扩大测试；此前 readiness focused pure/fake/loopback 仍是 99/99。
