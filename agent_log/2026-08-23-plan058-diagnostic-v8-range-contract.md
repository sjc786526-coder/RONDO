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
