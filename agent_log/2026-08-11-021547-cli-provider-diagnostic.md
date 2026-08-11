# 配置化 Provider 的真实 CLI 诊断

## 范围与结论

- 在独立 worktree `0811-luna-provider-diagnostic` 中修正 synthetic probe 与真实 Codex/RONDO Responses
  请求的偏差，并增加受预算约束、仅保存去敏事实的真实 CLI 诊断入口；冻结 Codex 源码和二进制均未修改。
- 用户关于 Luna 的判断正确：中转可完成 Luna 主模型和审批模型。修正请求形状并加入指数退避后，冻结 Codex 与
  RONDO 的 Luna main/Guardian 均完成。随后只运行 RONDO，Sol main + Sol/low Guardian 也完成
  `main → guardian → main` 审批闭环。
- 中转仍不稳定：同批活动观察到 403、429、503 和 HTTP 200 但 usage 无效。Terra 在短测中持续 403；不能把
  任一失败继续归因于 Luna 或 Guardian 不受支持，也不能用一次成功证明 provider 已稳定。

## 实质修改

- `provider_probe.py` 与真实 CLI 对齐：非 Azure Responses 使用 `store=false`；Guardian format 名为
  `codex_output_schema` 且 `strict=false`。
- loopback proxy 仍在本地消费并校验 `X-RONDO-Eval-Role`，但不再把这个项目私有 header 发给上游。
- 新增 `model_cli_diagnostic.py`：固定 runtime-bundle identity，显式选择 main/Guardian alias，复用 ignored
  本地 profile/密钥。短测对每个 upstream request 预留 1 USD，正式/大请求继续沿用 5 USD；receipt 只保存角色、
  usage 结算、二进制 identity、命令哈希/状态和精确最终消息判定。临时 `auth.json` 与每次启动自动生成的
  plugin/clone cache 在 `finally` 中删除。
- 冻结 Codex 不改源码：从与 bundle source commit 一致的本地只读 `models.json` 生成最小
  `model_catalog_json`，用 Sol 条目的 `auto_review_model_override` 把审批模型显式覆盖为 Sol；RONDO 继续使用
  自身 `[auto_review]` 配置。catalog 投影与 SHA 均进入去敏 receipt。
- 诊断专用重试允许按任务授权重复未知计费失败；生产 paid pair 的未计费重试合同未放宽。

## 真实请求与预算

以下均为本地保守借记，不是供应商账单；中转未提供可核对的实际费用，全部保持 `actual_usd=null`。

- 第一笔 300 USD Luna 授权：保守借记 `270.126309` USD。
- 第二笔 300 USD Terra+Sol 授权：保守借记 `235.500063` USD。
- 第三笔 600 USD 修复/复测授权：保守借记 `285.230585` USD，包含：
  - frozen Codex direct Luna control：`135.000000`；
  - 修正 proxy 后 Luna v9/v10（含中断 reservation 恢复）：`85.080955`；
  - Terra 短测：`30.000000`；
  - Sol main + Luna Guardian 中断短测：`25.011921`；
  - 仅 RONDO 的 Sol main + Sol Guardian 短测：`10.137709`。
- 三笔授权累计本地保守借记 `790.856957` USD，分别未超过 300/300/600 USD 硬上限。

最新 RONDO Sol/Sol 短测中，main 首次成功并按 usage 结算 `0.040449` USD。审批共运行 5 个 CLI process
（4 次重试）：前两次各按未知计费保守结算 5 USD；中间两次审批拒绝并按有效 usage 结算；最后一次得到
`main → guardian → main` 三个有效 usage 结算、命令完成、marker 存在且最终消息精确为 `DONE`，按 usage
结算 `0.041214` USD。campaign 最终 `completed`，无活动 reservation。

## 验收与边界

- `test_model_cli_diagnostic + test_provider_probe + test_api_budget_proxy + test_config_hardening`：62/62 通过；
  其中独立 `PersistentBudgetLedgerTests` 5/5 通过。
- 相关 Python 文件 `py_compile` 通过，`git diff --check` 通过。
- 完整 provider/proxy 本地回环套件的提权审批因自动审查 stream disconnected 被拒；随后在默认沙箱和显式
  loopback `NO_PROXY` 下直接完成相关套件，不需要提权，也没有外部请求。
- `.env.local` 只静默检查为非符号链接、普通文件、权限 `0600`、非空；未打开、搜索、打印或修改。最新输出目录
  无临时 `auth.json`、无活动 reservation。ignored active profile 当前为 relay + Sol main + Sol Guardian/low。
- 精确清理本任务 50 个 `plugins` 与 36 个 `plugins-clone-*` 临时目录，约释放 5 GB；receipt、ledger、session
  和命令证据均保留，可由后续运行重新生成这些 cache。
- 未运行 Docker、Cargo、Terminal-Bench paid pair 或 M1；未合并、未推送。

## Sol/Sol 最终稳定性短测

- 在同一 active profile 下连续运行 3 轮，每轮依次执行 frozen Codex main、frozen Codex approval、RONDO main、
  RONDO approval；关闭 proxy/SDK 外层重试，任何单轮失败都会停止，不用重试把偶发失败洗成成功。
- 三轮均 completed：24/24 个 upstream request 的 effective model 都是 `gpt-5.6-sol`，Guardian effort 为 low、
  main effort 为 medium；每个 request 的 `attempt_count=1`、usage valid、settlement 为 `usage_priced`。两端审批链
  均为 `main → guardian → main`，命令退出 0、marker 存在、最终消息精确为 `DONE`。
- 三轮本地价卡估算依次为 `0.394750`、`0.412640`、`0.427083` USD，合计 `1.234473` USD；实际供应商账单
  未查询，继续保持 `actual_usd=null`。这证明当前短窗口内 Sol/Sol 稳定性良好，但不替代 Plan 014 的新 pair、
  Docker 与 M1，也不对未来中转可用性作永久保证。
