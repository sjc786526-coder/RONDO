# L2a Guardian 独立 provider：阶段 A 实现待验收

对应计划：`plan/016-l2a-guardian-provider-override-execplan.md`。本批只执行 canary 安全阶段 A；没有运行
格式化、schema 生成、Rust 构建/测试、mock server、Docker、本地模型或真实 provider 请求。

## 实质改动

- `[auto_review].model_provider` 引用合并后的 `model_providers` registry；未知或空白 ID 在 config load
  时 fail-closed。项目局部 `.codex/config.toml` 不能设置该目的地，但同表既有字段继续保留。
- Guardian 克隆配置后同时替换 `model_provider_id` 和完整 `ModelProviderInfo`，再把 request/stream retry
  收缩回既有 `1/1`；未配置时继续继承主 provider，主 `Config` 不变。
- session spawn 分离 session auth 与 model-provider auth。显式独立 provider 的 env key、静态 bearer、
  command auth 由 provider 自己处理；无鉴权本地 provider 不继承父凭据；`requires_openai_auth`、Bedrock
  和未配置 Guardian 保持原路径。
- provider auth 继承策略进入 Guardian session 复用键；显式覆盖与继承即使使用相同 provider ID/info，
  也不会跨鉴权策略复用旧 session。
- 三层测试代码覆盖有效/无效配置、项目层过滤、完整 provider/retry/父配置不变、无鉴权隔离、Bedrock
  兼容、安全收缩，以及主/Guardian 两个 WireMock endpoint 的 `2/1` 请求分流。

## 静态审查

- 两个独立只读审查分别检查实现链和测试/计划。首轮发现无鉴权 provider 会继承父 AuthManager 的凭据
  泄漏风险；已补 auth 隔离并把双端点用例改成能直接捕获该问题。末轮发现鉴权策略未进入 Guardian
  session 复用键；已补行为键和同 provider ID/info 下的失效回归。复审未留下已知阻断。
- 另一项审查指出 loopback 测试在 Codex sandbox 中会 early-return false-green、空 ID 可能命中人为构造
  的空 registry key、以及阶段 B 命令顺序问题；空 ID 已显式拒绝，non-sandbox/no-skip 证据和
  fix→fmt→schema→最终测试顺序已冻结在 ExecPlan。
- `git diff --check` 通过；`Config`/`SessionSpawnArgs`/delegate 的显式构造与调用点已用 `rg` 静态枚举。
  `core/config.schema.json`、Cargo/Bazel manifest/lock 均未修改。

## 并行状态与交接

- worktree：`.claude/worktrees/0812-l2a-provider`，分支 `0812-l2a-provider`，实现基线
  `98717160d7503fa29fe0299e2df715eccf29b589`。用户在阶段 A 收口后单独授权把实现提交到该本地分支，
  并把最新本地 `main` 合入；没有授权合并回 main、推送或启动阶段 B。
- 阶段 A 期间 `main` 由另一任务前进到 `21bcf18`，只新增/修改本地模型冻结文档，并新建
  `0812-local-model-engineering` worktree；未触碰。并行任务占用了 `plan/015-*`，本计划因此改为
  `plan/016-*`。
- 提交交接前复核时 `main@fea01f8` 与 `origin/main` 对齐且干净；`0811-plan014-post-audit` 有并行未提交修改，其他
  非本任务 worktree 干净，均未触碰。
- 当前状态是“实现待验收”。阶段 B 只有在用户明确授权并完成 canary/Docker/build-lock/cgroup/Windows
  C 盘/target/worktree 门禁后，才按 ExecPlan 运行生成、定向测试和双 loopback endpoint 验收。
