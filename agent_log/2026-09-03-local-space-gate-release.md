# Local 阶段二空间门：只读盘点与经授权释放

日期：2026-09-03
依据：`doc/WBS.md` §1「产品线配套补齐与逐条收口」的**全量前空间门**
基线 commit：`7569f48c`（本地 `main` 与 `origin/main` 一致，工作区干净）

Plan 107 合入、推送、Local 轻量 CI 全绿之后的下一工作包。本次只处理构建缓存与已合入工作树，
**不改任何产品代码、默认值或测试语义**，不解锁任何方向。

## 授权

空间门规定 AI 默认只读盘点、不得自行删除。本次用户在看过只读盘点结论后，明确授权：
先归档各工作树再关闭释放（前提是确认相关资产已在主工作区），随后释放
`.codex/cargo-target/rondo-local/debug/incremental`。未获批准的对象一律未动。

## 只读盘点结论（操作前）

| 项 | 实测 | 门限 |
|---|---:|---|
| 项目总占用 | 79,619,213,646 B（79.6 GB） | 告警 350 / 主动停 365 / 绝对停 370 GB |
| Windows `C:` 可用 | 118,874,439,680 B（118.9 GB） | 低于 50 GB 停止 |
| WSL `/` 已用 | 145,769,644,032 B | — |
| WSL `ext4.vhdx` 已分配 | 438,817,521,664 B（438.8 GB） | 只增不减；额度内增长不触及 `C:` |
| `rondo-local` target | 31,499,597,846 B（31.5 GB） | — |

`ext4.vhdx` 已分配 438.8 GB 而 WSL 实际只用 145.8 GB，意味着约 293 GB 的增长落在已分配区内，
**不会回吃宿主 `C:`**。这是判断本次门禁能否通过的关键量。

## incremental 为何重新出现

Plan 108（Multi 空间门）已删过 `rondo-local/debug/incremental` 并释放 10.32 GB，本次盘点却又见到 11.7 GB。
查证结论是**重新长出来的，不是当时漏删**：

- incremental 下 137 个条目的 mtime 全部落在 2026-09-03 03:14–03:48，删除时刻
  （2026-09-02 20:44 本地 / UTC 03:44）之前**零残留**；作为对照，`deps/` 有 6556 个条目早于该时刻，
  正是当时有意保留的热缓存本体。
- 成因是 Plan 107 的定向门禁走 `just test -p codex-tui status::`。`mydev/justfile` 中只有
  `test-with-codex-v8-conservative` 设 `CARGO_INCREMENTAL=0`，普通 `test` 不设；justfile 自身注释即写明
  **“Daily narrow entries leave incremental on.”**
- 因此这是**设计行为而非失误**，Plan 107 的入口选择符合 justfile 指引。`codex-tui` 位于依赖图顶端，
  编它等于过一遍整个 workspace，137 个成员各落一份 incremental，故体量甚至略大于被删的 10.32 GB。

**运维含义**：删一次不能一劳永逸。全量之后若还有定向复验（Plan 105 在 Multi 侧即因此涨了 20 GB 并二次授权删除），
它会再长一轮。需要避免时必须显式用 conservative 入口或前置 `CARGO_INCREMENTAL=0`。

## 资产核验（关闭工作树前）

两个工作树均：工作区干净、无 stash、无未跟踪文件、HEAD 经 `git merge-base --is-ancestor` 验证为 `main` 祖先
（`ahead=0`），即 tracked 内容已完全包含于 `main` 与 `origin/main`。

核验中发现一处**只存在于工作树的真资产**：`110-local-product-support/.codex/build-watchdog/` 下三次运行
（`.codex/` 为 git-ignored，故不随分支进入 `main`）。它们是 Plan 107 定向门禁的原始证据：

| 运行 | 内容 | rc |
|---|---|---|
| `20260903-031149-1000-616619` | 60 tests / 1 failure（接受快照前一轮） | 100 |
| `20260903-032013-1000-684164` | **60 tests / 0 failure（即 60/60 门禁轮）** | 0 |
| `20260903-034703-1000-745435` | 4 tests / 0 failure（整改后窄复验） | 0 |

已 `cp -a` 归档至主工作区 `.codex/build-watchdog/`（该目录原有 35 次运行，归档后 38 次），并双重校验：
三份 `junit-local.xml` 的 sha256 与各自 `summary.env` 记录值一致，且与工作树原件 `diff -r` 逐字节相同。

其余被忽略产物为 `mydev/scripts/.venv`（28.3 MB）、`mydev/sdk/python/.venv`（27.9 MB）与两处 `.ruff_cache`，
均为可重建缓存，未归档。两个工作树内均无 `target/` 目录。

删除前另确认：无 `cargo`/`rustc`/`rust-lld`/`nextest` 进程；遍历 `/proc/*/cwd` 无任何进程位于工作树内；
`lsof +D` 无占用。

## 操作与实测占用

| 步骤 | 对象 | 前 | 后 | 释放 |
|---|---|---:|---:|---:|
| 1 归档分支 | `worktree-109-…` → `zz-done/worktree-109-…` | — | — | — |
| 2 关闭工作树 | `109-multi-v0.1.1-release-closeout`（151,469,700 B） | | | |
| 3 关闭工作树 | `110-local-product-support`（207,934,222 B） | | | |
| — | 项目总占用（步骤 2–3 合计） | 79,619,213,646 B | 79,256,264,018 B | 362,949,628 B |
| 4 释放缓存 | `rondo-local/debug/incremental` | | | |
| — | `rondo-local` target | 31,499,597,846 B | 19,776,751,973 B | 11,722,845,873 B |
| — | 项目总占用 | 79,256,264,018 B | 67,533,418,145 B | 11,722,845,873 B |
| **合计** | | **79,619,213,646 B（79.6 GB）** | **67,533,418,145 B（67.5 GB）** | **12,085,795,501 B（12.09 GB）** |

| 计数器 | 前 | 后 |
|---|---:|---:|
| WSL `/` 已用 | 145,769,644,032 B | 133,614,743,552 B |
| Windows `C:` 可用 | 118,874,439,680 B | 118,871,588,864 B |

`incremental` 单独测得 11,953,305,489 B，略大于父目录实际减少的 11,722,845,873 B，差 230,459,616 B。
原因与 Plan 108 记录的一致：`du` 对硬链接只计一次，这部分字节仍被 `deps/` 引用，删 incremental 并不释放。
**以父目录前后差为准。**

`C:` 可用基本不变（-2.85 MB，属采样噪声）是**预期行为**：WSL 的 ext4 vdisk 只增不减，
释放只是把空间还给 ext4 内部复用。这正是本次释放的目的——让 Local 全量的 target 增长落在已分配的 vdisk 内。

## 保留对象与理由

- `rondo-local/debug/deps`（18,597,803,773 B）：热缓存本体。`mydev/codex-rs/Cargo.lock` 共 1347 个 package，
  仅约 110 个是 workspace 成员，其余第三方 crate 的编译产物在此，`CARGO_INCREMENTAL=0` 下仍会命中。
- `eval-data/`（46.6 GB）：**全部保留**。该目录 git-ignored（`git ls-files eval-data` 为 0），
  且历史网络卷 `mwemzrn33y` 已删除，故为唯一副本、删除不可恢复。盘点已列出四个大头
  （`publication-critic/plan068` 13.8 GB、`bin/` 12.1 GB 的 9 个 runtime bundle、
  `local-approval/l6` 的两个 5.2 GB GGUF、`envs/publication-critic-plan068` 6.9 GB 可重建 venv），
  但本次门禁不需要它们，按“不可逆操作从保守”未申请授权。
- `.claude/worktrees/111-plan107-closeout`（151,528,394 B）：**未动**。它在本任务执行途中才出现
  （即推送 `7569f48c` 的 Plan 107 收尾任务），用户授权时尚不存在；虽干净、处于 `origin/main`、
  分支已是 `zz-done/`、无独有资产，但不排除并行任务仍挂着它，且其体量对门禁无影响。

已关闭的两个工作树，其分支均保留为 `zz-done/worktree-109-multi-v0.1.1-release-closeout`（`40e9b263`）与
`zz-done/worktree-110-local-product-support`（`b5d60311`），历史未丢。

## 空间门结论

以 `test-with-codex-v8-conservative`（`CARGO_BUILD_JOBS=1` + `CARGO_INCREMENTAL=0`）跑 Local 全量的预测，
锚定 Plan 105 的 Multi 实测（target 104 GB → 257.9 GB，项目峰值 320.3 GB，`C:` 全程未降）：

两条线依赖闭包几乎相同（Cargo.lock 1347 vs 1349 个 package，workspace 目录 110 vs 112），
但 Local 起点缓存仅 19.8 GB，远薄于 Multi 当时的 104 GB，命中率更低，故**终值同量级而增量更大**：

- `rondo-local` 预计涨到 230–260 GB，项目总占用落在约 **278–308 GB**，距 350 GB 告警线尚余 42–72 GB。
- WSL 已用由 133.6 GB 升至约 344–374 GB，仍在 vdisk 已分配的 438.8 GB 内，**`C:` 预期全程不变**；
  即便悲观越界，`C:` 现有 118.9 GB 也远高于 50 GB 停机线。

**空间门通过。** 下一步是禁用 incremental 的 Local 全 workspace 测试，由用户安排时机并批准。
余量不算宽裕，建议全量期间开启占用监控；若逼近告警线，可再针对
`eval-data/envs/publication-critic-plan068`（6.9 GB、按定义可重建）单独请示。

## 未处理 / 需注意

- 归档进 `.codex/build-watchdog/` 的三份 `summary.env`，其 `junit_path` 仍指向已删除的 110 工作树路径。
  为保持证据原样未做改写；判读时以所在目录为准。
- `.claude/worktrees/111-plan107-closeout` 保留，需要时由用户确认后另行释放。
