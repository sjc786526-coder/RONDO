# Multi 阶段一空间门：只读盘点与经授权释放

日期：2026-09-02（操作时间戳为 UTC 2026-09-03T03:44–03:45Z）
依据：`doc/WBS.md` §1「产品线配套补齐与逐条收口」的**全量前空间门**
基线 commit：`b943fd00`（本地 `main` 与 `origin/main` 一致，工作区干净）

Plan 104（Multi M-1/M-2/M-3）完成并推送后的下一工作包。本次只处理构建缓存与工作树残留，
**不改任何产品代码、默认值或测试语义**，不解锁任何方向。

## 授权

空间门规定 AI 默认只读盘点、不得自行删除，任何释放须用户针对明确对象另行授权。
本次用户明确批准了下列精确对象，随后追加批准释放遗留工作树：

- `.codex/cargo-target/rondo-multi/debug/incremental`
- `.codex/cargo-target/rondo-local/debug/incremental`
- `.claude/worktrees/106-multi-product-support`（追加）

未获批准的对象一律未动。

## 操作前后占用（实测）

删除前确认：无 `cargo` / `rustc` / `rust-lld` / `nextest` 进程，工作区干净。

| 对象 | 前 | 后 | 释放 |
|---|---:|---:|---:|
| `rondo-multi` 叶子 | 164,171,576,249 B（152.9 GiB） | 110,598,444,311 B（103.0 GiB） | 53,573,131,938 B |
| `rondo-local` 叶子 | 20,628,683,184 B（19.2 GiB） | 10,308,086,023 B（9.6 GiB） | 10,320,597,161 B |
| 项目总计 | 232,758,952,201 B（216.8 GiB） | 168,653,975,171 B（157.1 GiB） | 64,104,977,030 B（59.7 GiB） |
| WSL `/` 已用 | 277 GiB | 217 GiB | 60 GiB |
| Windows `C:` 可用 | 109,840,207,872 B（109.8 GB） | 109,839,622,144 B（109.8 GB） | 不变 |

两个 incremental 目录单独测得 54,907,828,213 B 与 10,805,600,791 B，略大于父目录的实际减少量
（差约 1.24 GiB / 0.49 GiB）。原因是 `du` 对硬链接只计一次：这部分字节仍被 `deps/` 引用，
删除 incremental 并不释放它们。以父目录前后差为准。

**Windows `C:` 不变是预期行为**，不是测量错误：WSL 的 ext4 vdisk 只增不减，删除只是把空间还给
ext4 内部供后续写入复用，不会回缩到宿主。这正是本次释放的目的——让 Multi 全量的 target 增长
落在已分配的 vdisk 内，从而完全不触及 `C:`。

## 保留对象与理由

- `rondo-multi/debug/deps`（95.6 GiB）、`.fingerprint`、`build`：这是"热"缓存本体。
  `multidev/codex-rs/Cargo.lock` 共 1349 个 package，其中仅 134 个是 workspace 成员，
  其余约 1215 个第三方 crate 的编译产物在此。WBS 明确「禁用 incremental 不表示清空 target
  或进行零缓存冷构建」。
- `rondo-local/debug/deps`（8.6 GiB）：阶段二 Local 全量会复用。
- **整个 `.codex/cargo-target/rondo-multi` 未删**：按 WBS 路线，该叶子的删除是 **Multi 发布之后**
  的步骤，目的是为阶段二 Local 全量腾容量，且届时仍须单独授权。

## 支撑本次判断的实测证据

在 `$CLAUDE_JOB_DIR/tmp` 建玩具 crate（两个第三方依赖 + 一个本地 crate）验证，实验后已清理，
未触碰 RONDO 的 target：

| 操作 | 结果 |
|---|---|
| 翻转 `CARGO_INCREMENTAL=0` | 只重编本地 crate；两个第三方依赖未重编 |
| 删除 incremental 后以 `INCREMENTAL=0` 重编 | 目录被重建但 **0 字节 / 0 条目**（纯占位） |
| 对照：默认模式改一行源码 | incremental 目录 803 KB（单文件 crate） |

结论有二：其一，本次释放在 `CARGO_INCREMENTAL=0` 下是**永久的**，全量跑不会把这 51 GiB 长回来；
其二，第三方依赖 fingerprint 不受该开关影响，`deps/` 的主体会命中。

workspace 成员 crate 仍会大面积重编，但那是因为 `config_toml.rs` / `core/src/config/mod.rs`
自 Plan 093 基线以来真的改过、而 `codex-core` 在依赖图底层，与是否保留缓存无关。

同期核对：`Cargo.lock` 自 Plan 093 基线以来仅新增 `codex-publication-critic` 对
`codex-http-client` / `url` / `wiremock` 的依赖声明，三者均为既有 workspace 依赖，
**无任何第三方版本变化**，不构成第三方产物失效。

## 空间门结论

以 `test-with-codex-v8-conservative`（`CARGO_BUILD_JOBS=1` + `CARGO_INCREMENTAL=0`）跑 Multi 全量：

- 预期峰值约 145 GiB（Plan 093 的 183.2 GiB 峰值扣除增量部分，并为 multidev 自基线以来的增长留量），
  自当前 103.0 GiB 增长约 42 GiB；项目落在约 213 GB，远低于 350 GB 告警线。
- WSL 已用从 217 GiB 升至约 259 GiB，仍低于 vdisk 已占的 277 GiB，**`C:` 预期全程不变**。
- 悲观情形（峰值 183 GiB）下 `C:` 约降至 88 GB，仍高出 50 GB 停机线 38 GB。

**空间门通过。** 下一步是 Multi 全量测试，由用户安排时机并批准。

## 未处理 / 需注意

- 本次**未改 `doc/WBS.md`**。空间门完成属于 WBS 的「下一工作包」范畴，但同期存在活跃工作树
  `.claude/worktrees/107-multi-full-workspace-closure`，按 §4.3「WBS 等共享权威文件尽量在同一时段
  由一个任务负责」，交由承接全量测试的任务一并更新，避免并行覆盖。
- 遗留工作树 `106-multi-product-support`（243 MB）删除前已确认工作区干净、分支
  `zz-done/worktree-106-multi-product-support` 已并入 `main`；分支本身保留为历史。
