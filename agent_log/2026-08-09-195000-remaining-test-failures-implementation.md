# plan 004 剩余测试失败实施

日期：2026-08-09

## 范围与工作树

- 从本地 `main@37b0e66` 创建 `.claude/worktrees/0809-remaining-test-failures`，分支
  `0809-remaining-test-failures`；全部代码、测试、文档与构建均在该工作树完成，未修改宿主配置，未合并或推送。
- 按 `plan/004-remaining-test-failures-investigation.md` 实施A-I共39个严格失败合同，并处理J external migration与
  K OAuth两个附加设施事项。所有Cargo构建、测试与clippy均通过 `mydev/scripts/with-build-lock.sh` 串行执行。
- 不处理external生产git超时/后代清理，不改Landlock另外6项legacy共享helper合同，不改产品sandbox/审批策略，
  不进行V8源码构建或Windows目标平台替代验收。

## 实质修改

### A：DNS确定性

- `NetworkProxyState` 增加私有、可克隆的host lookup协作者，生产默认仍调用系统解析；reload和execution-token clone
  保留同一resolver。测试builder只允许精确登记的小写hostname，登记项映射到 `8.8.8.8:<原端口>`，未知项返回
  `NotFound`，没有catch-all。
- network-proxy的20个点名测试逐项注入所需hostname；显式DNS失败用空映射。core managed-proxy decider测试改用
  公网字面IP，断言403、allowlist拒绝、`not_allowed`而非local-address拒绝，并证明decider恰调用一次。

### B/C：Direct HTTP测试路由与session proxy

- `OutboundProxyPolicy` 增加经审计的 `#[doc(hidden)] Direct` 路由；route-aware同步/异步解析在系统/PAC/env前短路，
  client builder强制 `no_proxy`，legacy CA fallback不作用于Direct。产品配置只映射
  `ReqwestDefault`/`RespectSystemProxy`，并有静态/运行时回归防止选择Direct。
- codex-api、CLI doctor、remote plugin search、exec-server logging、ollama等消费者改用本地listener或注入probe，
  listener accept有界；不靠ambient proxy/DNS制造失败。
- 三个需要确定transport失败的HTTP fixture保持一个已绑定但不监听的loopback socket直到请求结束，避免
  “bind临时端口后drop”被并发进程抢占的TOCTOU。
- managed shell回归只排除当前session注入的managed proxy URL和active marker，允许login shell合法重载用户profile，
  并要求最终 `HTTP_PROXY` 不等于本session managed URL。这是刻意走真实login-shell的具名产品合同例外；测试代码
  不直接打开或记录profile内容，不把它表述为完全独立于home/profile执行。

### D：Landlock wget

- 新wget测试使用独立loopback HTTP listener；同一binary先跑未沙箱控制轮并必须取得精确响应，再跑沙箱轮。
  沙箱轮要求现有执行层分类为 `SandboxErr::Denied`，并在listener端机械确认没有第二个连接。
- control listener的accept使用nonblocking轮询和2秒deadline，accepted stream另有2秒read timeout；wget未连接或参数
  异常时不会在thread join处无限等待。
- 不复用、不修改 `assert_network_blocked` 及其另外6个legacy调用者。最终wget保留stderr诊断；quiet模式会把
  seccomp EPERM抹成无输出exit 4，无法与DNS/拒连/任意非零区分。

### E/F：fixture边界与Windows分类

- config/git/realtime测试改用非空唯一project marker或fixture-bounded FS；fixture根外metadata返回NotFound。
  realtime新增私有FS seam，grouping、current group和 `format_thread_group` label三处贯穿同一FS。
- secrets抽出 `environment_id_from_cwd_with_repo_root`，一个纯测试同时覆盖无repo与显式repo根。
- PowerShell import与finder只在Windows目标编译；Bash/Zsh跨平台合同和非Windows拒绝PowerShell的安全测试保留。

### G：V8 feature合同与manifest校验

- workspace测试始终执行单向兼容性蕴含；仅当 `RONDO_V8_CANARY_EXPECT_SANDBOX` 显式为严格 `0`/`1` 时执行
  双向独占canary，非法值失败，不新增Cargo feature。
- manifest校验发现 `code-mode` 已无feature但脚本仍保留白名单，删除这一条stale exception；v8-poc现有例外不变。

### H：realtime与remote replay时序

- realtime原测试的WebSocket fixture会自动transport-close，导致第二次POST的tail被steer进初始turn，测试实际没有
  覆盖两次显式close。改为保持WebSocket存活、gated SSE，并以初始/尾部 `TurnComplete`、thread-idle hook、精确
  submit id、第二次POST通知和最终真实POST/请求体计数形成确定性屏障。
- `ResponseMock` 增加Notify驱动的request-count等待；去除sleep轮询。统一exec测试保留原1024并发与全部timeout，
  增加phase/output/POST/child状态快照，失败能区分模型请求前、首请求后和exec lifecycle阶段。
- truncated replay改为仅该exact test在移除所有managed proxy环境键的子进程内运行。原因是修改后唯一残余失败发生于
  0 Responses POST、0 exec event，属于ambient proxy影响的模型请求前阶段，不是pushed/replay竞态。
- 目标realtime close测试不再用禁网宏提前成功；检测到禁网标记时显式失败，避免Nextest/JUnit把未执行主体记成passed。

### I：empty workspace roots

- bwrap缺失不再 `return Ok(())`；同一remote backend先做包含临时根的正对照，再清空roots做负用例。
  两轮共享command/cwd/helper，补齐remote运行需要的 `:minimal`、ProjectRoots与PATH；负例精确断言沙箱启用、文件
  未读取、closed和路径访问拒绝，helper/加载器/command/timeout不能冒充成功。
- 该场景的旧pushed-event collector可见closed却丢stdout，改用专用terminal read collector；pushed与close后replay
  语义继续由现有两条独立生命周期测试承担，没有用read collector虚构事件覆盖。
- 新增SandboxType import、输出结构与helper均保持 `cfg(unix)`，保留基线macOS Seatbelt测试的编译/覆盖入口；本次仅在
  Linux/WSL执行，未把未运行的macOS门禁称为通过。

### J/K：external与OAuth副作用

- external内部增加crate私有的generic async fake-adder seam；生产wrapper仍调用真实 `add_marketplace`。原真GitHub
  组合测试原位改成fake-adder测试，精确断言官方source/ref/sparse、一次调用、本地manifest、outcome和config；另补
  纯source推导测试并保留相对本地marketplace测试。门禁期间没有GitHub DNS/connect或git子进程。
- rmcp新增自描述 `BrowserLaunch::{Enabled, Disabled}`；CLI新增 `mcp login --no-open-browser` 并让首次/去scopes重试
  透传同一值，core两次生产调用及silent wrapper显式保持Enabled。URL打印、callback、token保存不依赖launcher。
  私有launcher seam分别证明Disabled为0次、Enabled为1次；cloud fixture隔离失败改为fail-closed，不再提前成功返回。

## 关键诊断与决策理由

1. H修改前realtime的10线程压力为199/200；truncated两组均197/200。轨迹证明前者是fixture自动close造成的合同错位，
   后者同时存在0 POST与首POST后停滞两类phase，因此先修可观测性与真实turn屏障，再隔离exact test的ambient proxy。
2. I修改前200轮仅3轮通过、197轮timeout。补齐同helper前提后，event collector仍可closed但无stdout，而read terminal完整；
   采用read collector并保留独立pushed/replay门禁，比放宽timeout或把无输出非零当拒绝更准确。
3. D首轮最终测试返回exit 4且无stderr，是测试自己的 `-q` 抑制了EPERM。移除quiet后现有拒绝分类器得到明确
   `operation not permitted`，listener未连接断言不变，没有降级成“任意非零通过”。
4. `Direct` 的doc-hidden unit variant触发 `manual_non_exhaustive`。它是真实跨crate测试路由而非兼容哨兵，故加带理由的
   局部lint豁免；删除variant或改 `#[non_exhaustive]` 都不能满足确定性构造合同。
5. V8 sandbox=true下载URL返回确定的HTTP 404，说明v150.4.0没有该目标预编译资产。按计划记未运行，不自动扩大为
   `V8_FROM_SOURCE=1` 重型源码构建，也不通过过滤V8把第二次运行伪装成workspace全量。
6. truncated父测试原先只检查子进程exit 0，但Rust测试二进制零匹配也可能成功退出。增加完整exact test名与
   `1 passed` 输出断言，确保proxy-free子进程确实运行目标测试而不是零匹配假绿。
7. 独立审查指出C族“完全不依赖home/profile”的总述与真实login-shell合同冲突。保留产品行为，收窄文档为具名例外，
   因为制造受控shell会把测试从当前产品入口移开，反而不再验证session managed proxy清理。
8. Landlock仅设置stream read timeout不能约束accept；改成nonblocking accept+deadline，同时保留stream timeout。
9. I族一度把目标及新helper收窄到Linux，这会删除原有macOS Seatbelt覆盖；统一恢复 `cfg(unix)`。
10. Direct虽排除了ambient proxy，但释放临时端口仍可能被抢占；用保持绑定的非监听socket取得确定connect failure。
11. H的禁网宏会把提前返回记作passed；仅对本计划目标测试改为显式失败，未扩张清理全文件历史宏调用。
12. 提交前严格clippy发现truncated子进程失败消息仍用旧式format参数；仅改成等价inline format args，保留完整
    stdout/stderr诊断并原样复验，没有放宽lint。

## 验收证据

- 前置：watchdog Python回归9/9、bash语法、cgroup smoke和真实Nextest/JUnit 1/1均通过。
- H修改后四组压力均200/200、0 failure/error/skip：realtime 1/10线程run
  `20260809-190338-1000-695860` / `20260809-190508-1000-720055`；truncated 1/10线程run
  `20260809-191127-1000-763175` / `20260809-191322-1000-781597`。
- I修改后200/200、0 failure/error/skip：run `20260809-183819-1000-632851`，JUnit SHA-256
  `7cf2b5f37327e43fcddc40327208275f837c036d8014f1de11f1e675df592a28`。
- A：network定向40/40、整包205/205、core 1/1；B/C：定向24/24；D：1/1；E：6/6；F：1/1；
  J：3/3；K：4/4。代表性run id记录在ExecPlan §17，26份绿色JUnit的逐份run id与SHA矩阵见后续独立验收日志
  §7；全部使用 `--retries 0 --flaky-result fail`。
- G default=false canary 1/1（run `20260809-192947-1000-909276`）和manifest脚本通过。sandbox=true run
  `20260809-193011-1000-912361` 在测试执行前因官方预编译资产404失败，不能记通过。
- `just fmt`、`just fmt-check` 通过；受影响crate `just fix` 与workspace配置lint的 `just clippy` 通过（run
  `20260809-193437-1000-936925` / `20260809-193855-1000-971128`，JUnit均正确为not_applicable）；该clippy run
  没有统一显式传入 `-- -D warnings`。后续带 `-- -D warnings` 的严格门禁为五个审查后受影响crate的run
  `20260809-200429-1000-1103492`。clippy fix后
  H最终文件具名回归2/2通过（run `20260809-194348-1000-1014436`）；补子进程非零匹配断言后truncated最终回归
  1/1通过（run `20260809-195026-1000-1037637`）。
- 独立只读解析26份正式JUnit，逐份testcase数量与命令匹配，failure/error/skip均为0，SHA与watchdog summary一致。
- Landlock有界accept修订与I族Linux路径的中间回归2/2通过：run `20260809-195141-1000-1041018`，JUnit SHA-256
  `07fb3110ba7672530c0d161a5dad4f027c31920569f88e07f10bd9ee42f0851a`。最终B/D/H/I联合回归6/6通过：run
  `20260809-195832-1000-1068951`，JUnit SHA-256
  `de9ae140ceb458613ea8b17b170f6e6b2380ceb3836074e59b054603ec42a7ef`。两份均为0 failure/error/skip，
  stop/cleanup reason均为none。
- 审查后严格clippy首轮run `20260809-200154-1000-1088950` 在编译期因一处`uninlined_format_args`退出101；
  等价机械修正后原样重跑通过，run `20260809-200429-1000-1103492`，stop/cleanup reason均为none。最终
  `just fmt-check`、manifest校验与 `git diff --check` 通过。
- H禁网fail-closed负对照设置 `CODEX_SANDBOX_NETWORK_DISABLED=1` 后同一exact test按预期失败：run
  `20260809-200731-1000-1108959`，JUnit为1 testcase/1 failure/0 error/skip，SHA-256
  `7ecb8037a47d9ae4931344ed47ca6c41ac7d4bb006eac3823842a0ed10dec152`。该预期红色诊断不计入绿色验收，
  证明禁网前提不再静默返回成功。
- 唯一一次严格workspace命令 `just test --retries 0 --flaky-result fail` 的run
  `20260809-194124-1000-981676` 在测试启动前同样因V8 sandbox资产404退出101；summary为
  `junit_status=absent`、`stop_reason=none`、`cleanup_reason=none`，没有workspace测试结果。

## 未完成与诚实边界

- Windows PowerShell同名测试未在Windows目标平台运行；WSL通过不替代该证据。empty-roots保持Unix/macOS覆盖入口，
  但本次未在macOS运行。
- V8 sandbox=true独占canary和workspace全量被缺失的官方预编译资产阻断；实现已编译通过default V8模式，但不能称
  sandbox模式或完整workspace全绿。
- 没有运行Bazel；本机环境本就未安装Bazel。没有运行Docker、真实API、真实浏览器、GitHub clone或远端写操作。
