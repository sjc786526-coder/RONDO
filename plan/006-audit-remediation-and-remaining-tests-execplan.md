# 审查遗留修复与剩余测试最终方案执行计划

> 本计划是本轮执行记忆，不需要额外审批；执行期间实时更新“当前状态”和“关键决策记录”。
>
> 工作树：`.claude/worktrees/0809-claude-fix-acceptance`
>
> 分支：`audit/0809-claude-fix-acceptance`
>
> 起点：`b9f724c`（包含 `17ad414`、`de6f604`、`b9f724c`，未合入 `main`）

## 1. 目标

### 最终目标

1. 修复上一轮独立验收确认未闭合的 F2、F3、F7，以及相应权威文档和证据记录。
2. 修复第一批 hermetic 测试仍存在的覆盖弱化和低风险夹具隐患，不依赖宿主 `/tmp`、home、WSL 或版本号。
3. 将 `plan/004-remaining-test-failures-investigation.md` 从调查草稿修订为可直接实施的最终方案，准确覆盖
   39 个当前严格失败和 2 个附加 hermeticity 事项。
4. 在当前独立工作树完成必要验证并提交；不合并、不推送、不触碰 Claude 工作树。

### 完成/验收标准

- 看门狗以 `cgroup.events: populated`/runner 生命周期作为主存活事实，`cgroup.procs`只作直接成员诊断；D-Bus查询异常不得被当作inactive，终止等待按真实经过时间报告。
- Nextest 证据与本轮建立结构性归属，非 Nextest 命令不复制旧报告；`summary.env` 明确记录报告状态、路径和哈希。
- Guardian evidence 从受 Git 跟踪的显式上游基线事实读取 tag，并同时保留 peeled commit；不再从 crate 版本推导上游身份。
- ancestry 测试继续覆盖“非空 marker 搜遍祖先但未命中”的原分支；home/版本夹具不得留下容易跨缓存或误替换的入口。
- 第一批日志和当前权威文档使用 42/39+2、20.4GB/约142MB等真实口径，不把历史修正过程堆入 WBS。
- `plan/004` 为每族给出精确集合、代码/API 落点、串并行顺序、失败语义、机器可验证门禁与非凑绿红线；
  V8、Landlock、F/G 取证和 external/OAuth 均可直接交给后续 AI 实施。
- 所有 Rust 重型验证只走 `just`/`with-build-lock.sh`，一次一组；fmt/fix 按就近 `AGENTS.md` 执行。
- 最终 diff 无无关依赖、`#[ignore]`、断言弱化、宿主配置修改或 Claude 工作树改动。

## 2. 范围

### 允许修改

- `mydev/scripts/with-build-lock.sh` 及必要的窄测试/探针设施。
- `mydev/codex-rs/core/src/guardian/`、与显式上游基线事实直接相关的 Cargo/Bazel 文件和回归测试。
- 第一批 hermetic 修复涉及的 TUI、skills 测试夹具与测试。
- `doc/WBS.md`、`doc/development-environment.md`、`doc/eval-data-layout.md`、相关方向规划、受影响的
  现有 `agent_log`、本 execplan和最终执行日志。
- `plan/001`、`plan/003` 与 `plan/004-remaining-test-failures-investigation.md` 的数据契约/实施方案同步。

### 不允许修改

- `codex-source-code/`、Claude 工作树、主工作区、宿主 `/tmp` marker、Clash/TUN、代理/DNS、全局工具链。
- 39 个剩余失败本身的产品/测试实现；本轮只把其方案定稿。唯一例外是已属于 A/B 的第一批遗留和看门狗/P0缺陷。
- 不增加依赖、不放行 `198.18/15`、不删除/弱化断言、不新增 `#[ignore]`、不以 skip/超时扩大凑绿。
- 不运行真实 API、真实模型、Docker、发布、上传或远端状态修改。

### 不允许读取/查看

- 项目外个人文件、凭据和无关仓库。允许读取本仓 git-ignored 的既有测试/watchdog 日志作为证据；只读上游快照仅用于核对。

## 3. 硬约束

1. 遵守根 `AGENTS.md`、`mydev/AGENTS.md` 和 `mydev/codex-rs/AGENTS.md`；未知修改一律保留。
2. 重型 Cargo 构建/测试只走 `mydev/scripts/with-build-lock.sh`，优先使用 `just`；一次一组，等待锁，不绕过资源上限。
3. 看门狗修复本身必须 fail-closed：拿不到 cgroup 活性事实时继续监督或主动终止，不得正常收尾。
4. 测试、静态检查、历史日志和本轮新证据分开表述；skip/未运行不能称通过。
5. `plan/004` 的标题和总数不得继续把 2 个附加事项称为严格失败。
6. Landlock 默认门禁使用本地受控 listener；其依据是 seccomp 对 IP socket/connect 无地址分支，而不是未经证明的代理归因。
7. V8 必须同时保留 full workspace 单向蕴含与 canary 的 `default=false`/`sandbox=true` 严格双矩阵。
8. 当前任务授权包含项目工作树内编辑、验证和当前分支提交；不包含合并、推送或任何宿主/远端变更。

## 4. 软性建议

- 看门狗优先让Nextest直接写入逐轮独占目录建立归属，避免复制旧报告或依赖时钟启发式；缺失/无效
  报告要写入summary。
- 上游基线事实保持轻量、编译期可用，tag 与 peeled commit 同处；普通单测不依赖 git-ignored 快照。
- 第一批低风险问题只做窄改：构造期注入优于可变 setter，结构位点版本替换优于整行裸替换。
- 先并行静态复核，主代理统一编辑；Rust/脚本验证严格串行。
- 不在本轮重复完整 workspace 全量；只跑改动模块和小型看门狗 smoke。

## 5. 当前状态

### 已完成

- [x] 确认 `main/origin/main=58cc429`，当前工作树基线 `b9f724c`，Claude 工作树只有其未提交日志。
- [x] 读取根与就近规则、plan example、WBS/开发环境、历次 GPT/Claude 交叉核验、第一批日志和 `plan/004`。
- [x] 确认最终口径为 42 项第一批覆盖、39 个当前严格失败、2 个附加事项。
- [x] 确认 Landlock/V8 分歧清零；历史上游 wget 两次均为 10 秒 `Sandbox(Timeout)`，不是沙箱击穿。
- [x] 建立 6 条并行只读复核线：F2/F7、F3、第一批遗留、A/B、C-G+附加事项、权威文档/证据。
- [x] 落地F2/F7 cgroup/JUnit状态机及7项轻量回归；正式入口在D-Bus缺失时fail-closed且不复制旧报告。
- [x] 落地F3唯一机器事实源、tag+peeled commit meta与独立快照校验脚本。
- [x] 补强skills ancestry/home与TUI sanitizer，纠正第一批42/39+2及资源记录。
- [x] 将 `plan/004` 重写为可直接实施的39严格失败+2附加事项最终方案，并同步当前权威文档。

### 当前工作

- [x] 收集并交叉验证子智能体结果，冻结 F2/F3/F7 和第一批遗留的最小实现。
- [x] 核实 Nextest 同名 `local` profile 的逐轮绝对 JUnit 路径、Bazel compile data 与测试夹具构造 API。
- [x] 收口脚本/代码轻量回归，修订权威文档与最终版 `plan/004`。
- [ ] 在user D-Bus恢复后补跑Rust定向测试与相关clippy；当前不能绕过看门狗。

### 后续计划

1. D-Bus恢复后串行补跑skills、TUI、core定向测试与相关clippy，检查JUnit retained/not_applicable。
2. 复核diff、受保护边界、看门狗summary/JUnit和残留进程，提交当前分支。

### 阻塞项

- 当前宿主 `/run/user/1000/bus` 不存在，受监督 smoke 已按 `watchdog_attach_failed` 返回81；在D-Bus恢复前不得绕过看门狗执行任何重型 Cargo 门禁。

### 当前验收状态

- 42项GitHub脚本测试、bash语法、基线快照校验、Nextest配置探针、fmt/fmt-check与diff-check通过。
- 看门狗和正式just-test入口均在Cargo启动前因user D-Bus缺失返回81；本轮Rust测试/clippy未运行，
  上一轮3,547/3,547通过证据不覆盖本轮F2/F3/ancestry代码。

## 6. 执行顺序与子智能体分工

### 串行准备

- 主代理维护本 execplan、读取规则和历史证据、决定最终范围。

### 并行只读复核

1. F2/F7：脚本状态机、JUnit 归属与可执行 smoke。
2. F3：单一上游基线事实源、Cargo/Bazel和回归。
3. 第一批遗留：ancestry、版本 sanitizer、home override、日志数字。
4. A/B：20项DNS与8项proxy的最终API/测试合同。
5. C-G+附加事项：6+1+1+2+1以及external/OAuth/Landlock的最终取证协议。
6. 文档与证据：权威当前事实、历史日志最小纠错和去重。

### 串行实施与验证

- 主代理统一编辑，避免脚本、计划和文档并发冲突。
- 看门狗先自证可用，再串行运行 skills、core 及必要 TUI 门禁；不得同时运行两组。

## 7. 已知事实与证据索引

- `agent_log/2026-08-09-105456-claude-fix-acceptance.md`：上一轮独立验收和3,547项复跑。
- `agent_log/2026-08-09-130949-claude-verification-consensus.md`：双方共识、修法裁决和 wget 原始证据。
- Claude 最新核验日志：`005-test-hermetic/agent_log/2026-08-09-114033-verification-of-gpt-acceptance.md`。
- `agent_log/2026-08-09-073528-test-hermeticity-batch-1.md`：第一批实现，含待纠正计数/资源。
- `agent_log/2026-08-09-080300-audit-followup-fixes.md`：F2～F7修补，F2/F3/F7需重新打开。
- 上游 wget 原始失败：`.codex/build-study/0.147.0-upstream/test-attempt-08-full-complete.log`；两次约10秒 Timeout。
- RONDO首轮 wget 通过：`003-codex-0.147.0/.codex/p0-0.147.0-full-nextest.log`，约0.040秒。

## 8. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 当前任务继续使用 `0809-claude-fix-acceptance`，不新建或修改 Claude 工作树 | 用户明确要求 | 全任务 | 已采纳 |
| 002 | 严格集合按 39 个失败 + 2 个附加事项管理 | 81减第一批42；migration/OAuth不在严格失败清单 | plan/004、日志、验收 | 已采纳 |
| 003 | F2以`cgroup.events: populated`/runner为主事实，`cgroup.procs`只作直接成员诊断，systemd仅作控制 | D-Bus错误可伪装inactive，根`cgroup.procs`不覆盖子cgroup | 看门狗 | 已采纳 |
| 004 | F7优先使用结构性归属，不以mtime单独推断 | 已复现clippy轮复制旧JUnit | 看门狗证据 | 已采纳 |
| 005 | F3使用显式tag+peeled commit事实，不依赖crate版本或普通单测读取上游快照 | 消除产品版本与上游身份耦合及重复事实；既有集成测试已能发现普通版本漂移 | Guardian evidence、基线升级 | 已采纳 |
| 006 | Landlock使用本地listener且收紧成功条件；wget 10秒机制仍需后续定向诊断 | seccomp无地址分支，历史失败是Timeout | plan/004 | 已采纳 |
| 007 | V8全量单向保证与canary严格双矩阵成对实施 | feature unification只增不减，default=false负责反向故障 | plan/004 | 已采纳 |
| 008 | F7保持`NEXTEST_PROFILE=local`，用逐轮配置把JUnit直接写入独占run_dir | 私有profile会改变测试可见环境；直接输出消除stale归属歧义 | 看门狗 | 已采纳 |
