# Plan 051 close/pointer 中断恢复

- 第三次外部验收确认正常自动收口与 blocked 路径已正确，但发现两个真实缺口：envelope close 后、pointer retire
  前中断时，旧 `finalize` 会先进入要求 active envelope 的 runner；durable passed/failed 与 runner 退出码错配时可能
  透传错误的成功码。
- `finalize` 现在先读取任务 envelope。若当前 identity 已按匹配终态闭合，则不进入 runner，直接复核 closed record 并
  退役 pointer，分别返回 0/2；envelope 仍 active 时才走既有发布恢复。passed/failed 的任何退出码错配均抛出明确错误，
  不关闭预算、不退役 pointer，也不返回成功。
- closed-envelope 回归现断言 runner 不得调用；新增 passed/2、failed/0 双向错配回归。formal entry 13/13、整改相关
  9 模块 362/362 通过；语法和 whitespace 检查通过。测试显式移除宿主代理，未运行 Docker、Cargo、真实 API、
  全 workspace、CI/PR、validation/holdout、本地模型或训练。
- v23—v28、累计 `$9.412888`、lock、ledger、raw result、tracked public baseline、comparison 与 ignored 运行资产均
  未改变；没有创建 successor 或外部对象。
