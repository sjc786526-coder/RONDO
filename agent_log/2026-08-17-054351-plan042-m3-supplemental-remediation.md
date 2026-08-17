# Plan 042 / Multi M-3 补充整改

日期：2026-08-17 ｜ 整改基线：`95ef17d` ｜ 实现提交：`eb53218`

## 结果

第三轮独立复验报告的三项残余缺陷已在 042 worktree 内补修；未引入 artifact store、签名链、复杂 ACL、
provenance graph 或新审计设施。当前实现完成并通过定向门禁，等待再次独立复验；尚未合并或推送。

## 实质修改

- Harness 在直接工具 dispatch 前预留唯一 output item identity；完成 note、host 丢弃时撤销、retention 确认与最终
  locator 共用该身份。`call_id` 只保留为元数据，因此同一响应内并行复用 call ID 时不会漏 Fact 或错配
  tool/category/observation。
- 删除固定 256 条 pending 逐出。pending 仍只承载“工具完成到有序 retention”之间的轻量 metadata，确认后移除，
  被 host 丢弃时按唯一 item identity 精确撤销；正式保留的支持集结果不再因暂存计数被静默丢弃。
- `team_history` 新增 `evidence_refs_offset`；每个返回 Version 的单页仍最多 32 条，并返回当前 offset、下一页 offset
  与页后余量。canonical Version 仍保存全部 refs，Agent 可有界走到第 33 条以后，不需要猜 Fact ID。
- 新增一个合并产品纵切：单次响应发出 33 个真实本地文本工具调用，前两项复用同一 call ID 且一成一败；验证两项
  各自形成准确 Fact/下钻文本，并经 history offset 取得第 33 条引用。

## 定向门禁

- `just test -p codex-team-state evidence`：23/23。
- `just test -p codex-core team::evidence`：6/6。
- 新增重复 call ID + refs 分页产品纵切：1/1。
- M-1/M-2、其余既有 M-3 产品链与 `tools::parallel` 合并定向：19/19。
- `just fix -p codex-team-state -p codex-core`、`just fmt`、`just fmt-check`：通过。

Rust 门禁均走共享构建锁/cgroup 看门狗；core loopback 测试按既有环境约束清空代理变量。未重跑先前的 541 条合并
门禁或全 workspace 测试，也未运行 Docker、真实 API、本地模型或付费测评。

首次未提权的 test 入口因沙箱无法连接 cgroup 总线而按规则 exit 81，未进入编译；随后只通过仓库规定的共享看门狗
入口运行。首次 `just fmt` 的 Rust 部分执行后，两个无关 Python formatter 因用户级 uv cache 只读失败；改用 worktree
内 ignored `UV_CACHE_DIR=.uv-cache` 后通过，没有修改宿主配置。

## 决策

- 沿用复验代作决策：接受 session 内 `ResponseItemId` locator；此次把同一 identity 前移到 dispatch 前预留，兼作
  completion/retention 配对键，不要求跨重放同值。
- 保留 32 条单次模型输出上限，并用现有 `team_history` 的窄 offset 参数完成 refs 分页；不新增通用浏览或审计工具。
- 不保留任何会丢正式 observation 的 pending 固定截断；暂存仍只含轻量 metadata，不复制工具正文。
- PostToolUse 已执行后的最终失败文本继续纳入；未知工具与 PreToolUse 等执行前拒绝继续排除。

执行者未留下其他需要用户选择的产品问题。合并、推送和分支归档仍等待用户批准。
