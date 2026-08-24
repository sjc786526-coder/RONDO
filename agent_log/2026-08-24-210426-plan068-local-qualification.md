# Plan 068：Publication Critic 本地部署资格交接

## 结果

- 从 RunPod exact winner 卷 `hi3iaz8rsr` 完成 manifest 驱动、可续传且不覆盖的只读交接；120 个对象、24,385,153,354 bytes 全部按 bytes/hash 验证。
- exact base 九文件、C1/C2/C3、62 文件 source bundle、recipe/model contract、依赖 freeze/identity、FlashOptim wheel、winner/provider/receipt 以及正式 C3 full checkpoint 均闭合。checkpoint 12 文件、10,555,059,139 bytes；optimizer 311 项、scheduler 与 RNG 可反序列化。unseen-test 未导出、读取或运行。
- 新增 strict handoff/identity、真实 Transformers inference、持久 Python worker/framed IPC、Rust scorer/service/probe、service runner 与 write-once 三态资格 runner；没有修改 Plan 054/055/057 的输入、scalar、service verdict/identity、fallback/cancel/store 语义。
- 部署直接使用原始 safetensors，CUDA BF16；参考为相同原始 safetensors 的 CPU FP32。没有转换、量化、训练、远端上传、真实外部模型 API 或 Docker。

正式 run `plan068-formal-20260824T201213Z-qualification` 绑定 clean source
`4f3d67c85e0643a4272c499a45ca9245c53daabf` 和 freeze
`1feb7ad63b206f3fab2fd6daf81aa89e41df5b7d9de4d9c0a428aa36b76b1809`。24 条 cohort 全部来自 Plan 054 且
`future_unseen_test=false`；临时 threshold 来源为 Plan 054 v4，不是最终产品 threshold。

| 对象 | 结论 | 关键事实 |
|---|---|---|
| base | `NOT_QUALIFIED` | load 3.477s；raw max drift 0.1651 通过；projected max drift 0.03404 和 1 个临时 verdict mismatch 失败；后续 `N/A` |
| C1 | `NOT_QUALIFIED` | load 3.262s；offline 门通过；RSS 4.295GB、VRAM 3.497GB、warm P95 103.1ms；真实 service raw drift 0.125 通过，projected drift `9.58e-10` 超过 `1e-12` |
| C2 | `NOT_QUALIFIED` | load 3.388s；ranking 0.4565、obvious direction 0.6037、pair preservation 0.0833 均失败；后续 `N/A` |
| C3 | `NOT_QUALIFIED` | load 3.513s；offline 门通过；RSS 4.295GB、VRAM 3.497GB、warm P95 103.9ms；真实 service raw drift 0.0078125 通过，projected drift 0.0009505 超过 `1e-12` |

C1/C3 真实服务均完成 1/2/4/8 压力共 15/15 成功和 graceful shutdown；代表 C1 另完成 cancel、task-owned worker SIGTERM、typed `backend`、自动重启、post-restart review、forced cleanup，最终 orphan/body leak 为 0。资格门在正式前冻结，未因结果放宽。四对象均未资格通过，因此
`m3_c2_prerequisite_satisfied=false`，不得自动进入 M3-C2。

## 验证与保留

- Python pure/fake/loopback：113/113；Rust `codex-publication-critic`：34/34、0 skip。
- Rust fmt、Plan 068 inference `uv.lock` check、Python compileall、`git diff --check` 通过。
- 真实模型与 Rust 重测均通过根 `with-build-lock.sh`/watchdog 与当前 069/070 串行；Docker 未使用/未运行。
- ignored `eval-data/publication-critic/plan068/`：24,385,637,322 bytes，42 目录均 `0700`、209 文件均 `0600`；serving env：6,897,892,345 bytes；公开 exact-base HF cache：3,457,500,887 bytes。三者根均 `0700` 并保留。Windows C: 删除前可用 139,242,090,496 bytes。
- 正式 summary：`eval-data/publication-critic/plan068/handoff-evidence/plan068-local-handoff-summary.json`；正式 archive：`eval-data/publication-critic/plan068/formal/runs/plan068-formal-20260824T201213Z-qualification/`。
- 删除门查询：0 Pod；当前唯一卷为 `hi3iaz8rsr`（US-KS-2、Standard 60GB）；compute 持续费 0、volume 约 `$0.005833333/h`。收到独立审查者字面量 `LOCAL_HANDOFF_ACCEPTED` 前保留卷。

WBS 建议 delta：记录 M3-C1 本地资格执行已完成但四对象均 `NOT_QUALIFIED`，保持 M3-C2 阻塞；上游需处理 base BF16 projected/verdict parity、C2 direction/ranking，以及 C1/C3 重复 service inference 的 projected parity。最终卷删除事实应在删除后再写，不在本 task branch 抢写共享 WBS。
