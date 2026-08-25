# Plan 074 persisted cwd read consistency 实施记录

## 实质变更

- ThreadStore read-by-ID/read-by-path 在 lineage 可证明且 cwd 为绝对路径时优先投影 persisted cwd，并按该 cwd 重新推导 legacy permission；
  read-by-path 的整份 SQLite metadata 只有在 canonical rollout path 精确匹配时才合并。
- 空/相对 cwd 只回退到同 ID SessionMeta 的绝对 cwd；state-only list 无独立 rollout 验证时明确报错，避免 app-server 用进程 cwd 伪造持久值。
- app-server 回归同时验证 cold read/list 的 persisted projection 与 resume live cwd/workspace-roots override 分离。

## 验证证据

- `codex-thread-store`：190/190，通过；watchdog `20260825-015831-1000-1874250`，JUnit SHA-256
  `7c8350d83b62f5d7980fa518c131e4b0df1b1a435afd945e0d154b7c4a502f53`。
- 最终 fresh-fixture 聚焦轮：3/3，通过（resume 首试仅初始化超时、自动重试通过）；watchdog
  `20260825-020911-1000-1953582`，JUnit SHA-256 `8fdb9ed71d5940d26bf658695e33d92326b495b1b59413fdbb76c6f7fb8ac5b6`。
- resume 单独复验：1/1，无重试通过；watchdog `20260825-021157-1000-1973327`，JUnit SHA-256
  `32bd06f1ade1baa6b33000d4608922196d73623490c0d544edc2c767d9abc015`。
- `codex-thread-store` clippy、`just fmt`、`git diff --check` 通过；clippy watchdog `20260825-021042-1000-1965559`。
- 独立审查 finding 修复复验：ThreadStore 1/1 与 clippy 通过；watchdog `20260825-021852-1000-1993447`（JUnit SHA-256
  `56993eb51385d3fa0b0fad6558f7c1ee65326c7bfc7c9e8ffeddf16c9a5e8419`）及 `20260825-021911-1000-1994951`。

## 独立复核

- 上下文独立审查首轮发现 1 项中等级问题：同 lineage 的空/相对 cwd 回退后，path-read 没有按最终 cwd 重算 legacy permission。
- 已改为 matching lineage 下始终使用 persisted sandbox metadata 与最终 cwd 重算 permission，并为两种异常 cwd 增加 ID/path permission 等值及
  helper 结果断言；同一审查者复验 `ACCEPT`，无剩余高/中 correctness finding。

## 未通过/未运行

- 069 相邻 core cold-resume 测试两次均在未修改的 mock sampling 链因 `/v1/responses` 第五次请求返回 502 后超时；无 074 cwd 断言失败。
  证据：watchdog `20260825-020225-1000-1911375`，JUnit SHA-256
  `9d9bf1178f9e44b32ed63faff33423fd54c082359b2acc1300fe7cf3c52f2275`。
- app-server 联合 clippy 被未修改 core 的 `await_holding_invalid_type` 既有错误阻断；074 自身唯一折叠-if 告警已修复并由 ThreadStore clippy 复验。
- 按授权未运行全 workspace、Docker、真实模型/API、CI/PR，未执行 069 阶段 E，未合并、rebase 或 push，未更新共享 WBS。
