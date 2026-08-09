# V8 sandbox 本地资产接线与 Plan 004 门禁补验执行计划

> 本计划是任务的稳定约束文档。除“当前状态”和“关键决策记录”外，执行期间默认不修改其他部分；
> 若必须改变目标、范围、硬约束或完成标准，应暂停并向用户说明。
>
> 状态：执行完成；轻量资产接线、sandbox canary与真实host smoke通过，workspace已真实执行但存在
> 31项失败、1项超时和23项显式ignored，Plan 004仍按部分通过披露
>
> 工作树：`.claude/worktrees/0809-v8-sandbox-local-gate`
>
> 分支：`0809-v8-sandbox-local-gate`
>
> 起点：`main@dd0ea98db6264c5a3991858692bfc7bb2c93f91f`

## 1. 目标

### 最终目标

用一个轻量、本地、显式的测试入口，把仓库已有的 OpenAI `rusty_v8` sandbox 预编译资产下载与双 SHA-256
校验逻辑接到现有 build lock/watchdog 上；随后补跑 Plan 004 尚未进入测试体的 `sandbox=true` canary、一个真实
Code Mode host smoke，以及被同一资产问题阻断的唯一一次完整 workspace 门禁。

本任务只补齐既有能力之间的连接，不新建 V8 构建体系，不修改产品的 V8 feature 选择，不从源码编译 V8。

### 完成/验收标准

- 本地入口从当前 `rustc -vV` 读取精确 host target，从 `codex-rs/Cargo.lock` 读取唯一 `v8` crate 版本，调用
  `scripts/codex_package/v8.py` 既有下载、缓存和两文件 SHA-256 校验逻辑。
- 正式子进程只使用校验通过的同版本 OpenAI archive/binding 对，并同时设置
  `RUSTY_V8_ARCHIVE`、`RUSTY_V8_SRC_BINDING_PATH`；不把环境修改写回用户 shell 或宿主配置。
- 入口拒绝 `V8_FROM_SOURCE`，不允许正式门禁静默退回源码构建；缺资产、目标不支持、manifest格式错误、任一
  SHA不匹配或环境准备失败都必须非零退出，不能启动 Cargo。
- 新入口复用 `just test` 的 `RUST_MIN_STACK`、`NEXTEST_PROFILE=local`、Nextest参数和
  `scripts/with-build-lock.sh`，不复制或绕过锁、cgroup、资源看门狗、JUnit留存逻辑。
- `sandbox=true` canary 实际执行目标测试，`linked_v8_has_sandbox()` 为true，JUnit为0 failure/error/skip；
  已在 Plan 004 通过的 `default=false` canary不重复运行。
- 真实 Code Mode host smoke 必须启动实际 `codex-code-mode-host` 子进程并执行JavaScript/会话协议，不接受只编译、
  只调用runtime单元函数或假host替代；JUnit为0 failure/error/skip。
- 完整workspace只补跑一次，命令固定带 `--retries 0 --flaky-result fail`。最终必须解析JUnit，要求所有实际
  testcase为0 failure/error；任何skip逐名审查，Plan 004目标项和Code Mode/V8门禁不得skip，不能只看进程退出码。
- 新入口的最小脚本回归、格式检查与diff检查通过；没有新增依赖、Cargo feature、CI、PR、常驻服务或发布流程。
- `agent_log/` 完整记录实现边界、资产版本/target/archive与binding SHA、正式命令、watchdog run/summary、JUnit
  路径与SHA、testcase/failure/error/skip、失败诊断与重跑原因。Plan 004、WBS和完成历史只同步最终事实。

## 2. 范围

### 允许修改

- `mydev/justfile`：增加一个显式、窄用途的 OpenAI V8 sandbox 资产测试入口。
- `mydev/scripts/`：增加薄包装脚本及其轻量单元测试；直接复用
  `mydev/scripts/codex_package/v8.py`，只有发现无法复用的真实小缺口时才允许对该模块做窄扩展。
- 若 `sandbox=true` canary或真实host smoke暴露V8/Code Mode测试自身的确定缺陷，可最小修改
  `mydev/codex-rs/v8-poc/`、`code-mode-runtime/` 或 `code-mode-host/` 的直接相关代码/测试。
- 本ExecPlan、Plan 004的“当前状态/关键决策”、`doc/WBS.md`、`doc/WBS-COMPLETED.md` 和本任务
  `agent_log/`。

### 不允许修改

- 不修改 `v8` 版本、Cargo feature拓扑、产品默认开关、V8 sandbox实现、安全策略或上游源码基线。
- 不运行或接入 `V8_FROM_SOURCE=1`，不新增Bazel/V8源码构建、资产发布、镜像、CI、PR或通用下载框架。
- 不复制 `.github/actions/setup-rusty-v8/action.yml` 的下载实现形成第二套校验器；本地入口以既有
  `codex_package.v8` 为唯一下载/校验实现。
- 不修改 `.github/workflows/`、GitHub release、远端资源、宿主配置、全局工具链、Clash/TUN、代理、Docker或真实API。
- 不借workspace门禁修复与V8/Code Mode无关的新失败；若出现，保留证据并另列，不扩大本小任务。
- 不重复Plan 004已通过的A-F/H-K定向/压力门禁，也不重复default=false canary。

### 不允许读取/查看

- 项目外个人文件、凭据、真实会话和无关仓库。只允许访问公开的 `openai/codex` 对应release资产及其checksum
  manifest；不读取或打印代理凭据等环境值。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. 全部代码和文档变更只在本独立worktree进行；未知修改保留，不触碰其他worktree。
2. 新入口必须是薄适配层：host识别、调用既有fetch/verify、打印非敏感证据、给子进程注入两个路径并执行命令；
   不把下载、checksum解析或cache原理重新实现一遍。
3. 正式门禁所用OpenAI资产必须与当前lock中的唯一V8版本和当前rustc host target一致。archive与binding必须来自
   同一份恰含两行的官方checksum manifest，且两项均复核通过；禁止混版、单变量覆盖和部分成功。
4. 入口应以本次已验证的OpenAI资产覆盖调用进程中可能存在的ambient `RUSTY_V8_*`，并在日志中打印最终使用的
   公开路径与SHA；不得继承来源不明的半套或自定义资产冒充正式证据。
5. 发现任何有效 `V8_FROM_SOURCE` 请求时fail-closed，不删除该变量后偷偷继续，也不把源码构建当作fallback。
6. Cargo测试只经新`just`入口进入 `with-build-lock.sh`；一次只运行一组并等待全局锁。不得直接运行Cargo，
   不得提高现有build jobs/test threads或绕过资源阈值；`CARGO_TARGET_DIR`保持在RONDO项目根内。
7. 三段正式门禁严格串行：sandbox canary通过后才跑host smoke；两者通过后才启动一次workspace。失败后只允许在
   发生直接相关修改时原样重跑受影响门禁，必须保留首次失败证据和原因。
8. 正式Nextest命令统一带 `--retries 0 --flaky-result fail`。`junit_status=retained`只代表工件留存，必须独立解析
   XML；0匹配、skip、测试体提前返回、构建前退出均不算通过。
9. 下载是公开只读网络访问；不上传、不发布、不创建release。缓存沿用既有helper默认，损坏项只有在既有
   `ensure_valid_artifact` 校验失败路径中才删除并重下，不做递归清理。
10. 若workspace暴露与V8/Code Mode无关的失败，本任务只诊断、记录和判断Plan 004状态，不进行跨模块修复。
11. 执行结束运行仓库规定的格式工具和 `git diff --check`；不因格式化夹带无关改动。
12. 工作树内完成审查和提交；本任务不自动合并或推送，除非用户另行明确要求。

## 4. 软性建议

- 新入口建议命名为 `just test-with-codex-v8 ...`，参数语义与现有 `just test ...` 一致，只增加资产准备层。
- 薄包装脚本建议使用 `rustc -vV` 的唯一 `host:` 行选择 `TARGET_SPECS`，调用
  `fetch_codex_v8_artifacts()`，随后以 `os.execvpe` 替换为原命令，保持信号和退出码语义。
- 资产证据建议打印crate version、target、archive/binding绝对路径与实际SHA-256；不输出完整环境。
- 包装脚本的单元测试只覆盖host解析、无命令、source-build拒绝和环境覆盖等纯逻辑；真实下载和双文件校验由
  sandbox canary的实际入口贯穿验证，避免另造网络测试。
- 真实host smoke优先复用
  `remote_session_persists_values_forwards_delegates_and_controls_cells`：它会启动真实host，执行JS，验证跨cell
  store/load、nested tool回调和session关闭，比新增一条重复smoke更轻。
- 现有 `/tmp/codex-package` cache能在SHA一致时复用；不要为了“更正式”再建项目内资产仓库或长期缓存管理器。

## 5. 实施接口与步骤

### 5.1 轻量资产适配层

预期接口：

```text
python3 ../scripts/with_codex_v8_artifacts.py -- <command> [args...]
```

行为顺序：

1. 拒绝空命令和有效的 `V8_FROM_SOURCE`。
2. 运行 `rustc -vV`，解析唯一host triple并映射到既有 `TARGET_SPECS`；不使用Linux package builder默认的musl
   release target代替本机GNU host。
3. 调用 `fetch_codex_v8_artifacts(spec)`；该函数从lock解析V8版本、下载两行checksum manifest、校验并缓存archive
   与binding。
4. 复算并输出两项实际SHA作为本次审计证据，将两个artifact变量在child env中成对覆盖。
5. `exec`调用原命令，完整保留其stdout/stderr、信号和退出码。

`just test-with-codex-v8` 应复用现有测试recipe的环境和命令骨架：

```text
RUST_MIN_STACK=<既有值> NEXTEST_PROFILE=local \
python3 ../scripts/with_codex_v8_artifacts.py -- \
  ../scripts/with-build-lock.sh cargo nextest run --no-fail-fast <调用者参数>
```

### 5.2 轻量设施验证

从worktree的 `mydev/` 执行包装脚本单元测试；随后运行仓库格式工具。单元测试不得联网或启动Cargo。

### 5.3 三段正式门禁

以下均从worktree的 `mydev/` 执行，且每条都由新入口进入看门狗：

```text
RONDO_V8_CANARY_EXPECT_SANDBOX=1 just test-with-codex-v8 \
  -p codex-v8-poc --no-default-features --features sandbox \
  --retries 0 --flaky-result fail \
  -E 'test(/sandbox_feature_matches_linked_v8/)'

just test-with-codex-v8 \
  -p codex-code-mode-host --retries 0 --flaky-result fail \
  -E 'test(/remote_session_persists_values_forwards_delegates_and_controls_cells/)'

just test-with-codex-v8 --retries 0 --flaky-result fail
```

canary必须精确执行1项；host smoke必须精确执行1项。workspace结束后解析完整JUnit，另核对V8 POC单向蕴含
和Code Mode相关目标确实执行且未skip。

### 5.4 收口与交付

- 检查每轮watchdog summary的 `final_rc`、stop/cleanup、项目/target峰值和JUnit路径/SHA。
- 独立解析JUnit根统计与testcase节点，记录实际执行、failure/error/skip；失败/skip列出完整测试名。
- 更新本计划当前状态、Plan 004实时状态、WBS当前阶段和WBS-COMPLETED历史，详细过程只写本任务agent log。
- 运行最终格式/diff检查，审查工作树diff后提交本分支；不合并、不推送。

## 6. 失败语义与分流

| 阶段 | 失败 | 处理 |
|---|---|---|
| 资产准备 | 404、网络错误、target不支持、manifest非两行、任一SHA错误 | 非零退出且不启动Cargo；记录为资产门禁失败，不启用源码构建 |
| sandbox canary | 0匹配、构建失败、linked sandbox=false、skip | G族仍未完成；只修直接相关的入口/canary/V8测试缺陷 |
| host smoke | host未启动、协议/JS执行失败、timeout、skip | Code Mode真实链路未通过；只修直接相关的V8/host/runtime测试问题 |
| workspace | 看门狗72/125/137或证据失败 | 视为资源/设施失败，不算代码红；按原因恢复后只重跑该唯一正式尝试并记录前次 |
| workspace | V8/Code Mode相关测试失败 | 允许本任务内窄修并原样重跑相关定向；workspace仅在修复后补一次完整复验 |
| workspace | 其他模块失败 | 不扩大修复；记录完整差集，Plan 004仍不宣称workspace全绿 |
| workspace | skip | 逐项审查；Plan 004目标项或V8/Code Mode skip直接不通过，平台/显式ignored项单列而不冒充执行通过 |

## 7. 记录与可审查证据

本任务新建一份时间戳agent log，至少包含：

1. Git起点、工作树/分支、最终提交与dirty状态。
2. 实际修改文件和“薄接线而非新基建”的实现说明。
3. V8 crate版本、rustc host target、release tag、三份资产名、archive/binding实际SHA以及是否命中cache。
4. 每条正式命令的完整文本、开始/结束时间、首次结果、必要重跑及理由。
5. 每轮watchdog run目录、summary关键字段、JUnit路径/SHA和独立XML统计。
6. workspace所有failure/error/skip名称；若为全绿，仍记录总testcase和已审查skip边界。
7. 明确列出未运行项：不运行V8源码构建、Bazel、Windows/macOS、Docker、真实API、真实浏览器、CI或发布。

`.codex/` 下的watchdog/JUnit继续作为git-ignored机器证据；agent log记录足以定位与复核这些工件的run id和hash，
不把大体积原始XML提交进Git。

## 8. 当前状态

### 已完成

- [x] 阅读根与 `mydev/` 规则、README、WBS、Plan 004、计划模板、实施/独立验收日志。
- [x] 确认 `main/origin/main=dd0ea98` 且主工作区clean；创建本独立worktree与分支。
- [x] 确认当前rustc host为 `x86_64-unknown-linux-gnu`，既有package helper会下载
  `ptrcomp_sandbox_release` archive/binding并双SHA校验。
- [x] 确认历史上同一OpenAI资产已成功支持workspace构建；Plan 004的404来自未注入override的denoland默认URL。
- [x] 冻结轻量实现为“薄包装脚本 + 一个just入口 + 纯逻辑小测试”，不改中央watchdog或产品V8配置。

### 当前工作

- [x] 实现并验证本地资产接线。
- [x] sandbox=true canary 1/1与真实Code Mode host smoke 1/1通过，JUnit均0 failure/error/skip。
- [x] 经用户批准复用原Plan 004 target启动workspace；在测试前编译阶段项目增至195.9GB，watchdog按设计以
  `project_reached_proactive_stop`/final rc 125终止，JUnit absent；不是代码测试红，也不计通过。
- [x] 用户明确允许清理无害中间产物/target后，精确清理已完成整改树56.1GiB与本任务5.1GiB target；第二次
  workspace续编仍因旧target增至194.1GB而触发同一项目主动停线，JUnit absent。
- [x] 精确删除旧target的66.7GB `debug/incremental` 后，第三次原命令完成编译并实际运行14,092项：14,060通过、
  31失败、1超时；另有23项显式ignored。JUnit 14,092 testcase、32 failure节点、0 error/skipped节点，
  SHA-256为`31166103c1b000eb5c9b3e11677df79a49b7a3c6904fcbfb18394f8de66d0337`。
- [x] workspace中的V8 POC 7/7及Code Mode专属crate 167/167通过；严格canary与真实host smoke均实际执行，
  没有V8/Code Mode目标失败。23项ignored已通过只读Nextest列表逐名核对，不含V8 canary或host smoke。

### 后续计划

1. 本工作树提交后，是否合并/推送由用户另行指示。
2. Plan 004的Windows PowerShell门禁留待Windows环境；workspace的32项终态未通过另立测试维护任务，
   不在本V8小任务内扩修，也不为这些无关失败重跑全量。

### 阻塞项

- 本Plan无继续执行阻塞。Plan 004整体仍受Windows目标平台证据和workspace 32项非绿色结果阻塞；macOS未运行
  继续作为非阻断跨平台边界披露。

### 当前验收状态

- 本任务的轻量资产接线、fail-closed边界、sandbox=true canary与真实host smoke均通过；workspace已解除V8资产
  阻断并取得完整JUnit，但整体31失败+1超时，不能称全绿。按本计划失败分流，本任务实现完成且无需V8/Code Mode
  修复，Plan 004仍为部分通过。

## 9. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 增显式 `test-with-codex-v8`，不让所有 `just test` 自动下载资产 | 保持普通开发入口轻量，避免中央看门狗和所有测试隐式联网 | just/本地测试 | 已采纳 |
| 002 | 直接复用 `codex_package.v8.fetch_codex_v8_artifacts` | 既有实现已处理精确版本、两行manifest、双SHA与cache，不应复制action shell逻辑 | 资产准备 | 已采纳 |
| 003 | host取 `rustc -vV`，不用package builder的Linux默认musl target | 本机Cargo测试实际目标是GNU；错用musl archive会造成ABI/链接错误 | target选择 | 已采纳 |
| 004 | 正式入口覆盖ambient双变量并拒绝source build | 验收必须绑定到本次验证的OpenAI资产，不能被来源不明override或源码fallback污染 | 证据完整性 | 已采纳 |
| 005 | host smoke复用现有真实进程集成测试 | 已覆盖host启动、JS、store/load、nested tool和shutdown，无需新增重复重型测试 | Code Mode验证 | 已采纳 |
| 006 | 不重跑default=false与A-F/H-K门禁 | 这些已有可靠证据且不受新薄接线修改；重复运行浪费资源 | 测试范围 | 已采纳 |
| 007 | workspace非V8失败只记录、不顺带修 | 保持任务是Plan 004环境门禁补验，不演变成新一轮全仓维护 | 失败分流 | 已采纳 |
| 008 | 工作树内提交，但合并/推送另等用户指令 | 当前授权包含执行与本地交付，未包含远端状态变更 | Git交付 | 已采纳 |
| 009 | 经用户授权精确清理三个可重建Cargo缓存并复用旧target | 两次195GB项目停线都发生在测试前；保持安全线比抬高阈值更重要 | 资源恢复 | 已采纳 |
| 010 | 第三次workspace视为唯一实际测试执行，不因无关失败重跑 | 前两次没有JUnit/testcase；第三次已完整执行14,092项，重复全量只浪费资源 | workspace | 已采纳 |
| 011 | 以Nextest只读JSON列表审查23项ignored，不运行它们 | JUnit只含14,092个实际testcase，不编码额外ignored名称；列表可机械对账14,115=14,092+23 | skip审查 | 已采纳 |
| 012 | 32项workspace终态失败只记录，不在本任务修复 | V8/Code Mode目标均通过；跨模块修复违反本计划窄范围 | 失败分流 | 已采纳 |
