# Plan 086 / #39616 Linked-Worktree Trust 窄适配实施日志

## 结论

执行者已完成 `#39616@bc3545b805de6e91a11b88114fe1673b678633ca` 的 RONDO Multi 窄适配和自审，当前状态为
`REMEDIATED / AWAITING_INDEPENDENT_REREVIEW`。独立审查提出的 nested cwd active-project P2 已完成窄修与复验；
`M4_W_39616_ADAPTATION_PASS` 尚未由独立审查者接受，未修改 WBS 当前指针，未启动
`#39153` 或 M4-W1。

## 实现

- 将 project trust resolver 从普通 Git info 收口到 `codex-git-utils` 的专用 trust 模块；普通 repository 行为不变，linked worktree
  只有在 `.git` pointer、admin directory、`gitdir` backlink、`commondir`、registered checkout、common directory 与 main checkout
  ownership 全部一致时才返回主仓 trust key。
- Git metadata 使用 64KiB 有界二进制读取，拒绝 symlink、异常类型、超限和读取后仍超限内容；`PathUri::join_native_bytes` 保留 remote
  executor 上的 POSIX 非 UTF-8 路径并拒绝无效 Windows/opaque/null-byte 输入。
- 既有 config loader、active project、app-server/TUI trust target 与 realtime grouping 继续消费同一 resolver；没有新增 workspace registry、
  permission/trust 体系或下游能力。
- 新增 task-owned `TempDir`/本机 Git fixture 覆盖普通/真实 worktree、missing/forged/mismatch/symlink/oversize/stat-read swap、alias、
  separate Git directory、Linux 非 UTF-8、move/repair，以及 config/hooks/MCP 行为。非法 checkout 的 project config、permission 与 host MCP
  不生效，合法 registered worktree 不退化，当前 checkout 的独立显式 trust 仍生效。
- 审查 finding 确认存在：nested linked-worktree cwd 的 `active_project` 仅查 exact cwd 和继承 root，会跳过 checkout root 的显式决定。
  窄修复用 config loader 的既有 checkout-root helper，统一查询优先级为 exact cwd、checkout root、hardened resolver 验证的继承 root；
  未引入目录 registry、宽松 fallback 或任意外置 Git directory 支持。

## 验证

- `UV_CACHE_DIR=/tmp/plan086-uv-cache just fmt`：通过。首次默认 `uv` cache 因 sandbox 只读失败，改用 task-owned 临时 cache 后正常完成。
- resolver/path/config 聚焦簇：21/21 通过，nextest run `52db5063-2bb8-4ba8-a41a-0f2f4fcfae92`。
- 合法 linked-worktree config/hooks：2/2 通过；同批初版 MCP 测试的无关模型请求断言失败，删除该非目标断言后重跑。
- host MCP/config/permission 行为：1/1 通过，nextest run `6f97fe8b-88d3-4bf1-a4de-b164eaf78593`。
- app-server linked-worktree hooks：1/1 通过，nextest run `8a580372-0674-4a52-ba0f-126dc1509aa8`。
- scoped `just fix -p codex-utils-path-uri -p codex-git-utils -p codex-core -p codex-app-server`：通过；最终 `git diff --check` 通过。
- 审查整改聚焦轮：nested active-project trusted/untrusted 优先级单测与 nested host MCP/config/permission 正反行为 2/2 通过，nextest run
  `cf9287bf-ed1d-4a47-aaaf-d4b874877c29`；随后 scoped `just fix -p codex-config -p codex-core` 通过。

所有重型命令均经共享 lock/watchdog，显式复用 069 target 与 270/285/290GB 临时项目门限。一次合并 core/app-server 行为批次在测试开始前
被 watchdog 因持续 memory full PSI 主动停止（exit 125），随后保留进度、拆窄通过；未清理 target。观测到的项目结束占用约
269.67GB、069 target 约 211.10GB、Windows `C:` 实际余量约 74.58GB，未触及 285GB 主动停止线。

## 未运行与边界

- 未运行 workspace 全量、`--all-features`、benchmark、S/C 全链、Docker、真实 API/模型、训练、CI/PR；整改仅调整 active-project
  与 config loader 的既有接缝并补 nested cwd 回归，聚焦单元/行为门已覆盖直接风险，因此没有扩大到这些无关门禁。
- 未修改 WBS/COMPLETED、main、其他 worktree、Plan 082 资产或远端；等待指定独立审查者验收。
