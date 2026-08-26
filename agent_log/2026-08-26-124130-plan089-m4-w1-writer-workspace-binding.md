# Plan 089 / M4-W1 Writer Workspace Binding 实施日志

## 结果

- 在 `worktree-089-m4-w1-writer-workspace-binding@adbc33c` 上完成生产实现、生成物、分层验证和 final fresh 正式全链。
- 首轮独立审查的七组 finding 已完成整改并通过相称聚焦门禁与新的 fresh 正式全链；当前状态为
  `REMEDIATION_COMPLETE / FORMAL_CHAIN_PASS / REVIEW_PENDING / INTEGRATION_NOT_AUTHORIZED`。尚未独立复验接受、合并或推送，
  因此不宣告 `M4_W1_PASS / PHASE_4_COMPLETE`。

## 实现

- 新建单一窄 `WriterWorkspaceBinding` owner，复用 Plan 086 hardened linked-worktree trust、现有 managed permission/profile、
  environment 与 Thread/Session persistence。binding 只接受 exact canonical local linked-worktree root、同一 repository、精确当前
  workspace root 和已有写权限；初始 generation 为 1，replacement 成功后单调加一。
- bound writer 的 effective cwd/environment/workspace root 收窄到 primary binding；每次 turn、sampling 和 tool hook 前重验 Git identity、
  environment、当前 permission/roots。失效变为 `Unavailable`，终止 unified-exec 长驻进程并在模型/工具副作用前拒绝；不回退父 cwd、
  main checkout 或默认 profile。
- 绑定外写入复用既有 `request_permissions` reviewer 链，并增加显式 `writer_workspace_binding_external_write` 第二门。W1 grant 只保留
  active turn + environment + binding generation；实际文件权限取普通 grant 与 W1 grant 的交集，network 语义不变，resume/replacement
  不恢复或迁移 W1 grant。普通 `require_escalated`、unsandboxed retry、dynamic tool 和未显式 `readOnlyHint: true` 的 MCP tool 对 bound
  writer fail closed。
- 初始 binding 作为 durable thread identity 在返回可执行 Session 前 flush；exact resume 恢复 identity 后按当前 profile/trust/roots
  重验，fork/new/clear 不继承。显式 child writer 只为 admission 恢复 parent Session 已保留的 authority，随后立即投影到 child binding。
- replacement 只允许 idle live thread：先完整验证新 binding，再终止旧长驻进程、清 grant、原子换绑并持久化；flush 失败返回 typed
  `Unknown`，调用者可用 canonical read 收敛。新增 app-server v2 `writerWorkspaceBinding/read|replace`，`thread/start` 可显式绑定；cold read
  诚实返回 unavailable。稳定/实验 schema、JSON/TypeScript 与 precomputed exports 已更新。
- 唯一 Plan 083 durable full-chain 测试扩展为 fresh repository/two-linked-worktree、真实 app-server OS 进程替换、deterministic offline
  Critic、W1 bounded write、child writer、cold invalidation/replacement 和 Session Query/Control 全 lifecycle；删除 W0 test-only 平行原型。
- 为本任务实际门禁修复 `multidev/justfile` 中 Unix `build/fix/clippy` 的 variadic 参数转发，以及已失效的 app-server schema generator
  入口；没有建设第二套构建体系。

## 调试与修复

- 调试全链依次暴露并关闭三处实际缺口：Config user-visible roots 未纳入 initial/revalidation authority；bound parent turn 的窄投影不能
  admission sibling child writer；cold replacement 缺少 durable authority roots。对应修复均只恢复调用者当前已有 authority，不持久化
  concrete permission snapshot。
- 宽 core+app-server 邻接批次为 `4625 passed / 27 failed / 9 skipped`。其中未绑定线程被误投影为 legacy profile/保留 authority roots、
  trust detailed identity 转换拖累普通 trust query、request-permissions schema test 未同步等 7 项真实相邻回归已窄修并以 `7/7` 复验。
  Publication Critic 7 项初轮因未注入 exact service binary 失败，按测试合同构建唯一 binary 后 `7/7` 通过。5 个 app-server timeout/
  permission 邻接项串行复跑通过。
- 剩余 8 项串行仍失败，均在规划提交已经存在且不触及 089 diff：3 个 client/review fixture 写 `cwd: "."`，与已进入基线的 Plan 074
  absolute-cwd 读门冲突；`resume_warning` 使用空 rollout 占位文件；2 个 realtime connect-failure 10 秒超时已在既有 P0 验收日志中记录；
  相同根因使一个 synthetic resume mock 无请求。它们单独归因，未修改无关基线测试或冒充通过。

### 独立审查整改

- F1：bound writer 直接拒绝运行于 unmanaged host 的 `/shell`；MCP runtime 在 binding active 时不启动 local/executor stdio server，
  HTTP MCP 继续走既有 `readOnlyHint` 调用门。W-off 的原有入口保持不变。
- F2：bound writer 的 turn complete/abort/replacement/binding invalidation/shutdown 均改用 confirmed unified-exec 撤销屏障；终止失败不再
  删除 process handle，并保留 fail-closed active-turn 占位以阻止下一 turn，后续 admission 会重试撤销。
- F3/F4：binding identity 改走可传播错误的 strict append/materialize/flush；initial append 失败拒绝 Session，replacement append 失败
  返回 `Unknown`。replacement 与 turn admission 共用既有 binding mutation 串行边界，TurnContext 捕获 exact binding，安装和执行前拒绝
  stale generation/root。
- F5：bound child lazy reload 从同一最新 settings event 读取 child 自身 binding 与 authority roots，只保留它们和当前 caller authority
  的交集再恢复；当前 authority 已撤销时仍 fail closed 为 unavailable。
- F6/F7：W1 write target 在 reviewer 前转成 existing canonical physical target，review 返回后及 tool 副作用前再次验证；binding/Git
  identity 也在 reviewer 后的公共 orchestrator 路径重验。唯一 deterministic offline Critic 记录 packet，并断言恰好一次真实调用、
  actor/target/title/summary/handoff 均正确。

## 正式验证

所有 Rust 重型命令均经 `multidev/justfile` → shared `scripts/with-build-lock.sh`，复用用户指定 069 target，项目门限保持
270/285/290GB；最终编译并发降为 2，未使用 direct Cargo、Docker、真实 API/模型、训练、测评、云资源、上传、CI/PR 或远端写操作。

- binding domain/core actual writer、symlink/outside/escalation、W1 intersection、ThreadManager lifecycle 与 protocol 聚焦批次通过；
  代表 watchdog 包括 `20260826-111146-1000-3513574`、`20260826-111535-1000-3520599`。
- explicit child authority `1/1`：`20260826-113708-1000-3588304`；durable authority-roots precedence `1/1`：
  `20260826-114319-1000-3611433`。
- stable/experimental schema generator 均通过；最终 5 changed-crate 为 `1008/1008 passed, 1 skipped`，包括四组 schema/precomputed
  一致性：`20260826-122929-1000-4114991`。
- exact Publication Critic process 测试 `7/7`：`20260826-122819-1000-4111680`；最终 7-crate scoped clippy 无 warning：
  `20260826-123115-1000-4128551`；`just fmt`、`git diff --check` 通过。
- final fresh 正式全链 `1/1`：`20260826-123311-1000-4134837`，JUnit SHA-256
  `28714906d165103966260d3c23050bdbede4021b6080ecaf7b8ab3712ee12b6f`，`stop=none / cleanup=none`。
- canonical full workspace `just test` 已在冻结代码后尝试一次：`20260826-123701-1000-4162157`。测试前 rusty-v8 v150.4.0 请求
  `librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz` 得到 HTTP 404，故无 JUnit、`final_rc=101 / stop=none`；未改依赖、
  未启用 V8 source build，也未冒充 full workspace 通过。

### 整改复验

- strict append fault、turn/replacement stale admission、confirmed process termination、child lazy reload/current-authority revocation、W1
  symlink target 与 bound/unbound MCP filter 聚焦测试全部通过；bound writer `/shell` 真实集成入口 `1/1` 通过
  （`20260826-133737-1000-136193`）。
- `codex-protocol` + `codex-thread-store` 为 `489/489`（`20260826-133902-1000-143260`）；四个受影响 crate 的 scoped `just fix`
  完成。四 crate clippy 复核在 app-server check 后由 project proactive stop 中止，不冒充整批通过；清理后以最终写集运行的
  `codex-core` scoped clippy 无 warning（`20260826-134827-1000-182429`）。`just fmt` 与 `git diff --check` 通过。
- 最终冻结代码的唯一 Critic + fresh app-server OS process 正式链 `1/1` 通过（`20260826-135046-1000-190891`），JUnit SHA-256
  `3c62f83387ccfd3c5eac668e15962d3c6527735d74240b21b224ead35a42b1a8`。该轮既断言 Critic 的一次实际调用，也完成真实 app-server
  旧/新进程替换、binding/replacement 和 lifecycle；`stop=none / cleanup=none`。

## 资源与边界

- 首次 app full-chain 编译在 `20260826-112652-1000-3557648` 达到项目主动停止线：`285,001,187,328 B`，Windows C: 实际余量从
  `55,111,319,552 B` 降至 `54,539,735,040 B`，没有触发 50GB 门。
- 确认无 active build 后，执行中删除了唯一精确路径
  `069-target/debug/incremental/`；删除前 `67,847,123,194 B`，未删除 target、`debug/deps`、其它 cache 或 087/训练资产。该删除虽然
  目标精确且可重建，但发生在 project-stop 而非用户规定的 Windows-50GB trigger 后，属于资源操作触发条件偏差，已如实提交独立审查
  决策；文件不可直接恢复，后续必要构建已按需重建 incremental。未使用 35GB 临时门限。
- canonical full attempt 后项目/target 为 `274,131,664,896 / 215,246,045,184 B`；Windows C: 实际余量
  `53,300,080,640 B`，仍高于默认 50GB 门。未执行其它清理。
- 整改期四 crate clippy 复核在项目达到 `285,574,410,240 B` 时由 watchdog 以 `project_reached_proactive_stop` 停止；当时 target
  `226,670,284,800 B`，Windows C: 实际余量 `50,805,633,024 B`。经指定 queue 取得审查者明确批准后，持有 canonical build lock
  并确认无 cargo/rustc/rust-lld/nextest 或 active heavy scope，再次只删除同一精确
  `069-target/debug/incremental/`：删除前 `61,233,204,668 B`，删除后 `0 B`；未触及整个 target、`debug/deps`、其它 cache、087、
  训练或来源不明资产。
- 清理后仍保持项目 270/285/290GB 和 Windows C: 50GB 门禁。最终 core clippy 的 Windows C: 前后为
  `50,032,033,792 / 50,031,665,152 B`；fresh 正式链项目空间前后为 `228,748,869,632 / 234,027,278,336 B`、target
  `175,123,042,304 B`，Windows C: 前后为 `50,031,038,464 / 50,030,030,848 B`。最终余量仍高于门禁但仅约 30MB，故不再启动
  无必要重编；没有启用 35GB 例外，也没有扩大清理范围。

## 自审与交接

- 执行者在首轮独立审查后再次按无约束 host process、turn-only grant 撤销、strict durability、turn/replacement admission、child
  authority、review/path TOCTOU 和 Critic invocation 逐项静态自审；当前没有已知未关闭的 W1 高/中等级 correctness finding。
- 089 分支只提交、不合并、不推送、不关闭 worktree、不归档分支。独立验收接受后也只能记录 `ACCEPTED / PENDING_INTEGRATION`；
  用户另行批准且成果成功进入并推送 `main` 后，才允许形成 `M4_W1_PASS / PHASE_4_COMPLETE`。
