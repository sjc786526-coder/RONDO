# Plan 058 commissioning

## 有效 runtime

从 clean `c13ae981e3779305453621584e3259b5cb669d67` detached source 经 canonical build lock/watchdog
完整重建 legacy 与 companion，分别用时 `22m59s`、`19m33s`，均为 `status=0`、`stop=none`。BinaryManifest
prepare/verify 后，runtime 的 RONDO binary、code-mode host、bwrap SHA-256 分别为 `859248187fd5b647bd380249a3c61ca0a46e50359da7f3464dd4a2fb288ea337`、
`ad618afad71b6e0351f16d0bf009e8c9c82aeda92e4a8be23a318169f3aae098`、
`77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c`。

封装前有三次本地 fail-closed 启动：sandbox 无权连接 systemd user bus、误用未识别的 metrics 变量、prepare 进程
HOME/PATH 与真实构建记录不一致。三次均未发送 API、未改变构建字节；修正为既有 `RONDO_BUILD_METRICS_DIR` 与原
构建环境后成功，不弱化冻结校验。

## commissioning-v1 invalid

`plan058-direction1-c2-commissioning-v1` 选择 `terminal-bench/sanitize-git-repo`。Docker/Harbor 零 API 预检
`1/1` 通过。真实运行中，模型在三次 Guardian logical request 后发起第 4 次需审批调用，预算代理按 v28 冻结上限
返回 `guardian_logical_request_limit_exceeded`；agent 非零退出，Harbor 未进入 verifier，Plan 058 runner 因运行链
不完整发布 `terminal_bench_infrastructure_failed` invalid。该终态不是 transport、鉴权、配额或模型不可用，不原地
重试、不冒充 reward 0，也不修改 Guardian、审批、sandbox 或安全策略。

该 identity 结算 28 个可靠 upstream attempts、`1.086600 USD`，总账余额继承到后续 identity。Docker 记录前后均
为 `11.5GB`、容器/卷为 `0`，Docker Desktop VHDX 增长 `0`，Windows C: 余量约 `191.9GB`。公共结果 body-free，
完整 trace/API metadata/Harbor 结果仅留 Plan 058 ignored campaign。

## 下一步

只读比较 formal-v6 同 cohort：`openssl-selfsigned-cert` 两轮均完整，分别仅 4/5 个 main、0 个 Guardian 请求，
且第二轮覆盖已分类为合理恢复的 C2 occurrence。commissioning-v2 使用该冻结任务重新走 initialize、零 API
preflight、paid run、投影、结算和发布；v1 工件与费用永久保留且不混入新结果。
