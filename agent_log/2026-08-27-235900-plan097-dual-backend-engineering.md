# Plan 097：双 backend 工程闭环实施

日期：2026-08-27 ｜ worktree：`.claude/worktrees/097-m3-d-dual-backend-engineering`
｜ 分支：`worktree-097-m3-d-dual-backend-engineering` ｜ 合同：
`plan/097-m3-d-dual-backend-engineering-execplan.md`

## 实质性修改

- 在既有 Publication Critic service/client 与 canonical Team State mutation 之间补齐 body-free candidate/cycle trace 证明；model-visible
  `team_publish` 输出、Root、Team State wire 和默认关闭语义不变。
- 新增 Plan 097 专用工程 contract/campaign：同一 typed 接缝显式选择 local exact 1.7B 或 DeepSeek V4 Flash，运行 OFF、3 个 bounded
  fixture、正常 Terra Producer 重写回环、controlled fallback/cancel，并生成 body-free write-once receipt。
- 复用 Plan 068 worker/serving env、Plan 095 cloud service、既有 Multi 驱动和 API budget proxy；代理窄泛化为支持零 Guardian、main 请求串行
  排队，持久 ledger roll-forward 计入所有 commissioning/失败轮次，没有复制 scorer、发布状态机或费用体系。

## Commissioning 与正式轮

commissioning 先分段打通 OFF/local/cloud/Producer，期间普通容量、并发、wake 与 Producer 持续性问题均通过新 run identity 窄修；有效模型 verdict
没有因结果不符预期而选择性重跑。源码和合同最终冻结在 `0ae9623`，clean `plan097-formal-5` 从头运行：

- OFF 不启动 scorer、不读取 scorer secret、不建立 review cycle，canonical flow 通过；
- local/cloud 均 3/3 fixture 命中预声明分支并覆盖 `PASS + REWRITE`；
- local Producer 为 12 个请求 / `$0.121840`，cloud Producer 为 11 个请求 / `$0.179534`；两者均 3 次 publish、2 次 rewrite/cycle hop、
  最终唯一 Event/Version/mutation、revision 1 与 Root wake；
- Rust controlled process tests 证明 failure fallback 一次 canonical commit、commit 前 cancel 零提交；
- worker/service/proxy 全部回收，private packet/wire/trace 在正式摘要前删除。

正式终态为 `M3_D_DUAL_BACKEND_ENGINEERING_PASS`。累计保守总账 `21.4197186 RMB / 30 RMB`：Producer 172 请求共
`2.846074 USD = 21.3455550 RMB`，cloud scorer 24 个 usage-priced attempts 共 `0.0741636 RMB`，零 unknown-usage charge。
该结论仅授予工程链与 backend 替换接缝 GO；本地质量、云端资格、产品价值、默认启用和生产边界不变。

## 验证与资产

- API budget proxy：68/68 Python tests；Plan 097 contract/campaign/service/runtime/Producer：45/45 Python tests；Python compile 与 diff check 通过。
- formal controlled Rust process tests：13/13、零 failure/error；经正式构建锁复用物理根唯一
  `.codex/cargo-target/rondo-multi`。`multidev` `fmt-check` 通过；未运行全 workspace。
- tracked 正式摘要：`eval/results/publication-critic/m3-d-dual-backend-engineering-v1.{json,md}`；完整 body-free receipt 位于物理根 ignored
  `eval-data/publication-critic/plan097/formal/plan097-formal-5/`。
- 任务未训练、微调、量化、转换、下载/上传模型，未使用 Docker、RunPod、validation/unseen 或全 workspace，也未修改模型、tokenizer、
  Plan 068 env、密钥文件或产品默认配置。

当前实现与正式结果等待首次独立验收；按合同，本轮不更新 `doc/WBS-COMPLETED.md`，不合并、不推送、不归档/重命名分支、不删除 worktree。
