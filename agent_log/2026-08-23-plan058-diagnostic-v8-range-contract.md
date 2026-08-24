# Plan 058 diagnostic-v8 range contract

从 clean `199849b7ea0e6746e7ae8be0c4530a8c19b9a996` 完整重建 legacy/companion，Cargo 分别
`19m53s`/`16m52s`；两个 watchdog 均 `status=0`、`stop=none`、swap peak `0`，项目 peak
`170099150848` bytes，无外部 Cargo。prepare/verify legacy、companion、既有 bwrap 与 runtime 均通过。
CLI/host/bwrap SHA-256 分别为
`453858a5230d0b3a7015a9df8a364832293b07202f7691f708040f5b7f1621dd`、
`d776884488196215bf391a447eb6a037d590f2ea5454b845ddafdfa9de1668a2`、
`77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c`，runtime manifest SHA-256 为
`09fabd2a656c6286faa5d6299249f9b94b471680cc37b643baa6120a9d3218bd`。

首次 diagnostic-v8 initialize 在 Docker/API/campaign identity 前由本地 range contract 拒绝。现有实现只接受
初始 commissioning sweep 的 `8..20`，与用户后来冻结的规则冲突：新 formal 若在其他槽暴露设施故障，脏版本只复验
实际问题题目。活动 pointer 保持为空，未创建 campaign，费用仍为 `15.158073 USD`。

修复仅把 diagnostic 绝对槽范围改为冻结 20 槽内的任意闭区间 `1..20`，不改变 formal 的完整 20/20、执行顺序、
预算或历史 sweep。新增绝对槽 4 与越界/倒序回归；相关 pair/results/Plan 058 回归 `106/106` 通过。该零 API
设施失败不会复活为 identity；提交后从新 clean source 重冻 runtime，再只初始化并运行绝对槽 4。

从 clean `99f053015829f1945d613f551b84978edbc4bec5` 将该零 API attempt 未绑定 identity 的独占 target 精确
迁移并增量重建，legacy/companion 分别 `1.52s`/`0.59s`，watchdog 均 `stop=none`。CLI/host/bwrap hashes 不变，
新 runtime manifest SHA-256 为 `dd26b0e9fe868ae1f7138eec9a23e4abcad174c1ec988e54a6a3130471f353a0`；旧
`199849b` bin/metrics 保留，旧 target 未被任何 campaign 引用。

`plan058-direction1-c2-diagnostic-v8` 仅含绝对槽 4，preflight/result/source validation/finalize 均 `1/1`。
agent、Harbor、verifier、Guardian evidence、schema-v2 投影、预算和发布完整，task pass/reward `1`。12 个可靠
attempts、0 transport retry、费用 `0.235429 USD`；累计 task budget `15.393502 USD`、reserved `0`、剩余
`34.606498 USD`。raw exact-C2 3 次/`5,656 ms` 分别用于失败后确认、恢复重试和成功变更后验证，均归为
reasonable，refined harmful/reasonable/insufficient 为 `0/3/0`，无害四门通过。Docker/VHDX 增长 `0`，最终
Docker 11.5 GB 且无容器/卷/cache，Windows C: 实际余量 `200631042048` bytes。局部 commissioning 闭环；
下一步从提交后的新 clean source 冻结全新 formal，不复用 diagnostic 数据。
