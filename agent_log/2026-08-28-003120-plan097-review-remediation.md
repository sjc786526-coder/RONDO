# Plan 097 初审问题窄修

日期：2026-08-28 ｜ 分支：`worktree-097-m3-d-dual-backend-engineering` ｜ 初审报告：
`agent_log/2026-08-28-001531-plan097-independent-review.md`

## 修改

- cloud scorer 单文件费用账本改为每次 reserve/settle/snapshot 都在 OS 文件锁内重新读取、校验并原子落盘；两个独立实例不能再重复占用 attempt、覆盖结算或绕过额度。
- formal finalizer 现在要求 local/cloud Producer 的 profile SHA-256、model、effort 彼此相等且等于当前冻结 runtime projection，并把该 body-free identity 写入 summary。
- scorer service 仍会在异常路径有界回收，但 shutdown probe 失败、未接受、提前退出、非零退出或强制回收都会形成 typed failure；只有 accepted + graceful zero exit 可写 backend receipt。
- local descriptor/contract threshold 恢复权威 `0.9350569011196121`，测试直接绑定权威常量。tracked archive 明确保留 `formal-5` 历史低一 ULP 值及其仅记录 process reap 的旧 receipt 边界。
- 精确删除审查点名的两个 task-owned 私有临时目录和一个未完成 ledger 临时文件；复核 Plan 097 根无同类前缀残留。

## 验证与边界

- 受影响四文件单元回归 39/39；全部 Plan 097 Python 单元回归 51/51；JSON 解析、Python compile、`git diff --check` 通过。现有 formal 两份 backend receipt 的 Producer identity 也与当前 runtime projection 离线等值复核通过。
- 未运行付费 API、Producer、真实本地模型、Cargo、Docker 或全 workspace。按审查决定原样保留 `plan097-formal-5` raw receipts 和累计保守总账 `21.4197186 RMB / 30 RMB`，未伪造旧 run identity。
- `doc/WBS-COMPLETED.md` 未修改；当前状态为 `REMEDIATION_COMPLETE / RE_REVIEW_PENDING`。
