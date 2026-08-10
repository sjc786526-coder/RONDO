# Plan 010 paid readiness 限域审查

- role 投影、publication journal 前失败收敛、v6 两槽顺序与 canonical 命令未发现阻断。
- 官方 Luna 模型页当前价格为 input 0.20、cached input 0.02、output 1.20 USD/百万 token。
  readiness 提交误改为 1.00/0.10/6.00，会过早停止 run 并高估费用，但不会放宽授权上限。
- 已最小回退三个价格常量和相应断言/说明；20 USD batch、5 USD/run 和两槽最多 10 USD 授权边界不变。
- 本轮不运行 Docker、Cargo、本地模型或真实 API。
