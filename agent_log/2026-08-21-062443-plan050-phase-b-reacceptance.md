# Plan 050 阶段 B 独立复验

## 结论

**FAIL。** 六槽外部结果、attempt lineage、账本结算、Root 唯一性、body-free 案例和资源状态均可核对，但 C01 RONDO 的
协作合规判读存在真实漏报。当前三份案例和总览不能作为最终结果冻结；Plan 050 阶段 B 的真实 API 执行仍有效，不得重跑，
只需从既有 trace 做本地窄修和重新归约。

## 阻断问题

C01 RONDO 的 typed Team View 显示：Root accepted 1 个成员；该成员完成 7 次 inference 和 7 次非协作
`exec_command`，随后以 `send_message` 向 Root 返回信息；Root 在该消息之后还有一次 inference。它满足冻结口径中的
accepted Root spawn、成员承担实质工作并把贡献交回团队，至少应为 `collaboration_observed`；是否形成完整跨成员影响链仍可保守
保持 `not_observed`。

当前 `proactive_eval.aggregate` 只把成员到 Root 的 `agent_result` 认作 `member_result_returned`，忽略同方向、已完成的
`send_message`。因此 C01 被错误归为 `policy_noncompliance`，总览也把协作案例少计 1 个。这个规则比冻结合同更窄，并与
Team Lens 已记录的 typed 交接事实不一致；已有测试覆盖“有 `agent_result`”和“完全无返回”，没有覆盖“实质成员活动 +
member-to-Root `send_message`、无最终 `agent_result`”这一真实形态。

## 其余核对结果

- 13 attempts 的固定槽位顺序和恢复 lineage 完整；7 个 infra invalid 后形成 6 个唯一有效终态。C01/C02 两侧
  `completed`，C03 两侧 `task_failed`，不需要也不允许购买替代样本。
- 账本为 165/165 `settled`：153 个 `usage_priced`、12 个 `conservative_reservation`；总账
  `30.307445 USD`，无 held/open 请求或悬空 reservation。六个有效槽位费用仍为 `3.156021 USD`。
- 六份 Team View 均有且仅有一个 Root，source/root identity 一致；三个案例和 overview 的现有 SHA-256 与执行日志一致。
  13 个 provider secret 暂存文件均为普通 `0600` 零字节文件。
- watchdog 为 `stop_reason=none`、`cleanup_reason=none`、swap 峰值 0，Windows C: 余量高于硬门禁；没有发现资源残留或
  合同 identity 漂移。
- 当前 HEAD 复跑 `python -B -m unittest eval.tests.test_explicit_eval` 为 14/14 通过；这证明现有门禁稳定，但也确认上述真实
  `send_message` 形态没有回归覆盖。本次未重复 219 项套件。

## 代用户作出的决定

1. 不接受“5 个 policy noncompliance、1 个 collaboration observed”的最终案例结论；阶段 B 最终验收重开。
2. 保留六个有效槽位、13 attempts、165 笔结算和全部外部 verifier 结果，禁止重跑真实 API 或替换有效失败。
3. 窄修方向为：只有在成员已有实质活动时，把已完成的 member-to-Root `send_message` 或 `agent_result` 都视为贡献已交回；
   message/spawn 等纯协作工具本身仍不能证明实质工作。补一正一负的定向回归后，从既有 body-free/trace 资产重新归约 aggregate、
   案例、overview 与文档；C01 RONDO 的 impact chain 可继续保守标为 `not_observed`。
4. 不追加审计设施、Docker、Cargo、全 workspace 测试或第二次付费运行；修复后只跑 Plan 050/共享 aggregate-report 的必要测试并
   再做一次本地复验。

## 当前状态

- 验收：不通过。
- 任务目标：失败（付费执行有效且完整，但最终协作分类和案例总览尚不正确）。
- 执行汇报：本次只读取既有 body-free/Team View 机械字段、运行 14 项定向测试并更新审查状态；未展开正文、未调用真实 API、
  Docker、Cargo 或本地模型，未修改 ignored 结果，未合并、未推送。
