# Plan 097 独立验收审查

日期：2026-08-28 ｜ worktree：`.claude/worktrees/097-m3-d-dual-backend-engineering`
｜ 审查基线：`32553d84357af31cf695e23842b5bfa4280dc6b5`

## 结论

- **验收不通过；当前交付的任务目标判定为失败，允许在 Plan 097 原授权与边界内修复后复验。**
- 发现 **0 High、4 Medium、1 Low**。问题都可窄修，不否定 `plan097-formal-5` 已真实执行的双 backend、Producer rewrite、canonical commit、fallback/cancel 与费用事实；但在修复前，不能把现有归档认定为完整满足 ExecPlan 的正式工程 PASS。
- 本轮没有运行真实模型、真实 API、Docker、全 workspace 或其他重型测试。审查集中在产品接缝、正式证据、预算硬上限、生命周期与资源终态。

## Findings

### M-1：cloud scorer 的持久费用账本没有跨进程互斥，30 RMB 硬上限可被并发实例绕过

`eval/rondo_eval/publication_critic/engineering/cloud_budget_proxy.py:63-126` 的 `_PersistentLedger` 只持有进程内
`threading.Lock`，并把初始化时读出的 `_document` 长期缓存在实例中。两个指向同一路径的 proxy/恢复命令可以同时从相同旧快照通过
`reserve`，各自写入同一 attempt 编号；后写者覆盖先写者，导致真实 provider 请求数和费用高于持久账本记录，甚至越过 scorer/总费用硬上限。

这不是要求建设通用费用平台。修复只需在既有单文件账本上复用项目已有风格的 OS 文件锁或等强的跨进程串行化，并在每次
reserve/settle/snapshot 的临界区重新读取、校验、原子落盘。补一个两个独立 ledger 实例争用同一路径、不能重复占用 attempt/额度且不能覆盖结算的
轻量回归即可。

### M-2：正式收口没有校验 local/cloud Producer 使用同一冻结 runtime identity

`eval/rondo_eval/publication_critic/engineering/campaign.py:604-623` 每个 backend 执行时都会重新从 ignored runtime config 解析 Producer
model/profile；backend receipt 虽在 `:785-794` 保存 `provider_profile_sha256`、model、effort，`finalize_run` 在 `:798-840` 却只检查
Producer status，没有要求 local/cloud 两份 receipt 的 Producer identity 相等，也没有把该 identity 带入最终 summary。

因此配置在两个 backend 步骤间漂移时，finalizer 仍会给出 PASS，破坏“只替换 scorer backend、Producer/runtime 条件保持冻结”的对照边界。
现有正式两份 raw receipt 实际都为 `gpt-5.6-terra / low` 且 profile SHA-256 相同，所以这是验收器缺口，不是已观察到的正式轮漂移。
窄修 finalizer 的等值/合同校验、最终 body-free 投影与 mismatch 反例测试即可，无需重新调用 Producer。

### M-3：service 关闭异常可被吞掉并被归档成成功 shutdown

`eval/rondo_eval/publication_critic/engineering/service_runtime.py:207-227` 会吞掉 shutdown probe 的任意 `ServiceRuntimeError`，随后没有检查
service 最终 return code，也不区分 graceful shutdown、异常退出、SIGTERM 或 SIGKILL。campaign 在
`eval/rondo_eval/publication_critic/engineering/campaign.py:560-582` 只要进程已退出便无条件写入 `process_reaped: true`；finalizer 又以该布尔值作为
生命周期通过条件。

资源被回收与 shutdown 成功是两个不同事实。保留超时后的有界强制回收是合理的，但异常/强杀不能被归档为正常关闭。执行者可选择返回一个小型
body-free lifecycle outcome，或在清理完成后抛出 typed failure；final receipt 必须由实际结果生成，并补正常关闭、异常退出/强杀不能形成成功 receipt
的聚焦测试。无需扩建审计设施。

### M-4：物理根仍保留一组 task-owned 私有临时目录和未完成的 ledger 临时文件

ExecPlan 要求任务临时文件全部回收，完成汇报也声明 private packet/trace 已清除；但审查时仍存在：

- `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan097/plan097-cloud-producer-720wb1kb`（约 3.1 MiB，0700）；
- `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan097/plan097-cloud-packets-0vl7l262`（0700）；
- `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan097/budget/.producer-terra-v3-ledger.json.tmp-4-127889126176448`（约 11 KiB，0600）。

第一处包含任务私有 runtime home、`auth.json`、session/trace 与 sqlite 状态。审查没有打开这些文件内容。它们的共同时间戳为
2026-08-27 22:58，属于一轮中断 commissioning 的 task-owned 残留，不是应保留的正式 body-free receipt。

执行者应精确清除这些已确认的 task-owned 临时对象，并复核 Plan 097 专属根下没有同类临时前缀残留；不得清理正式/commissioning receipts、预算
ledger、其他任务或来源不明的数据。若现有异常路径可稳定复现泄漏，再补窄 cleanup 回归；否则不要求为强杀场景建设额外清理系统。

### L-1：本地 reference threshold 比既有权威值低 1 ULP

权威常量 `eval/rondo_eval/publication_critic/local_deployment/comparability.py:79` 为 `0.9350569011196121`，但
`eval/rondo_eval/publication_critic/engineering/contract.py:75` 与
`eval/locks/publication-critic-plan097-local-descriptor-v1.json:50` 冻结为 `0.935056901119612`。两者是相邻但不相等的 f64，不只是 JSON
显示差异。正式轮因而没有逐字沿用既有 reference threshold。

请把当前 contract/descriptor 改回权威值，并在归档中诚实注明 `plan097-formal-5` 使用了低 1 ULP 的工程 fixture 值。该差异不改变已观察到的
PASS/REWRITE 工程分支事实，也不具有模型质量语义；本审查决定不为此重跑真实本地模型。

## 已确认成立的部分

- 交付分支、主工作区及 093/095/096 worktree 在审查开始时 clean；正式 source 为 `0ae9623f3d0c2ce764f4b7c6e13994759b47746f`，其后到交付
  HEAD 只有结果、计划、WBS 和日志收口，没有正式代码漂移。`git diff --check 84a0ff2..32553d8` 通过。
- tracked summary 与物理根 formal-5 的 result、preflight、OFF、local、cloud、controlled-gates、contract、两个 descriptor 哈希逐项一致；exact
  safetensors、五个共享 target binary 及 Plan 068 runtime 文件当前哈希与正式 receipt 一致。
- OFF、两个真实 backend 的 3/3 representative cases、两条正常 Producer 3 publish / 2 rewrite / 1 canonical commit、fallback 一次 commit、cancel
  零 commit 及 Team State/Root 公共状态投影相互一致。Rust 产品改动只增加 body-free publication observation 和有界 artifact object id，未复制或
  分叉发布状态机。
- 费用独立复算一致：Producer 172 请求、`2.846074 USD = 21.3455550 RMB`；cloud scorer 24 个 usage-priced attempts、
  `0.0741636 RMB`；合计 `21.4197186 RMB / 30 RMB`，无 unknown-usage charge。M-1 是未来/并发恢复时硬上限可失守，不表示本轮已经超支。
- 聚焦 Python 门禁：Plan 097 engineering tests **45/45** 通过；清除宿主代理变量后 API budget proxy tests **68/68** 通过。首次继承宿主代理的
  loopback 运行出现 502，复核确定为审查环境污染，不计为实现失败。本轮未重复已有 13/13 Rust process test，也未运行全 workspace。
- 没有发现被拒稿提前创建 Event/Version、提前推进 revision/wake 或让 Root 感知 backend 类型的证据。关于 wait 起点晚于首次 rewrite 的疑问不成立：
  wake queue 会保留既有通知，且正式断言要求 wait 跨越最终 commit；若 rewrite 曾唤醒 Root，wait 会在最终 commit 前结束并使断言失败。

## 代用户作出的决策与返修边界

- 保留 formal-5 的真实模型/API/Producer 原始证据和费用总账；上述修复默认**不要求**重新付费或重新加载本地模型。只有修复过程中发现 raw receipt 与
  已归档事实实质矛盾，才通过跨会话队列另行请示。
- 修复只跑受影响 Python 测试、必要的轻量 lifecycle/process 聚焦测试和格式/diff check；不跑全 workspace，不重建可信、审计、注册中心或通用部署平台。
- threshold 修正采用“当前配置回到权威值 + 历史 formal-5 诚实注明 1 ULP 偏差”，不伪造旧 run identity，也不因这一工程 fixture 偏差追加真实模型费用。
- 精确删除 M-4 列出的 task-owned 临时残留属于原授权内正常收口；保留 commissioning/formal receipts 和共享缓存/target。
- 当前不更新 `WBS-COMPLETED`，不把 Plan 097 标为最终完成；未经用户批准不 merge、push、归档、重命名分支或删除 worktree。

## 当前状态

- 验收：**不通过**。
- 任务目标：**失败（当前提交尚未完整实现预期；完成上述窄修后可复验）**。
- 产品结论边界保持：本地模型质量 `NO-GO / 待替换`，云 scorer `NOT QUALIFIED`，M3-D 产品价值未验收，Publication Critic 默认 OFF，生产启用
  `NO`。
