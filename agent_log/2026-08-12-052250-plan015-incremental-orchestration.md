# Plan 015 增量编排与安全恢复

- v9 未被中止或改写；自然收口为 blocked。其 Oracle 10/10、wire canary `$0.143029`、首个正式任务
  `$0.425953` 与后继累计 debit `$282.287684` 均从既有 state/receipt/budget 复核，reservation 为 0。
- 新 Oracle store 逐题原子保存 proof，再由十题 manifest 聚合。proof 绑定 task/source/image、verifier、共享执行
  组件、Harbor/TB、seccomp 和稳定 Docker 事实，不绑定 campaign、provider profile、wire canary 或整个 Git commit。
- B7 coordinator 改为轻量 campaign lease；每个 Oracle/paid task 单独进入 build lock/watchdog，锁内执行实时门禁、
  单 slot、Docker 清理、最终资源计数和 durable state。恢复只接受 public result 与 settled budget 完整一致的 running
  slot，其他含糊状态 fail-closed。
- 161 个 slot 继续机械派生；active pointer 当前关闭，v1—v9 只读。identity generator 从 predecessor terminal state、
  wire receipt 与完整 budget 重算 prior，并拒绝版本、run-ID、profile/bundle、cap 或 debit 漂移。
- 验收：focused 185/185、完整 pure/fake/loopback eval 420/420、`just eval-lock` 85 packages、`git diff --check`
  通过。本批未调用真实 API、Docker 或 Cargo，未读取 `.env.local`，未修改任何 v1—v9 历史资产。
- 生成器随后冻结 v10：`p2-b7-canary-baseline-v10`、`p2-b7-canary-sol-sol-v10`、run ID base
  `20260812-300000000`、lock SHA `3e51aa222cc222890627036221a8a235e0ff6d95b0c5491b84eb9a2cb48d5d32`，
  prior `282.287684 USD`。首题 Oracle 官方任务与 Docker 清理完成，但 proof 发布调用了强制 paid metrics 的 B2
  receipt 而在落盘前停止；无 state/slot/API/费用。新增 Oracle 专用 compatibility receipt，保持 paid receipt 门禁，
  focused 108/108 与 lock 通过。
- v10 修复后自然完成十题 Oracle 与 fresh wire canary；首轮 13 个 paid run 后，三个不同 task 的
  `provider_response_integrity` 触发冻结全局熔断。v10 新费用为 wire `$0.225026` + paid `$61.383485`，累计
  debit `$343.896195`，reservation 0，全部 state/result/artifact 只读。
- 后继 schema-v2 离线实现 321 个机械 slot、700 USD 累计 cap、infra-only a1—a4、同题同类第二次 durable
  diagnosis hold、仅外部瞬态 resolution 与第三次 `task_local_reproducible_infra`。本地/shared 缺陷 resolution
  直接阻断 identity；非 infra 不补跑，既有全局熔断、逐轮门禁和共同分母不变。
- Docker counter 不再丢弃全部命令失败细节：只发布 exit/timed-out、stderr 长度/SHA 与最多 512 字节的脱敏
  excerpt，仍严格拒绝 live-container metrics 缺失。focused 170/170、完整 eval 430/430、`eval-lock` 85 packages、
  `git diff --check` 通过；本离线批次未调用 API、Docker 或 Cargo。
- 生成器以 v10 只读 terminal facts 冻结 v11：schema-v2、321 个唯一 slot、run base `20260812-310000000`、
  cap `700 USD`、prior `343.896195 USD`，lock SHA `b2ff3698881b0e0626823a72afc62782e21ab9330cca18317f7571085dc40348`。
- v11 Oracle 10/10 与 fresh wire 完成；db/extract completed，filter a1/a2 同为 Docker metric exec 128，第二次后
  durable hold，a3 未 claim。no-API 官方 Oracle 的 PIDs 采样多次达到 `256/256`，确认不是供应商/温度而是本地
  资源合同缺陷；v11 收口 blocked，本轮 wire+paid `2.066952 USD`，累计 `345.963147 USD`、reservation 0。
- 后继 versioned catalog 只把 filter 的 PIDs 从 256 提到 512，其他九题保持 256；历史 catalog 由 lock SHA
  继续只读加载，Oracle proof 与 paid request 均从同一 `FrozenTask.pids_limit` 投影。
- 离线门禁 432/432 与 `eval-lock` 85 packages 通过后，生成器冻结 v12：run base `20260812-320000000`、
  lock SHA `05d74b86ced79c68c73c857c3d4cd75b98150c15dafb264b9ae3c98068b20452`、prior `345.963147 USD`；
  v1—v11 均保持只读。
- v12 Oracle 10/10、wire `0.224821 USD` 完成；filter a3 重现 Docker metric failure 时发现 failure publisher
  topology 只允许 a1/a2。a3 请求全部 settled，但 tracked record 缺失，恢复保守记 operator interruption；v12
  blocked，累计 `385.923585 USD`、reservation 0。未回填历史。
- 离线统一 producer/validator a1—a4 并将 crash reconciliation 提前到 Oracle；后继 Docker 合同只对已验证 stopped
  object 将 disappearance grace 扩至 5 秒，live/replacement 不放行。v12 没有 512 PID 用尽的持久证据，
  因此后继仍冻结 catalog v2 的 512 PID，不用新资源上限掩盖 lifecycle 问题。
- focused 132/132 与 `eval-lock` 85 packages 通过后，生成器冻结 v13：run base
  `20260812-330000000`、lock SHA `c99257c15015a334ef46334536b09582ec5b642e1fa21e17c522260693052f1e`、
  prior `385.923585 USD`；v1—v12 保持只读。
- v13 首次 Oracle 在 sqlite 官方 verifier 的外部下载阶段超时，API/费用为 0；恢复时其余九题 proof 命中，只补
  sqlite 后聚合 10/10。fresh wire completed 并结算 `0.198335 USD`，但 worker 因 paid 推进块位于恒定提前返回
  后而退出；没有 paid slot claim、budget ledger 或 reservation。
- `3ebb97c` 将 post-Oracle wire/paid 单步推进恢复为显式 worker 路由，并增加原子退役和路由回归；focused
  93/93 与 `eval-lock` 85 packages 通过。v13 以本地 harness defect blocked，生成器机械得出后继 prior
  `386.121920 USD`，随后冻结 v14：run base `20260812-340000000`、lock SHA
  `dc4eb0f28a93784e6021782079d6c6993735e1b6cb152b583bb34ad4c417e8a8`；v1—v13 均保持只读。
- v14 命中十题 Oracle proof，fresh wire `$0.160824`；db/extract completed 后，filter a1 为 provider-integrity，
  a2/a3 均为 Docker metric exec failure，并按第二次同类规则进入 diagnosis hold。独立 no-API 官方 Oracle 在同一
  镜像和 512 PIDs 合同下达到精确上限仍 reward 1，证明 supervisor `docker exec` 没有进程余量；未运行 a4。
- v14 以 local implementation defect blocked：本 identity wire+paid `$20.569203`，累计 `406.691123 USD`、
  reservation 0。catalog v3 仅将 filter 调至 1024 PIDs；focused 82/82 与 lock 85 packages 通过后，生成器冻结
  v15：run base `20260812-350000000`、lock SHA
  `6749b815023bcca52bc2a57df3faa544eafb5ad38bef5284dc7289644f48f44a`、prior `406.691123 USD`；v1—v14
  的 lock/state/ledger/result/artifact 均未改写。
- v15 只重跑 filter Oracle，fresh wire `$0.210982`；db pass、extract reward 0，filter a1/a2 同类 Docker failure
  后在 a3 前诊断并退役。本 identity `$1.870700`，累计 `$408.561823`、reservation 0。no-API RCA 显示
  1024 PIDs 仅 9/28 Selenium batch 完成、19 次 driver 创建失败；4096 PIDs 下 28/28 完成、峰值 3083，另闭合
  stopped-container inspect/remove 竞态。focused 164/164、lock 85 packages 通过。
- catalog v4 仅将 filter 调至 4096 PIDs；生成器冻结 v16：run base `20260812-360000000`、lock SHA
  `8491778a7e358d279e96771f4a97927f9004c57498ba22a3d4e93c28067d4f21`、prior `408.561823 USD`。v1—v15
  及其 lock/state/ledger/result/artifact 均未改写。
