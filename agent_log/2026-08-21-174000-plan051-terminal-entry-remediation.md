# Plan 051 统一入口终态整改

- 第二次外部验收指出两个真实控制流缺口：`run`/`resume` 在正式 passed/failed 后没有自动关闭任务预算和退役
  pointer；blocked 归档会误入只接受正式 passed/failed 的相对比较器，令应有返回码 3 变成异常 1。
- 终态收口已抽成单一 helper。正式 `run`/`resume` 返回 0/2 后读取 durable terminal state，与恢复用 `finalize`
  共用 envelope 闭合、closed identity 复核和 pointer 退役；状态/退出码不匹配时 fail-closed。blocked 仍保留 active
  identity 给 successor，只写自身归档，不生成相对正式基线。
- 新增 run-passed、resume-failed、blocked-no-comparison 与 blocked-run-preserves-successor 四条入口级回归；此前
  整改相关 9 模块最终 361/361 通过，语法编译与 whitespace 检查通过。测试显式移除宿主代理，未运行 Docker、Cargo、真实 API、全
  workspace、CI/PR、validation/holdout、本地模型或训练。
- v23—v28、费用、lock、ledger、raw result、tracked public baseline 与派生 comparison 均未改写；本轮没有创建
  successor、ignored 运行资产或任何外部对象。
