# Plan 068：Publication Critic 本地部署资格交接

## 结果

- 从 RunPod exact winner 卷 `hi3iaz8rsr` 完成 manifest 驱动、可续传且不覆盖的只读交接；120 个对象、24,385,153,354 bytes 全部按 bytes/hash 验证。
- exact base 九文件、C1/C2/C3、62 文件 source bundle、recipe/model contract、依赖 freeze/identity、FlashOptim wheel、winner/provider/receipt 以及正式 C3 full checkpoint 均闭合。checkpoint 12 文件、10,555,059,139 bytes；optimizer 311 项、scheduler 与 RNG 可反序列化。unseen-test 未导出、读取或运行。
- 新增 strict handoff/identity、真实 Transformers inference、持久 Python worker/framed IPC、Rust scorer/service/probe、service runner 与 write-once 三态资格 runner；没有修改 Plan 054/055/057 的输入、scalar、service verdict/identity、fallback/cancel/store 语义。
- 部署直接使用原始 safetensors，CUDA BF16；参考为相同原始 safetensors 的 CPU FP32。没有转换、量化、训练、远端上传、真实外部模型 API 或 Docker。

首次独立审查确认旧 formal 把 Rust 单响应内部 sigmoid 校验 `1e-12` 误作独立 CUDA BF16 worker 的 projected drift 门，并指出
service 子进程继承完整开发环境、raw evidence 缺少轻量直接绑定。三项 finding 均属实，已完成以下整改：

- 用 C1 同一 packet 顺序启动四个 fresh CUDA BF16 worker，逐个完成 load/score/shutdown/reap，pairwise raw/projected drift 均为 0；跨 worker
  projected gate 在新 formal 前统一冻结为已有 BF16 部署 projected drift cap `0.005`，不按 C1/C3 结果贴线倒推；Rust 单响应内部 `1e-12` 不变。
- service/probe 只注入 CUDA、动态库、离线模型、Python path、线程和根 watchdog 所需变量；sentinel 回归确认无关开发变量不进入子进程。
- freeze/offline/service/observations/archive v2 直接绑定 run、freeze、artifact、cohort、packet、raw output hash，以及 real-service/probe/python 程序 hash。
  一次调试轮因此在启动前识别出误选受控 test service，按基础设施失败保留且未拼入正式结果。

新的唯一有效 formal `plan068-formal-20260824T222852Z-qualification-v3` 从空 namespace 完整运行四对象，绑定 clean source
`3906152d1348c273f1cd94404f2a3978f2a836fc` 和 freeze
`4497b02ed95583e3b2daf5ad1a102199d8144db27b20375255eefdfe3f5f1ce0`。24 条 cohort 全部来自 Plan 054 且
`future_unseen_test=false`；临时 threshold 来源为 Plan 054 v4，不是最终产品 threshold。旧
`plan068-formal-20260824T201213Z-qualification` 因错误门失效，`...T221100Z...` 是基础设施失败，均只保留为历史诊断。

| 对象 | 结论 | 关键事实 |
|---|---|---|
| base | `NOT_QUALIFIED` | load 3.679s；raw max drift 0.1651 通过；projected max drift 0.03404 和 1 个临时 verdict mismatch 失败；后续 `N/A` |
| C1 | `QUALIFIED` | load 3.272s；offline 门通过；RSS 4.299GB、VRAM 3.530GB、warm P95 125.2ms；service raw/projected drift 0.125/`9.58e-10`，15/15 stress，P95 751.2ms |
| C2 | `NOT_QUALIFIED` | load 3.318s；ranking 0.4565、obvious direction 0.6037、pair preservation 0.0833 均失败；后续 `N/A` |
| C3 | `QUALIFIED` | load 3.038s；offline 门通过；RSS 4.298GB、VRAM 3.530GB、warm P95 125.8ms；service raw/projected drift 0.0078125/0.0009505，15/15 stress，P95 754.9ms |

C1/C3 真实服务均为 0 verdict mismatch；代表 C1 另完成 cancel、task-owned worker SIGTERM、typed `backend`、自动重启、post-restart
review、cleanup 和 shutdown，最终 orphan/body leak 为 0。由于 base 未通过，`m3_c2_prerequisite_satisfied=false`，不得自动进入 M3-C2。

## 验证与保留

- 本轮新增/受影响 Python：41/41；Python compileall、`git diff --check` 通过。此前 Python 113/113、Rust `codex-publication-critic` 34/34、
  Rust fmt 和 Plan 068 inference lock check 已通过且相应 Rust/lock 代码未受本轮影响，未机械重跑。Docker 未使用/未运行。
- ignored `eval-data/publication-critic/plan068/`：24,386,010,209 bytes，51 目录均 `0700`、269 文件均 `0600`；serving env：
  6,897,892,345 bytes；公开 exact-base HF cache：3,457,214,889 bytes，位于 `0700` 私有父目录下，内部保持 HF 标准权限。全部保留。
  Windows C: 删除前可用 102,363,279,360 bytes；正式轮后无 GPU compute process。
- 正式 summary：`eval-data/publication-critic/plan068/handoff-evidence/plan068-local-handoff-summary.json`；正式 archive：
  `eval-data/publication-critic/plan068/formal/runs/plan068-formal-20260824T222852Z-qualification-v3/`。archive 中 observations canonical hash
  `d0e0b88473554b2949e7058c4853da3202db2ef18fc5896c843dfab0fc59fafe` 与 result 绑定一致，27 项 raw evidence hash 已直接绑定。
- 独立复验提交 `87122536a324bcd060d9b5df04d618f4760cbc77` 返回 `LOCAL_HANDOFF_ACCEPTED` 后，仅删除 exact volume
  `hi3iaz8rsr`，RunPod 返回 HTTP 204。删除后为 0 Pod、0 volume；Pod 费用为 0，当前 01:00–02:00 UTC 桶无 volume 记录，
  00:00–01:00 UTC 的 `$0.005833333` 是删除前历史记录，因此 compute/volume 持续费用均为 0。没有发现或删除无关资源。

WBS 建议 delta：记录 M3-C1 本地交接、资格执行和远端清理已完成，base/C1/C2/C3 分别为
`NOT_QUALIFIED`/`QUALIFIED`/`NOT_QUALIFIED`/`QUALIFIED`，RunPod 为 0 Pod/0 volume 且持续费用归零。由于 base 未通过，M3-C2
前置保持关闭；上游需处理 base BF16 projected/verdict parity 和 C2 direction/ranking。不在本 task branch 抢写共享 WBS。
