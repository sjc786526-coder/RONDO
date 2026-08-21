# Plan 051 schema v7 正式 Canary 收口

- 从冻结 Local `54f62e5...` 经共享锁/看门狗生成新 runtime bundle；Codex
  `v0.147.0@be6e8eac...` 既有 bundle 校验通过。实现 schema v7 显式 bundle、Terra main-medium / Guardian-low
  投影、任务级 400 USD envelope、wire 有界重试、三分法结算、恢复/退役和稳定 `just eval-plan051` 入口。
- v23—v26 零 API 关闭 preflight/runner 适配缺口。v27 在完整 stub preflight 后发送 wire 与首个产品槽，可靠结算
  `$0.270445` 后暴露 v7 发布 schema 缺口；以无新请求路径原子退役，窄修后创建 v28，历史 identity 与费用均保留。
- v28 的 20-side stub、10 receipt 与正式序列通过：1 wire、40 产品槽、400/400 usage-priced upstream attempts。
  10/10 共同有效任务，双方均 5/10，`sigma=0`、`base_delta=0`、`delta=0`，三层 passed、无条件题；有效失败和
  reward 0 未选择性重跑。v28 `$9.142443`，Plan 051 累计 `$9.412888`，`actual_usd=null`，预算终态已关闭。
- 结果发布器的 v7 profile 解析与运行中单槽安全退役补了回归。首次独立审查发现 passed v28 仍被 active pointer
  指向；finalizer 现只在结果发布成功且 task envelope 确认该 identity 已关闭后原子退役 pointer，历史 lock 保持只读。
  默认入口复验为 `idle` / 0 requests，最终相关无 API 集合 346/346、语法编译与 whitespace 检查通过。未运行全
  workspace、CI/PR、validation/holdout、本地模型或训练。
- 同一干净上下文审查者随后以直接相关 60/60、默认入口与 Git/结果终态复验该修复并给出 `PASS`；无剩余
  correctness/functionality finding，未引入额外审计设施。
- 正式运行前后 Docker 均为 26 images / 11.5 GB、0 container/volume/build cache，VHDX 为
  `69,467,111,424` bytes；Windows `C:` campaign 读数为 `183,926,632,448 -> 183,749,709,824` bytes，收尾
  读数 `183,738,654,720` bytes。ignored 资产保留 runtime/code-mode bundle、build metrics、v23—v28
  campaign/preflight、v27/v28 ledgers、task envelope、comparison、诊断 work 与正式 raw runs；13 GB 可重建临时
  build tree 和 v27 孤立隐藏发布 staging 已精确删除。未编辑 `rondo.local.toml`，未改冻结上游源码。
