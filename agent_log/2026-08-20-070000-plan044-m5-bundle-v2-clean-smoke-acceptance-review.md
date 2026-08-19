# Plan 044 / M-5 bundle v2 与 clean smoke 验收审查

日期：2026-08-20
审查范围：`1992d57..fda60fe`（工程提交 `5ebaace`、记录提交 `fda60fe`）
结论：**验收不通过；本轮任务目标失败。**

这里的“失败”只指本轮完整目标没有闭合：`runtime-v2` 与两把 v3 门锁已经正确交付，
code-mode 明文修复也已由真实模型确认；但 clean smoke 未达成，且新发现一处会让正式门 1
读取到未最终结算账本的 P0。Multi M-5、门 1 均未通过，门 2 未启动，不存在“未见退化”结论。

## 审查发现

### P0：门 1 在预算代理排空前判定并归档，尾部请求可在“通过”之后补出 taint

`run_gate1_paid()` 与 `run_gate1_smoke()` 都在 `with proxy:` 内调用 `_run_gate1_once()`；
后者在返回前立即读取 `run_stop_reason`、`infra_taint`、`exposure_summary`，生成 verdict 并持久化归档。
Python 随后才退出 `with proxy:`，预算代理此时才排空仍在运行的 handler。

`cs2` 已经给出实证，而不是理论风险：

- 已归档行：`request_count=35`，但 `budget_exposure.settled_requests=34`、
  `charged_usd=9.286679`；
- 代理关闭后的最终账本：同一 run 有 35 个 settled request、`spent_usd=9.297763`；
- 差额 `$0.011084` 正好是最后一个请求的结算。

本次最后一笔恰好带有效 usage，所以 `infra_taint.count` 仍是 4；若尾部请求改为流内
`server_error`，归档就可能先写成无 taint / `completed`，最终账本随后才出现 taint。
这会直接制造正式门 1 的假通过，属于发布阻断。

修复要求：先让 proxy 明确 drain/close，再读取 stop、taint、exposure，最后判定、归档和决定
CLI 退出码。可拆成“运行采集”和“账本最终化”两段，或增加可验证的 idle/drain 屏障；必须补一条
定向回归，让最后一个请求在 agent 进程退出后才完成，并断言归档与最终 ledger 完全一致且尾部
taint 能否决 apparent pass。

### P1：`member_message_delivery` 没有证明“成员收到 Root 的明文任务”

`collect.py::member_message_delivery()` 会统计捕获中所有 `agent_message`，不看 `author`/消息方向；
同时把任何不含 `encrypted_content` 的字典都计为 plaintext，而不要求
`type=input_text` 且 `text` 为字符串。

轻量复现：只放一条 `author=/root/worker`、发往 Root 的 `input_text`，函数仍返回
`status=plaintext`。因此成员未收到任务时，Root 收到的普通消息也能满足该机器判据；反过来，
Direct 路径合法送给 Root 的 encrypted 消息也可能把本来正确的成员投递误报为 encrypted。

修复要求：本载体只有 `/root` 与一个成员，判据至少只统计 `author=/root` 的 `agent_message`，
只把结构正确的 `input_text` 计作明文；未知 part 应 fail-closed/单列 unknown，不能默认算明文。
补“成员→Root 不算”“未知 part 不算”“双向混合不互相污染”三类窄回归即可，不扩建设施。

### P2：clean smoke 仍追加到旧 `code-mode-smoke-records.jsonl`

本轮只给预算账本换成了 `multi-m5-clean-smoke.json`，但
`SMOKE_ARCHIVE_RELPATH` 仍是旧的
`eval-data/multi-m5/archives/code-mode-smoke-records.jsonl`。现场文件前四行是旧 bundle 的
`cm1..cm4`，第五、六行已经追加新 bundle 的 `cs1..cs2`。行内 lock/batch id 尚能区分，
所以没有污染正式门判定；但“旧归档一字节未动”和“clean smoke 独立归档”两项交付陈述不成立，
后续按文件读取也容易把两批证据混在一起。

修复要求：旧文件从现在起只读；后续 clean smoke 使用独立 archive 路径。不要移动、重写或复制
既有六行来伪造历史分区，只需在日志勘误并让新 run 写新文件。

## 已确认成立的交付

- `multi-m5-runtime-v2` 指向源码 `6fe1379`，磁盘 bundle、manifest 与四项摘要通过
  `ready` 实际校验。
- `multi-m5-workflow-v3` / `multi-m5-nondegradation-v3` 均显式引用 runtime-v2；
  endpoint、terra root/member、medium effort、2 秒退避、正式
  `unpriced_stop_threshold=1` 与 `any_unpriced_invalidates_observation=true` 已冻结。
- 门 1/门 2 的退避均从 M-5 自己的锁读取，未改宿主全局 alias。
- `cs2` 足以确认产品修复成立：新 bundle 下成员收到的捕获形状为 plaintext，成员完成回合并从
  code cell 发出团队工具调用。它不满足 zero-taint，且没有 `team_inspect`，所以执行者拒绝据此
  判断 terra 协议遵循、Direct fact 风险或门 1 通过，这个结论是正确的。
- 最终 clean-smoke 账本扣减为 `$11.517763`（报告四舍五入 `$11.52`），其中按 usage 计价
  `$0.417763`（报告 `$0.42` 属正常近似），正式 `$120` 账本仍不存在。
- 独立轻量复验：`tests.test_multi_m5` + `tests.test_multi_m5_exec` 102/102，
  `tests.test_multi_m5_trace_evidence` 21/21，合计 123/123；`just eval-lock` 通过；
  `ready=true`。未重跑无关全量或重型 Rust 测试。
- 写本报告前，044 工作树受跟踪文件干净；主工作区 `main=origin/main=45efac6` 且干净；
  两个交付提交未合并、未推送。

## 代用户作出的决定

### 最后一次 clean smoke：保留 zero-taint，当前选择 C，但不立即下注

1. **不采用 B。** `taint != 0` 表示至少有一次请求没有取得可计价的完整响应；成员后来完成回合、
   trace 绑定正确，只能证明产品修复生效，不能把整轮升级为干净证据。zero-taint 标准保持不变。
2. **不按当前描述直接采用 A。** HTTP 200 只说明响应头已成功，SSE `server_error` 到来前可能已有
   model-visible 事件被转发，也不能从 `usage=null` 推导 provider 明确不计费。把它直接塞进
   “unbilled retry”白名单会同时带来重复输出、重复费用和把有故障运行洗成 clean 的风险。
3. **采用 C 的保守版本：先修本报告三项，保留最后一次付费机会，等待 relay 修复/恢复稳定后再跑。**
   在此之前不再花钱，也不启动正式 Gate 1/2。若 relay 无法恢复，下一选择应是单独冻结一个稳定
   endpoint，而不是放宽证据标准。
4. 如果将来确有机器可绑定的 provider 证明，确认特定 SSE `error/server_error` 在“无 usage、
   无任何 model-visible item 下发”时可安全且不计费，才允许把它设计成窄重试并重冻 provider 合同；
   不能用本次现象自行推导该保证。

### 最后一跑的身份与额度

修复完成且 relay 状态恢复后，只授权 **1 次**最终 clean smoke：

- 使用全新的 `multi-m5-clean-smoke-v2` lock/batch/archive 身份；
- 单 run cap 仍为冻结公式算出的 `$23.10`，不得重开三次额度；
- `cs1/cs2` 与旧 `cm1..cm4` 保持原样，只在日志勘误，不迁移、不重写；
- 仍须同时满足：最终 ledger 与归档一致、zero taint、`conservative_exposure_usd=0`、
  成员收到 Root plaintext 任务并完成至少一次工具调用、trace 绑定无误；
- 成功后才评估 instruction/terra，再决定是否启动正式 Gate 1；门 1 通过后才进门 2。

这一次仍落在用户既有 `$500` 冒烟授权内，但上述 `$23.10` 是本入口的实际硬上限，不把授权上限当消费目标。

### 构建残留

允许在确认没有构建进程、runtime-v2 已验证且无需再重建后，清理本任务自建的精确路径
`.claude/worktrees/044-m5-multi-bundle-measurement-v2/multidev/codex-rs/target`。
不得顺带清理其他 target、缓存、bundle、worktree 或来源不明对象。

## 当前状态与下一步

- **验收状态：不通过。**
- **本轮任务目标：失败。**
- **项目状态：M-5 未通过；门 1 未通过；门 2 未启动。**
- 下一步只做三项窄修与对应回归，更新本报告所指出的归档勘误；不要改模型、instruction、
  zero-taint 或正式两门合同，不调用 API/Docker。修复验收后等待 relay 稳定，再按上述单次 v2 身份执行。
