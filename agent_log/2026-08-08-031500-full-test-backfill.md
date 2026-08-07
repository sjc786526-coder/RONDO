# 补跑 P0 遗留的全量 `just test`

上一批次（`agent_log/2026-08-07-233100-p0-guardian-override-and-evidence.md`）因 OOM 风险把全量门禁
标为「未运行，不声称通过」。本次在新落地的资源闸门下补跑，只跑测试、不改它的代码，也不改它的日志。

## 实质改动

代码零改动。文档两处：

- `doc/WBS-COMPLETED.md`：追加 2026-08-08 条目，记录闸门与本次全量结果（追加式，不改上文历史）。
- `doc/development-environment.md` §8：把「工作区完整 `just test` 未执行」更新为已执行及其结论。

## 结果

```text
Summary [346.676s] 13135 tests run: 13062 passed (8 slow, 25 flaky), 73 failed, 23 skipped
```

资源侧（每 3 秒采样，全程）：已用内存约 3.8 GB、可用约 24 GB、scope 内峰值约 5 GB、swap 未增长，
**无 OOM、无退出码 137**。构建阶段因产物已热，几分钟内完成；执行阶段 346.7 s。闸门在真实全量负载下有效。

值得记一笔：执行阶段 scope 内只用了约 5 GB，说明 `test-threads = 10` 远不是瓶颈，
内存压力确实全在编译链接阶段——和 §3.5 的判断一致。

## 73 项失败的定性

先排除两种「是我们自己的问题」的可能：

1. **不是并发改动引起的。** `codex-tui` 用 `--test-threads 1` 串行重跑，失败项与并行运行完全一致
   （同为 33 项）。
2. **不是 RONDO 回归。** `tui` / `network-proxy` / `mcp-server` / `exec` 四个失败最集中的 crate，
   在本仓库历史里只被两次基线导入提交（`0fe9217` v0.146.0 初始化、`102ec27` 升级到 v0.146.1）碰过；
   P0 提交 `95d3358` 只改了 `config/`、`core/config`、`core/guardian`、`core/client.rs` 及其测试。
   名字含 guardian / auto_review / evidence 的 36 项测试中 35 项通过，唯一一项
   （`codex-tui status::tests::status_snapshot_shows_auto_review_permissions`）失败原因是快照里的
   版本号字符串，与审批逻辑无关。

两个已证实的系统性根因：

| # | 根因 | 项数 | 证据 |
| - | ---- | ---- | ---- |
| ① | 版本号占位 `0.0.0` → `0.146.1` | 25 | 上游快照/断言内嵌 `0.0.0`；RONDO 把 132 个工作区包钉为 `0.146.1`（见 §3.4），例如 mcp-server 的 `serverInfo.version` 断言与 tui 的 `OpenAI Codex (v0.0.0)` 快照 |
| ② | Clash Verge fake-IP DNS | 11 | 宿主把**所有**域名解析到 `198.18.x.x`（`example.com → 198.18.0.88`，连 `nonexistent-xyz-test.invalid` 都解析成功）。`198.18.0.0/15` 是保留段，codex 网络代理正确判定为私有地址，返回 `403 blocked-by-allowlist` / `not_allowed_local` |

其余 37 项：本地 mock 服务/超时 8、其他快照差异 12、其他 17。按本次任务范围（只补跑、不修复）未逐项定位。

## 疑难问题与处理

1. **代理环境变量不是 ② 的原因。** 先怀疑 `~/.bashrc` 里的 `http_proxy` / `all_proxy` 泄漏进测试，
   用 `env -u http_proxy -u https_proxy -u all_proxy ...` 重跑 `codex-network-proxy`，失败依旧。
   改查 DNS 才定位到 fake-IP。**没有停在猜测上**这一步是必要的，否则会得出错误结论。
2. **`junit.xml` 会被后续定向重跑覆盖。** `[profile.default.junit] path = "junit.xml"` 是固定文件名，
   我跑完全量后又跑了 `-p codex-tui`，`target/nextest/local/junit.xml` 就只剩 33 项了。
   最终统计改为直接解析全量日志，并按测试名去重（nextest 会在行内和末尾汇总各打印一次失败块，
   不去重会得到 146 这个双倍数字）。以后要留证据，跑完全量应先把 `junit.xml` 另存。

## 验收结果

- 全量 `just test` 已实际跑完，结果如上，**73 项失败如实记录，不声称全绿**。
- 未修改任何被测代码，未修改上一批次的日志。
- **仍未运行**：Bazel 门禁与 `just argument-comment-lint`（本机未装 Bazel，见
  `doc/development-environment.md` §8）。
- 本次未调整任何并发配置——因为没有崩，`jobs = 6` / `test-threads = 10` / 16 GiB 上限均未触发。
- 全程离线，未调用真实模型 API。
