# Plan 014 运行后合同收口

日期：2026-08-11

## 结论

审查报告中的预算 reservation/overage、stopped run 发布、Docker lease、v19 可重跑入口、并发 deadline、
Guardian claim/reserve、meta 组合、public evidence 路径、S2 证明强度、cleanup deadline 与 secret scanner 问题均可复现。
v19 的双侧 completed/reward 1、35 次一次成功请求、M1 passed 与费用事实保持有效；没有改写其 lock、result、ledger、
artifact，也没有重新发起付费请求。

## 实现

- 正式 proxy 按 role 价卡计算合法 usage envelope 最坏费用；当前 Sol 为 `$18.885000`。显式短测发生合法 usage
  overage 时保存完整估价，以 `usage_priced_overage` 停止，账本只允许精确 overage delta。技术上限允许新的
  Sol/Sol pair 为短暂重叠的 main/Guardian 预留 `$37.770000`/side；实际授权仍必须由新 lock 收窄。
- handler 在 lifecycle lock 内、`begin_attempt/open` 前重算 deadline；claim 与 reserve 在同一 policy lock 内提交，
  reserve 失败不消费 Guardian body SHA/计数。
- completed producer、paid slot 与 M1 共用未停止、零 reservation、全 settled/usage-valid/usage-priced 的预算合同，
  并核对 budget/API metadata 的精确 request ID 集合。
- v8—v19 使用统一 historical registry；v19 仅只读，paid CLI 与 Plan 014 canary 在配置、密钥、账本、Docker/API 前
  因无 active identity 而拒绝。
- Guardian meta 只接受生产合法终态组合；归档公开路径改为 `guardian-evidence/000N/E_final.json`。后续 S2 将
  canonical E_final digest 与 proxy Guardian request digest 唯一一一绑定；v19 旧记录降格为
  `task_scoped_count_match`，M1 仍 passed。
- Docker counter 成功返回前重验 watchdog lease；cleanup 全流程共用 30 秒绝对 deadline，kill 后 bounded wait/reap。
  scanner 移除全局 `user_authorization` 豁免，只在精确 Guardian schema 枚举位置中性化该键。

## 验证

- 预算代理定向回归：50/50；结果、pair、Docker、scanner 与 CLI diagnostic 回归均纳入完整套件。
- dependency lock：85 packages。
- 完整 pure/fake/loopback eval：349/349，58.590 秒。
- v19 现有两条 public record + pair/budget ledger 只读重放：
  `m1=passed`、`reasons=[]`、`s2=task_scoped_count_match`。
- `git diff --check` 通过。

本批未调用真实 API、Docker 或 Cargo，未读取 `.env.local`，未触碰共享历史数据。
