# Plan 077 Durable Session Query 执行日志

## 状态

`M4_C1_QUERY_REMEDIATION_PASS / LOCAL_COMMIT_COMPLETE`。正式 query 纵向链、相称回归、生成物、独立验收整改、最新聚焦正式轮、
scoped fix 和 077 本地提交均已完成；三路交叉复审未发现剩余高/中等级实现问题。workspace 非 077 阻断如实保留。

## 实现摘要

- 新增默认关闭且独立于 experimental API/control 的 `durable_session_query` feature，以及稳定 app-server v2
  `session/list` / `session/read`。
- state DB 只提供 bounded candidate locator；每个候选均通过 canonical Root `SessionMeta` durable marker、同一完整 checksummed
  committed Team snapshot 和 lineage/domain 校验后才形成正式 view。查询链不取得 writer authority，不 scan/repair/writeback，
  不 resume/load Session，也不启动 Agent、model、tool 或 control action。
- identity、storage、不可证明的 domain lifecycle、server-local residency、operation availability、provenance、read status、canonical
  commit generation、完整 snapshot fingerprint 和 Team revision 分轴表达。
- client 使用 connection/attachment/read ticket、whole-view replacement 和 stale 语义；list/read 共用 generation+fingerprint 高水位，
  并以独立于 Team 可用性的 client-local `Session -> Root` 轴保持已认证 identity。protocol apply 会先验证 request/response Session/Root、
  跨请求 canonical Root 稳定性、`Available <=> Team` 与 Team viewer 的 Root identity/role，再原子推进水位。切换其他 Session、
  list、detach/reconnect、错误 response 或换 Root 都不能把回退/同代异 fingerprint 标为 fresh。
- locator cursor 只保证稳定 keyset 排序，不冒充 source snapshot：cursor continuation 或单 RPC 内跨多个 locator page 时，server 保留
  bounded data/next cursor，但明确 `complete=false/sourceChanged`。
- TUI 的 `/sessions` 专用于正式 query；两个 gate 同开时，C0 经独立 `/session-control` 可达，仅启用 C0 时继续兼容旧 `/sessions`
  alias，不按参数形状或 parse failure 猜测路由。请求经 app-server client 后台执行，固定 15 秒 timeout、无 retry，迟到 completion
  经过 ticket 边界拒绝。四组正式 query snapshot 覆盖分页、健康 detail、损坏/身份不匹配、incomplete/unsupported、stale retained
  context，以及 Team authored 文本在 renderer 边界的单行化。

## `state/` 窄扩展

用户已明确批准以下四个文件仅服务于 read-only candidate locator：

- `state/src/model/thread_metadata.rs`：locator、双键 cursor、active/archive scope、page，以及 list/path lookup 的 typed error DTO。
- `state/src/runtime/threads.rs`：`CreatedAt DESC, ThreadId DESC` bounded SQL、空 preview 纳入、canonical UUID/毫秒时间解码、typed exact-path
  candidate lookup 和就近 fault-injection 回归。
- `state/src/model/mod.rs`、`state/src/lib.rs`：只导出上述 read-only 类型。

state DB 不证明 Durable Session/Team identity、lifecycle 或 committed state，也未新增 registry、cache、写回或 repair。

## 与 078 的共享文件

用户已批准两分支分别保留差异；077 未读取、复制或覆盖 078 内容：

- `core/src/team/durable.rs`：拆出 marker 已校验后的 read-only committed snapshot 入口，使 query 能分别保留 marker 与 snapshot
  typed failure。
- `thread-store/src/lib.rs`：导出 locator/meta query DTO 与 typed errors。
- `thread-store/src/store.rs`：为 store trait 添加默认 fail-closed 的 query-only methods。

后整合者应基于最新 main 加法收敛这些符号，保留 078 对 lifecycle/reload 的所有权，并执行 query + lifecycle 兼容验收；若出现
同一语义所有权竞争应暂停整合，而非让 077 预改 lifecycle 合同。

## 精确 write set 核对

最终分支 write set 共 109 个交付路径：`app-server-protocol` 41、`app-server` 9、`app-server-client` 3、`core` 5、`features` 2、
`state` 4、`team-state` 2、`thread-store` 10、`tui` 30、Plan 1、执行日志 1、独立审查报告 1。全部位于批准范围；没有
WBS、Cargo/Bazel manifest/lock、根 README 或其他 plan/log 差异。唯一 binary diff 是 schema generator 产生的 stable/experimental
app-server export 两个 `.json.zst`，可解压为合法 JSON；其余 JSON/schema 均通过只读 parse。没有删除项、`*.snap.new`、`*.rej` 或临时
备份文件。

## 已运行验证

- 独立验收整改正式轮（默认 features、dev/local profile、共享 069 target、`CARGO_BUILD_JOBS=2`、临时项目 270/285/290GB 门限）：
  `codex-thread-store`、`codex-app-server`、`codex-app-server-client`、`codex-tui` 的 8 个直接因果测试 8/8 passed、4838 skipped，
  JUnit SHA-256 `80d41f5afe70128ae9c3ae3855d2e975bb7e1b4c17c27ec53fe9f81db3543096`。覆盖 InMemory persisted seam
  fail-closed、app-server `SourceUnsupported`、非法 Team/readStatus/viewer 原子拒绝、双 gate 两入口及 popup gate、C0 usage/refresh
  提示和 authored 文本单行化 snapshot。此前生成 snapshot 的调试轮 6/6 passed，JUnit SHA-256
  `bd042bd9c5a363231b74f9f078a2c829d123bf498735a8dfc9bbe18a53fd6866`。
- 整改后四 crate 单批 scoped `just fix` 通过；只机械删除一个 077 TUI JSON fixture 的 4 个冗余 `Value::clone()`。随后 target-free
  `UV_CACHE_DIR=.uv-cache just fmt`、`just fmt-check`、`git diff --check` 通过；依 ExecPlan 未在 fix/fmt 后重复测试。
- target-free：多轮 `git diff --check`、无 `*.snap.new`/`*.rej`；最新 review fixes 后在 `multidev/` 运行
  `UV_CACHE_DIR=.uv-cache just fmt` 与 `just fmt-check` 均通过；全部 app-server JSON/config schema 及两个 zstd export 解压内容只读 parse
  通过。worktree 根一次 `just fmt` 因该 Justfile 无 recipe 立即退出，未触碰 target。
- 最新 review-fix 正式轮（默认 features、dev/local profile、共享 069 target、`CARGO_BUILD_JOBS=2`、临时项目 270/285/290GB 门限）：
  - `codex-state` / `codex-thread-store` 精确 locator/meta filter：18/18 passed，0 failure/error；JUnit SHA-256
    `d49a11e077fb66a88de0dfe1c0fce0be4fc7a49b7cd86e19b615fc4f2a9fe2e0`。
  - `codex-app-server` / `codex-app-server-client` / `codex-tui` 精确 Durable Session Query 与 `/sessions` gate filter：46/46 passed，
    0 failure/error；JUnit SHA-256 `c748719d7158245cbc7d88c59b4c224c3a345347644ef7f987f74d76b8b98a49`。其中 public fresh-state
    chain 覆盖 default-off、stable API、source unsupported、immediately-dropped owner cold read、cold committed read 无 activation/write。
- 下列较早重型证据形成于最终独立终审修复之前，保留为较宽基线证据：
- lower/protocol 聚焦：42/42 passed，4266 skipped。
- app-server 聚焦：11/11 passed，1132 skipped；覆盖 default-off、stable RPC 不依赖 experimental API、public source failure、
  graceful/abnormal restart cold read、分页、归档、identity/corruption 与 query-only side-effect 边界。
- client/TUI 聚焦正式轮：23/23 passed，0 flaky、0 retry、3462 skipped；JUnit SHA-256
  `b5882be46a2f93aa23e63cc23ed68381b03e646b7824b1c4b831984a8a2d144f`。
- stable/experimental app-server schema generator 各 1/1 passed；配置 schema generator passed。生成物只新增/更新 Session Query
  request、DTO、bundle、precomputed exports 与默认关闭 feature 的配置项。
- `codex-state`、`codex-features`、`codex-team-state`、`codex-thread-store` 全量：567/567 passed，1 skipped；JUnit SHA-256
  `dbd5cd76ab3541ccd7f5a25b8fcb6a19865491ff914c19bbc66b2e7b86105ea1`。
- 九个直接修改 crate 的单 crate scoped `just fix -p <crate>` 全部通过：state、features、team-state、thread-store、core、
  app-server-protocol、app-server、app-server-client、tui；各轮 `stop=none / cleanup=none`。

## 重型证据后的终审整改

- state locator 拒绝 legacy-second 时间值，避免 cursor 按毫秒回写后不推进；BLOB rollout path row typed 为 corrupt。
- thread-store 使用 fallible exact candidate seam 和 plain-first/`.zst` resolver；missing/non-file typed corrupt，PermissionDenied/timeout 等 OS I/O
  typed unavailable，不再由 Option-only helper吞掉。回归覆盖 compressed-only、双文件 plain 优先及错误分类。
- app-server 对无法证明的 source continuity 保守 incomplete；public fresh-state 场景在第一页后移动一个未返回 Root，验证 active continuation
  与 archived source 分离、无重复、cursor 耗尽及 `SourceChanged`。
- client list/read 共享 committed high-water，整页 staged 校验后才一次提交；typed 拒绝 duplicate Session、同页/跨请求 Root 冲突、request/response
  Session/Root mismatch 与 `Available + team=None`。Team unavailable 但 canonical Root 已认证时只绑定 Root、不推进 committed；已知 Root 后错误
  Root attachment 即使收到无 Root/Team 的 typed unavailable 也会拒绝。回归覆盖 list↔read 两方向 generation rollback/同代异 fingerprint、无部分提交、三种
  root-boundary 组合和 typed unavailable；TUI 只走 formal protocol wrappers，并保留 rejected projection 为 non-fresh。
- lower/app-server/client-TUI 与最终合同专项审查者已对上述最新 live diff 复审，无剩余高/中等级 finding；随后 64 项聚焦回归全部通过。

## 独立验收整改

- `InMemoryThreadStore` 不再把易失 history 冒充 canonical persisted `SessionMeta`，恢复 trait 默认 `Unsupported`；公共 app-server
  回归同时验证 list locator 和 direct read 都映射为 typed `SourceUnsupported`，不能与磁盘 snapshot 拼成 `Available`。
- formal client 在任何 high-water、canonical Root map 或 view 提交前校验 `Available <=> Team`，并要求 Team viewer 等于外层 canonical
  Root 且 role 为 Root；非法第二行不会部分提交同页第一行的新 Session，旧 projection 保留但降为 stale。
- 双 gate 不再由 `/sessions` 全局遮蔽 C0：`/sessions` 固定正式 query，`/session-control` 固定 C0；仅启用 C0 时保留旧 alias。
  popup、无参/带参 dispatch、usage、refresh 与错误提示均使用同一无歧义边界。
- Team 的 participant label、version author label 与 summary 仅在正式 renderer 边界把连续 whitespace/control 折叠为单个空格并 trim；
  canonical snapshot、fingerprint 和存储值不变。恶意 LF/CR/ESC/BEL/Unicode separator snapshot 不能伪造结构化状态行。
- 三路只读交叉审查分别覆盖 lower/client、TUI routing/renderer 和完整合同，均未发现剩余高/中等级 finding；审查报告
  `agent_log/2026-08-25-103752-plan-077-independent-review.md` 保持历史原文未修改。

调试期另有两次 watchdog 主动停止：一次 sustained memory PSI、一次运行中出现无法归属的 scope 外 Cargo PID；均未冒充测试通过，
且停止后释放重型资源。client/TUI 的前一调试轮虽最终 23/23，但含一次临时 SQLite pool timeout 自动重试；正式证据采用后续稳定轮。

workspace `just test` 只运行一次，测试前即被 `v8 = 150.4.0` 请求不存在的官方
`librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz` 资产 HTTP 404 阻断。只读核对 build script 与官方 release 资产后确认
该 ABI 变体未发布；没有用普通/ptrcomp 资产替代，没有关闭 sandbox、启用 `V8_FROM_SOURCE` 或升级依赖。

随后收窄的 core/protocol 全量轮中，protocol 与 077 相关测试先通过；core 大量互不相关测试共同表现为本地 wiremock 收不到请求、
`127.0.0.1` 请求被 502 代理链截获或超时。为避免余下测试继续 35–60 秒重试，按已声明的外部阻断终止条件向前台命令发送正常
`Ctrl-C`，由 canonical wrapper 回收 scope；记录为 2538 passed、44 failed、4 timed out、1145 not run，不能作为通过证据，也没有修改
这些 scope 外测试。

## 资源证据

- 首个重型轮前：RONDO `180,705,333,248 B`，069 target `93,634,899,968 B`，Windows C: 可用 `101,905,600,512 B`。
- client/TUI 稳定轮：RONDO `221,983,887,360 → 222,559,850,496 B`；target 结束 `128,941,871,104 B`；Windows C: 可用
  `95,886,262,272 → 95,650,783,232 B`；memory/nonreclaimable peak `4,657,291,264 / 2,330,566,656 B`；swap peak `0`。
- lower 四 crate 全量：RONDO `236,008,521,728 → 239,716,175,872 B`；target `146,097,659,904 B`；Windows C: 可用
  `101,876,326,400 → 101,874,630,656 B`；memory/nonreclaimable peak `5,214,175,232 / 2,279,141,376 B`；swap peak `0`。
- scoped fix 完成后：RONDO `254,989,651,968 B`，target `161,370,775,552 B`，Windows C: 可用 `101,874,155,520 B`，
  MemAvailable `20,424,804 kB`，SwapFree `8,169,992 kB`，PSI full avg10 `0`；无 cargo/rustc/nextest，重型资源已释放。
- 最新 target-free 整改期样本（078 已接管重型时段）：RONDO block `254,927,990,784 B`、069 target `161,120,481,280 B`、Windows C:
  可用 `101,868,146,688 B`、MemAvailable `20,987,100 kB`、SwapFree `7,858,004 kB`。项目距 255GB 主动停止线约 72MB；077 不启动
  target 写入、不排队/轮询锁，也不清理共享 069 target。
- 最终 review-fix lower 轮：项目 `272,824,258,560 → 273,183,907,840 B`，target 结束 `179,373,494,272 B`，Windows C: 可用
  `91,308,408,832 → 90,938,437,632 B`；memory/nonreclaimable peak `3,249,111,040 / 1,473,445,888 B`，swap `0`，`stop=none`。
- 纵向轮首跑在测试前以 `project_reached_proactive_stop` 停于项目 `285,255,151,616 B`；scope 已完整回收且无 JUnit。只删除 13 个本轮开始前
  已陈旧的 core/app-server-protocol incremental hash 目录，共 `13,537,357,824 B`；未删 `deps`、源码、fixture、测试证据或其他数据。
  清理后项目/target 为 `272,152,420,352 / 178,110,390,272 B`。
- 最终纵向重跑：项目 `272,152,424,448 → 277,175,566,336 B`，target 结束 `183,133,495,296 B`，Windows C: 可用
  `79,156,613,120 → 79,156,465,664 B`；memory/nonreclaimable peak `7,392,350,208 / 3,092,865,024 B`，swap `0`，`stop=none`。
  批次完成后无 cargo/rustc/nextest，重型资源已释放。临时门限仅通过本轮环境变量生效，未写入仓库。
- 独立验收整改正式轮：项目 `281,259,171,840 → 281,416,093,696 B`，target `187,368,755,200 B`，Windows C: 可用
  `78,852,145,152 → 78,849,191,936 B`；memory/nonreclaimable peak `8,606,568,448 / 3,648,495,616 B`，swap `0`，
  `stop=none / cleanup=none`。
- 整改 scoped fix 首轮因 `project_reached_proactive_stop` 于项目 `285,005,111,296 B` 停止，第二轮因瞬时 scope 外 Cargo PID
  `310544` fail-closed 停止；均未冒充通过且 wrapper 完整回收。只删除 18 个在整改批次前形成、后续测试/clippy 未触碰的可重建
  incremental hash 目录，删除前测得合计 `6,477,017,088 B`；未删除 `deps`、本轮进度、源码、fixture、snapshot 或 JUnit。
  第三轮 scoped fix 通过：项目 `282,011,971,584 → 283,521,429,504 B`，target `189,474,492,416 B`，Windows C: 可用
  `78,276,218,880 → 78,274,510,848 B`，`stop=none / cleanup=none`。随后无 Cargo/rustc/nextest，重型资源已释放。

## 未运行或未通过

- workspace-wide `just test` 未通过：上述 V8 官方资产 404；不重跑、不规避。
- core/protocol 全量未通过：上述 scope 外 mock/代理环境阻断后正常中断；077 聚焦与 lower 全量证据独立有效。
- app-server、app-server-client、TUI 未再运行 crate 全量；Plan 要求的聚焦/fresh-state/snapshot 与 scoped fix 已通过，且 270GB 后不再启动
  新宽门禁。

未运行 Docker、真实 API/模型、训练、测评、CI、PR、push、merge、rebase、cherry-pick、发布或远端修改。

## 任务收口

- 109 路径已只提交到 `worktree-077-m4-c1-durable-session-query`，提交后 worktree clean。本任务范围内无剩余实施步骤；未
  merge/rebase/cherry-pick/push/关闭 worktree 或重命名分支，交回用户独立验收。
