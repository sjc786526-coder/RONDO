# Claude 对 GPT 验收结论的复核与分歧裁决

## 边界

- 复核输入：`.claude/worktrees/005-test-hermetic/agent_log/2026-08-09-114033-verification-of-gpt-acceptance.md`。
- 结合当前源码、脚本、Nextest 本地帮助、V8 canary 配置和既有验收证据做只读核对。
- 本轮未改产品代码、测试、看门狗或 Claude 工作树，未运行 Cargo/重型测试。

## 总结

Claude 对此前 GPT 验收发现的主要事实核验成立。后续源码复核补出一处限定：既有 evidence bundle 集成测试已硬钉 `rust-v0.147.0`，所以 F3 不是“任意无后缀版本变化仍会全绿”，而是生产语义来源错误、事实重复；这不改变改用单一机器事实源的结论。双方其余关键口径为：第一批实际覆盖 42 项，严格失败清单剩 39 项；external-agent migration 与 OAuth 浏览器副作用是另外 2 个附加事项，不属于这 39 个当前失败；资源峰值必须读取 `summary.env`；F2、F3、F7 和 skills ancestry 回归均未闭环；`plan/004` 当前只能作为调查底稿，修订后才能实施。

需要区分两类“闭环”：F1、F4、F5、F6 已有代码修复并通过对应门禁；其余多项只是缺陷事实和修复原则达成共识，尚未落地代码或验证，不能称为实现闭环。

## 已达成共识并完成实现闭环

1. **F1 rustc stderr 被吞**：根因和修复成立。旧结果的退出状态仍有效，但“无 warning/诊断完整”证据无效；修复后重跑的 fmt/clippy/定向测试可作为当前证据。
2. **F4 测试构造器可见性**：生产构造器恢复私有、测试走 `#[cfg(test)]` 入口，闭环。
3. **F5 Arc 写法**：属于测试文件既有惯例，不应做无关局部重构，维持现状合理。
4. **F6 权威文档表达**：去除修正史、只保留当前事实的方向正确。
5. **第一批主要 hermetic 修复**：版本快照、MCP 动态版本、TUI 项目根缓存、WSL 注入和 home 覆盖的主修法成立；现有三包 3,547 项全通过、4 跳过的运行证据有效。skills ancestry 那一项除外，见下文。

## 已达成事实与修复原则共识，但尚未实现闭环

### F2：终止与存活判断

双方同意当前实现不可靠：D-Bus 不可达时 `systemctl --user is-active` 可返回与真正 inactive 难以区分的结果；主监控和收尾都可能把未知状态误判成已结束；所谓“每 30 秒”实际按重试轮数计数，实测约 366 秒才报告。

后续源码复核将主存活事实收紧为已捕获cgroup路径的 `cgroup.events: populated`（覆盖后代cgroup），
`cgroup.procs`只作根层直接成员诊断，systemd只负责请求终止：

- `populated=1` 即仍有负载，即使根 `cgroup.procs` 为空或D-Bus失败也不得结束监督；
- cgroup 路径消失时，只有 runner 同时结束才能判定已退出，否则按未知状态 fail-closed；
- 报告节奏按 Bash `SECONDS` 等单调经过时间计算，不按重试次数估算；
- 查询失败、终止失败和仍有进程必须分别记录，不能统一吞成 inactive。

原则已统一，状态机和回归测试尚未落地，因此 F2 未闭环。

### F3：Guardian source baseline

双方同意 `CARGO_PKG_VERSION` 不能证明冻结上游基线，单纯新增一个 `rust-v0.147.0` 字面常量也可能在下次迁移时静默过期。

推荐建立一个**受 Git 跟踪的单一机器事实源**，至少同时记录 tag 与 peeled commit，evidence 代码从该事实源取值。基线升级验收脚本可在本地上游快照存在时核对 `tag^{}`，但普通、可移植的 core 单测不应依赖 git-ignored 的 `codex-source-code/`。同样不建议反向解析 WBS/说明文档作为代码事实源；文档应消费或校验机器事实，而不是成为运行时配置。

因此对 Claude 的核心担忧完全赞同，但其三个落法都不宜原样采用：快照核对应属于基线升级验收，文档解析会倒置依赖，纯 checklist 不能防止遗漏。单一事实源的具体文件位置仍待实施时作窄设计，F3 未闭环。

### F7：JUnit 归属与留存

双方同意现有无条件 glob 会把旧 JUnit 冒充为本轮产物，且缺失/陈旧/复制失败均被静默；clippy 轮复制上一轮 JUnit 的相同 SHA 和更早内部时间戳已构成直接反例。

Claude 提出的“让 Nextest 直接写入本轮唯一目录”是首选结构，但当前本机 `cargo nextest run --help` 没有直接的 JUnit 路径参数；仓库只通过 profile 配置 `path = "junit.xml"`。是否能用每轮生成的 `--config-file` 安全指向看门狗目录，需要先做小型探针验证，不能在 plan 中直接当作已知能力。

若暂不改接口，最低可靠方案是：开跑前记录候选报告的 device/inode/mtime-ns/size 和内容哈希，结束后只留存本轮新建或变化的文件；同时识别本轮是否实际为 Nextest 命令，并在 `summary.env` 明确写入 `retained|absent|stale|copy_failed|not_applicable`、留存路径和哈希。仅比较时间戳或 inode/mtime/size 都不足以成为最终证据。

修复方向已统一，直接唯一输出与前后指纹方案尚待探针和实现，F7 未闭环。

### skills ancestry 回归与文档数据

- `project_root_markers = []` 会走提前返回，原测试名要求的“非空 marker 搜索全部祖先后回退”不再覆盖。应改用一个确定不存在的非空 marker，保留原分支语义。
- 第一批应记录为覆盖 42 项、严格剩余 39 项；峰值为约 20.4 GB、swap 最高约 142 MB。不能再引用收尾最后一次采样的 16.4 GB/0 作为峰值。
- `development-environment.md` 中“每 30 秒”“确认 inactive”“每轮 JUnit 可作为权威留存”等表述必须等实现闭环后按真实语义更新。

这些事实和修法无分歧，但代码、日志和权威文档尚未修订。

## 修复方案的收口判断

### Landlock/wget

Claude 担心本地 listener 会把“阻断公网出站”变成“阻断回环连接”。该担心适用于地址级网络策略，但当前被测实现安装的是 seccomp 网络过滤：Restricted 模式直接拒绝 IP socket/connect 等系统调用，并不按回环或公网地址分支。因此一个可控、未沙箱时确实可达的本地 listener，能够更稳定地验证当前产品契约，而且比“任意非零退出即通过”的真实域名测试更强。

最终建议：默认门禁使用本地 listener，清理代理继承，先证明未沙箱控制请求可达，再证明沙箱请求被明确拒绝；断言具体拒绝原因或 listener 未收到请求，不接受 DNS 失败、缺 binary、connection refused 等任意非零。测试名/注释应明确验证“sandbox blocks wget network connect”。若未来确实需要公网 DNS/路由集成覆盖，另设显式 live smoke，不能把它算作默认全量通过条件，也不能用 skip 冒充通过。

Claude 后续核对 seccomp 规则后接受了该判断：回环和公网没有地址级分支，本地 listener 不会缩小当前产品契约。双方现已同意默认门禁使用 hermetic listener，并把测试名/注释收口到“阻断 TCP connect”；可选公网 live smoke 不计入默认全量通过。原则分歧已经消失，代码仍未落地。

### V8 feature unification

双方同意全量 workspace 的 feature unification 合法，不能用 `cfg!(feature = "sandbox") == linked_v8_has_sandbox()` 作为通用断言，也不能通过 skip/排除成员消除失败。

Claude 建议拆成两条契约的方向正确，但“实际链接能力与另一个实际 probe 一致”会成为同义反复；现有 `linked_v8_has_sandbox()` 本身就是实际库探针。推荐收口为：

1. 全量 workspace 永远执行单向保证：本 crate 显式启用 sandbox 时，实际链接库必须启用；本 crate 未启用时允许依赖统一把实际库提升为 sandbox。
2. 官方 V8 canary 保留 default artifact/无 feature 与 sandbox artifact/有 feature 两个独占矩阵，并由 canary 显式传入期望模式，执行严格 `false/true` 断言。
3. full workspace 中“独占矩阵不适用”只能作为记录，不能代替第 1 条真实断言；code-mode-runtime 对 sandbox 链接为 true 的现有断言继续保留。

Claude 后续确认原“合同 A”是同义反复，并接受上述收口。双方还共同强调 canary 的 `default=false` 与 `sandbox=true` 必须成对存在：只有前者能发现探针恒 true 或错误链接，不能只落全量单向保证。原则分歧已经消失；canary 如何传递 expected mode 属实现细节，代码仍未落地。

### Network A/B 分组

Claude 的进一步纠正成立，已无分歧：

- `NetworkProxyState` 有手写 `Clone`/`Debug`，新增 resolver seam 必须同步审查手写实现，不能声称“无 derive 风险”；
- 不能使用被策略明确归为非公网的 `203.0.113.0/24`、`198.51.100.0/24` 作为“公网”测试解析结果；
- resolver 对未登记主机必须返回 DNS 错误，不能 catch-all 返回 IP，否则会破坏 DNS 失败测试；
- B 族只有第 1 项能在测试侧直接 `.no_proxy()`；第 2/4/5 项的客户端由产品函数内部构造，应统一走受控 client/factory seam；core DNS 项归 A 族，shell profile 项单列环境隔离。

这些应写回 `plan/004` 后再进入实现。

## 后续原始证据复核：`sandbox_blocks_wget`

Claude 新发现正确地推翻了“代理污染足以解释失败”的旧归因，但其“还需要先拿原始输出才能区分两种分支”已可由现存日志进一步收口。

纯上游原始日志 `.codex/build-study/0.147.0-upstream/test.log` 保留了两次完整失败：

- 首轮约 10.011 秒，报 `expected sandbox denied error, got: Sandbox(Timeout ...)`，内部 `exit_code: 124`、`duration: 10.002965247s`；
- retry 约 10.010 秒，同样是 `Sandbox(Timeout ...)`，内部 `exit_code: 124`、`duration: 10.002728253s`。

因此对这两次已留存的上游失败，可以确定是 Claude 所列的第 2 类：命令到期后被 fixture 判成非 `SandboxErr::Denied`；不是 `exit_code == 0`，没有沙箱被击穿的证据。RONDO 首轮全量日志中同一用例约 0.040 秒通过，说明该行为并非稳定必现。

同时，源码常量 `NETWORK_TIMEOUT_MS` 实际为 `10_000`，helper 注释仍写“2-second timeout”，该注释本身已经过时。Claude 附录和摘要中出现的“2 秒”也应按 10 秒更正。

证据边界仍需保持：最新严格轮只留下失败名称，没有该轮原始 stderr，不能证明它与上游两次失败必然属于同一分支；但现有证据已经足够把“沙箱击穿”和“已证实代理污染”都排除出上游失败结论。现在未知的是 **wget 为什么在 seccomp 拒绝网络调用后仍持续到 10 秒**，可能涉及 wget 自身重试、解析或环境交互，不能继续无证据归因给代理。

落地建议相应调整：

1. 不必再把“取得历史 dbg 输出”列为前置任务，历史上游分支已经判定；应定向诊断 wget 的持续等待机制，并为最新环境保留完整原始输出。
2. hermetic listener 方案仍然成立，但清理代理或 `--no-proxy` 的理由是保证测试只访问受控目标，不是声称它修复了已证明的代理根因。
3. 用未沙箱控制请求证明 wget 和 listener 可用；沙箱轮限制为确定的单次连接尝试，要求在界内快速结束、非零退出、未触达 listener，并拒绝把 timeout、binary 缺失或任意非零都当作安全断言通过。
4. F7 仍需修复未来每轮证据归属，但本次历史上游失败并非无证据：原始日志仍在。它只不能替代缺失的最新严格轮 stderr。

## 最终状态表

| 事项 | 事实共识 | 修复方案共识 | 实现状态 |
| --- | --- | --- | --- |
| 原审查结论、F1、F4、F5、F6 | 是 | 是 | 已闭环 |
| 第一批版本/TUI/WSL/home 主修法 | 是 | 是 | 主体已闭环；ancestry 除外 |
| 42 已覆盖、39 strict 剩余、2 附加事项 | 是 | 是 | 口径闭环，日志/plan 待改 |
| 资源峰值 20.4 GB、swap 约 142 MB | 是 | 是 | 口径闭环，日志待改 |
| F2 cgroup 存活与 30 秒报告 | 是 | 是 | 未实现 |
| F3 单一机器基线事实源 | 是 | 原则一致，文件落点待定 | 未实现 |
| F7 本轮 JUnit 唯一归属和状态记录 | 是 | 原则一致，需探针选实现 | 未实现 |
| skills ancestry 非空未命中 marker | 是 | 是 | 未实现 |
| Landlock 默认 hermetic listener 测试 | 是 | 是；公网 live smoke 只可另列 | 未实现；wget 最新严格轮机制待定 |
| V8 全量单向保证 + canary 严格 `false/true` 矩阵 | 是 | 是；两类门禁必须成对 | 未实现 |
| Network A/B 根因、分组和红线 | 是 | 是 | plan 待修订、代码未实现 |
| `plan/004` 可直接实施性 | 是：当前不可直接实施 | 是：先修订 | 未闭环 |

## 建议顺序

1. 先用一个小批次闭合 F2、F3、F7、skills ancestry，并同步修正相关日志和权威文档；为 F7 先做配置路径探针。
2. 修订 `plan/004` 的计数、A/B 分组、resolver 约束、Landlock、V8 和取证协议，使其成为可执行入口。
3. 再按修订后的批次逐族修剩余 39 项；external migration 与 OAuth 作为附加设施任务单独计数，不混入失败数。
