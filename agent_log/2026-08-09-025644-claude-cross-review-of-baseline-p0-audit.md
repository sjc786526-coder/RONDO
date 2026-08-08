# Claude 对 0809 基线/P0/测试设施审查批次的独立复核

日期：2026-08-09
被审对象：worktree `.claude/worktrees/0809-baseline-p0-acceptance`，分支 `audit/0809-baseline-p0-acceptance`，
起点 `e43697d`，未提交（21 改 + 3 新增）
审查者边界：本轮只读审查，未修改被审工作树的任何代码/文档，未跑重型 Cargo 测试，未改网络与宿主配置，
未运行 Docker 或真实 API。按用户指示，GPT 已记录的测试事实（跑了什么、通过/失败/跳过清单、报错原文）
直接采信，不重跑；审查重点放在其分析、根因判断、修复处置和结论措辞是否成立。

## 总体结论

**六项任务全部实际完成，结论方向正确，未发现凑绿。** 抽查到的关键事实均可独立复现，
文档改动是**收窄**而不是抬高承诺（把此前"P0 严格验收完成""全绿"类表述改回真实边界），
这一点符合项目"skip/未运行不得表述为通过"的硬约束。

**但有一处高优先级缺陷本轮没有被抓出来**：`.cargo/rustc-throttle.sh` 会把所有 rustc/clippy 的
stderr 丢进 `/dev/null`。这是 2026-08-08 `494742a` 引入的既有缺陷，main 上同样存在，不是本批次
造成；但 GPT 本轮任务 3 的题目正是"看门狗是否可靠"，且它重写的正是出问题的那一行，属于应抓未抓。
详见 F1。

结论：**本工作树的改动可以合并**。F1 与合并无关（合并前后 main 都有这个问题），应作为独立小修处理。

## 一、逐任务审查

### 任务 0（自建 execplan、worktree 纪律）— 通过

- `plan/002-baseline-p0-acceptance-execplan.md` 存在，含目标/范围/硬约束/软建议/当前状态/决策记录，
  与 `plan/plan-example.md` 结构一致，且"当前状态"是执行完的实时状态而非计划稿。
- worktree 纪律核对通过：分支停在 `e43697d`，**零提交**，改动全部以工作区形式留存；
  主工作区 `main...origin/main` 干净；其余三个既有 worktree 未被触碰。
- `codex-source-code/` 未被写入（见下方证据 2），符合"gitignore 目录出问题只汇报不改"的要求。

### 任务 1（基线迁移验收）— 通过，核心事实已独立复现

GPT 的唯一实质更正是"七处文档写了不存在的 commit SHA"。我独立复核：

```
git -C codex-source-code rev-parse rust-v0.147.0      -> 3ed6f04f6bf8b7c46299d1cb1ff99c74ce21a51d  (annotated tag object)
git -C codex-source-code rev-parse 'rust-v0.147.0^{}' -> be6e8eac029b183056b7e4402879f15d2c85f61b  (真实 commit)
git cat-file -t be6e8eac34711945bc47d57635f4759f20f08df9 -> fatal: could not get object info
```

- 旧记录的 SHA 在上游对象库中**确实不存在**，更正成立。
- 两个 SHA 共享前 8 位 `be6e8eac`，高度像是早期某轮 AI 抄对了前缀、编造了后缀。建议后续凡是写
  commit 的地方都用 `rev-parse` 产物，不手抄。
- 更正覆盖面核对：全仓库除 GPT 自己日志里"这个 SHA 不存在"那句引用外，无残留错误 SHA；
  正确 SHA 出现在 10 个文件中，减去本轮新建的 3 个文件，恰为其声称的 7 处。**计数属实。**
- 其余迁移结论（1,543 同名路径变更、双方 6,004 tracked files、15 个 overlay 文件等于三方合并结果、
  lock 仅 135 条 `0.0.0 -> 0.147.0`）属于 GPT 已执行的树级比对，本轮按证据事实采信，未重算。

### 任务 2（P0 复验与修复）— 通过，三处修复经代码级复核成立

**修复 1：捕获点从共享 builder 后移到 transport send point**

- `client.rs` 的 `build_responses_request` 里那行捕获已删除；HTTP 路径在 `client.stream_request(...)`
  前捕获（`client.rs:1470`），WS 路径在拿到 `websocket_connection`（`?` 已保证建连成功）之后、
  `websocket_connection.stream_request(...)` 前捕获（`client.rs:1677`）。语义与其声明一致。
- **我额外查了一个 GPT 没提的风险点**：`build_responses_request` 共有 3 个调用方
  （`client.rs:578 / 1448 / 1561`），捕获只加了 2 处，第 3 处 `compact_conversation_history`
  没有。核实结论是**不构成遗漏**：压缩请求的 `request_kind` 是 `Compaction`，
  被 `capture_final_request` 的 `Turn` 白名单挡掉，原本就不会被捕获。
  顺带的正向效果是：改动后压缩请求连进入捕获函数的机会都没有了。
- WS 侧保存的是完整逻辑 `ResponsesApiRequest` 而不是实际上线的增量 delta，
  即 `E_final` 对 WS 路径**不是逐字节 wire 记录**。GPT 在决策记录 004、
  `doc/WBS/local-approval-model.md` 和 `plan/001` 中都明确改了措辞（"真实 wire shape"→"完整逻辑请求形态"），
  没有含糊过去，处理得当。

**修复 2/3：规范化从全树递归改为结构位点定位**

- 旧实现 `canonicalize_call_ids` 递归改写**任何**名为 `call_id` 的字段，确实会污染
  tool schema / 参数 / metadata 中的同名业务字段；新实现只处理 `input[*].call_id` 和
  `input[*].internal_chat_message_metadata_passthrough.turn_id`。
- 回归测试 `normalize_request_canonicalizes_only_structural_item_ids` 是**真实**回归，不是摆设：
  同时断言 `turn_id` 被归一为 `turn_0`、而 `tools.metadata.call_id` 保持 `semantic-a` / `semantic-b`
  两个不同值。旧实现会让这两个断言双双失败。
- `canonicalize_direct_id` 的编号逻辑复核无误（`or_insert` 前算 `next`，同值复用、异值递增，
  两类 id 用各自独立的 map）。

**关于"首轮 15/16、修正断言后 16/16"这一处，我专门查了是否属于改断言凑绿——不是。**
出问题的是新写的 Lite 测试把"字段缺席"错写成"等于空字符串"。核对
`codex-api/src/common.rs:252` 的定义：`instructions` 带
`#[serde(skip_serializing_if = "String::is_empty")]`，`tools` 是 `Option` + skip-if-none。
即被测行为下这两个字段**本就应当缺席**，改成 `is_none()` 是把断言改**对**，测试意图（Lite 请求不带
顶层 instructions/tools）完全保留。

**`guardian_source_baseline`** 取值 `concat!("rust-v", env!("CARGO_PKG_VERSION"))`，
workspace 版本为 `0.147.0`，与测试里断言的 `"rust-v0.147.0"` 一致。设计上把"源码基线"和
"有效 policy 身份"拆开是对的，遗留问题见 F3。

### 任务 3（测试体系复用 + 看门狗）— 主体通过，但漏了 F1

**测试复用：通过。** 独立核对 `git diff --numstat`：

- 无任何 `Cargo.toml` / `Cargo.lock` 改动 → **确无新增 crate 或依赖**。
- 测试改动集中在既有文件（`client_tests.rs` +54/-0、`evidence_tests.rs` +105/-1、
  `guardian/tests.rs` +16/-1），没有新建 test crate、常驻服务或第二套框架。
- 唯一的 `-1` 分别是被扩展的那两行原代码，不是删断言。

**看门狗改动：方向正确，逻辑复核基本成立。**

- `read_counter` / `read_keyed_counter` / `read_psi_full_bp` 从"读不到就返回 0"改成"读不到就报错"，
  配合新增的 `invalid_sample` 校验，把原来的**静默 fail-open**（计数器缺失 = 一切正常）
  改成 fail-closed。这是本轮看门狗改动里价值最高的一处，是真实缺陷修复。
- `memory_nonreclaimable` 的计算被移到校验之后，避免空值在算术上下文里被当成 0。正确。
- `terminate_scope` 引入"SIGSTOP+SIGKILL → 轮询确认 unit inactive"，比原来发完信号直接
  `break` 更可靠；EXIT/INT/TERM/HUP trap 补上了包装器自身被打断时的 scope 清理。
- `rustc-throttle.sh` 从 fail-open 改 fail-closed（退出码 75–80），与 `.cargo/config.toml` 注释同步。
- 我另跑了零成本的 `bash -n`：两个脚本语法均通过（与 GPT 记录一致）。

**保留边界的措辞是诚实的**：明确写了"直接 cargo、app-server client、remote/version-skew 脚本和
Windows Just 分支不能被机制上阻止""不能写成任何 AI 忘记约束都无法绕过"。这符合实际，
没有夸大成"已封堵"。把 `just bench` 和三个 schema generator 接入统一入口也确有其事
（`mydev/justfile` 拆了 `[unix]`/`[windows]` 分支）。

**但任务 3 漏了 F1**，见下。

### 任务 4（全量失败归因，只调查不修）— 通过，纪律遵守到位

- **"只调查不修"经机械核对属实**：全量 diff 里搜不到任何被删除的 `assert*` / `#[test]` /
  `#[tokio::test]` / `expect(` 行，`#[ignore]` 零增减，无 fixture / 快照 / 网络配置改动，
  无审批或沙箱安全逻辑放宽。**未发现任何凑绿行为。**
- 归因矩阵的技术合理性抽查：release 版本写死 `0.0.0`、`/tmp` 祖先 marker 被当项目根、
  测试读到真实 `~/.agents/skills`、WSL 探测把 `Ctrl+V` 变 `Ctrl+Alt+V`、Clash TUN 把域名解析到
  `198.18/15` 触发产品的私网 fail-closed——这几类都是典型的**测试非 hermetic**问题，
  判断"应修测试而不是改产品/改网络"是对的。
- 特别认可两条守住底线的结论：① `198.18/15` 绝不加白名单，产品的 SSRF/local-address 判定是正确行为；
  ② PowerShell safe-command 那条按 target OS 收口，不放宽安全分类。
- 23 个 skip 拆成"17 项合理跳过 + 6 项欠账"，没有把 skip 说成通过，符合硬约束。

### 任务 5（全部经看门狗、一次一组重型）— 通过

- 收口检查项（无活跃 `rondo-build-*.scope`、无 Cargo/rustc/nextest 残留）我在审查开始时复核过一次：
  当时机器上只有开发用 codex 进程，无任何 cargo/rustc/nextest，无锁残留。与其记录一致。
- 本轮所有重型动作（schema 生成、fmt、clippy、P0 定向测试）在日志中都注明经 wrapper 执行，
  并附了 `stop_reason=none/cleanup_reason=none` 与峰值内存（首轮 ~13.0GB、增量轮 ~4.4GB，0 swap）。
  按用户指示采信，未重跑。

### 任务 6（P1 草稿）— 通过，质量高于"草稿"要求

- 结构完整符合 `plan-example.md`，开头明确标注草稿状态与两道未授权门（B1 Docker、B3 真实 API）。
- **不确定项标注得很实在**：Terminal-Bench 2.1 的精确版本/包名/adapter API/task digest 全部列进
  "阻塞项"并声明以 B1 实测为准、"本草稿不预先伪造接口"；这正是用户要求的"未来可能变动的要明说"。
- 硬约束 2 抓到了一个非平凡的点：**Docker daemon/容器不天然属于调用端的 user cgroup**，
  所以不能因为"docker 客户端经过 wrapper"就宣称容器已受监督，必须在 B1 另验容器 limits 与
  Docker 存储计数。这是本草稿里最有价值的一条，避免了把现有看门狗结论错误外推。
- 硬约束 9"不凑绿"、失败处置里 `infra_failed` 不计 agent 成败，与项目既有纪律一致。

## 二、发现的问题

### F1（高）rustc/clippy 的 stderr 被整体丢弃——既有缺陷，本轮应抓未抓

`.cargo/rustc-throttle.sh:90`：

```bash
if ! exec 8>"$slot_dir/$i" 2>/dev/null; then
```

`exec` 后面只跟重定向、不跟命令时，重定向会**永久作用于当前 shell**。因此 `2>/dev/null` 不是
"顺手静音这一句"，而是把整个脚本的 stderr 永久接到 `/dev/null`；紧接着第 95 行 `exec "$@"`
起 rustc 时，rustc **继承了这个 /dev/null**。

复现（零资源消耗，已实测）：

```
$ ./.cargo/rustc-throttle.sh bash -c 'echo E >&2; echo O'
O                                   # stderr 整条消失

$ ./.cargo/rustc-throttle.sh rustc --crate-type lib --emit=metadata --out-dir $T $T/p.rs
rc=0                                # 无任何输出
$ rustc --crate-type lib --emit=metadata --out-dir $T $T/p.rs
warning: unused variable: `x` ...   # 直连时正常
```

影响：

- rustc 的编译错误与警告全部不可见；cargo 是从 rustc 的 stderr 读 JSON 诊断的，所以 cargo 侧
  也渲染不出任何错误明细，只剩"could not compile"级别的空壳信息。
- `cargo clippy` 的 `clippy-driver` 同样经 `RUSTC_WRAPPER` 起，**`just clippy` / `just fix` 的
  警告输出因此是空的**。也就是说 lint 门禁一直处于"看起来永远干净"的状态，其"通过"不构成证据。
- GPT 本轮新加的 `exit 80` 那条错误提示恰好还能看见（`8>` 失败时 `2>` 尚未生效），但这属于巧合。
- **不影响测试结果计数**：nextest 的用例输出来自测试二进制运行期，不走 rustc stderr，
  因此 14,077 / 81 failed / 23 skipped 这类数字不受污染。

来源：`494742a`（2026-08-08，"固化跨入口 rustc 并发闸门"）引入，main 上同样存在，**不是本批次造成**。
但任务 3 的题目就是看门狗可靠性，且 GPT 改的正是这一行，只关注了 fail-open→fail-closed，
没注意重定向作用域，属于应抓未抓。

最小修法（已验证 fd 8 仍能保留、stderr 在花括号组结束后恢复）：

```bash
if ! { exec 8>"$slot_dir/$i"; } 2>/dev/null; then
```

### F2（中）"有界重试"的说法不完全准确

`terminate_scope` 内部是有界的（10 轮 × 10 次 0.1s 轮询）。但三处调用方都是无界外层循环：
监控主循环的 `terminate_scope ... || { sleep 1; continue; }`、`handle_exit` 与 `handle_signal` 里的
`while systemctl is-active; do terminate_scope || sleep 1; done`。若 scope 因 D 状态进程杀不掉，
包装器会无限期挂着重试，没有全局超时或升级手段。

方向上是安全的（不会假装成功返回），systemd 的 `MemoryMax=21G` 仍是硬兜底，所以不算缺陷；
但日志里"有界重试并确认 unit inactive"这句应改成"内层有界、外层持续重试直到确认停止"，
否则会给人"最坏情况会自行退出"的错觉。

### F3（低）`guardian_source_baseline` 取的是本地 crate 版本，不是上游 tag

`GUARDIAN_SOURCE_BASELINE = concat!("rust-v", env!("CARGO_PKG_VERSION"))`。当前 workspace 版本
恰好是 `0.147.0`，与上游 tag 一致，所以值是对的。但这个字段的**语义**是"Guardian 源码基线（上游）"，
取值来源却是"RONDO 自己的 crate 版本"。一旦 RONDO 将来独立版本号（哪怕只是加个 `-rondo.1`），
这个字段会在无人察觉的情况下说谎，而它正是 P1 用来分层的键。
建议：要么加注释锁死"本项目版本必须等于上游 tag 版本"，要么改由构建期从固定常量/迁移记录取值。

### F4（低）为测试放宽的可见性未做 cfg 隔离

`GuardianEvidenceRound::new` 从私有 `fn` 改成无条件 `pub(crate) fn`，只为 `client_tests.rs` 使用；
`mod.rs` 里的 re-export 倒是做了 `#[cfg(test)]`。建议 `new` 也加 `#[cfg(test)]` 或保持私有 + 测试内构造。

### F5（低）`guardian/tests.rs` 里 `Arc::get_mut(&mut turn).expect(...)` 偏脆

依赖 `make_session_and_context_with_rx()` 返回独占 `Arc`。将来该 helper 若多留一份引用，
测试会 panic 而不是静默误绿——失败方向是安全的，可以接受，记录备查。

### F6（低）实时文档里留了修正史

`doc/WBS.md`、`doc/development-environment.md` 现在含"2026-08-09 独立复验修复了…""因此不能继续称为…"
这类表述。按 CLAUDE.md §4，除 `WBS-COMPLETED.md` 外的文档应只呈现最新状态，修正过程放 plan/日志。
本次情况特殊（原文是错的，需要显式否定），可以接受；建议合并后下一次整理时把这两处收敛成陈述句。
`WBS-COMPLETED.md` 用追加式"2026-08-09 独立复验更正"小节则完全合规。

### F7（低，GPT 已自述）证据保存缺口

最新严格轮的原始 stdout/JUnit 未保留，只能靠清单和另两轮 raw log 交叉归因。这不阻塞当前结论，
但会阻碍对那 81 项的更细时序复盘。建议后续全量运行统一保留 JUnit XML。

## 三、独立复核证据清单

1. tag/commit 三方核对：`rev-parse rust-v0.147.0` = `3ed6f04f…`（tag object），
   `^{}` = `be6e8eac029b…`（commit），旧 SHA `git cat-file -t` 报 could not get object info。
2. 上游快照未被污染：`codex-source-code` `git status --short` 为空，`## HEAD (no branch)`（detached），
   `git diff 'rust-v0.147.0^{}'` 为空 → 工作树与 tag 逐字节一致。
3. 无依赖变化：`git diff main --stat -- '**/Cargo.toml' '**/Cargo.lock'` 为空。
4. 无凑绿：`git diff main -- '*.rs' | rg '^-' | rg 'assert|#\[test|#\[tokio::test|panic!|expect\('` 无输出；
   `#[ignore]` 增删为零。
5. 捕获点覆盖面：`rg 'build_responses_request'` 得 3 个调用方，第 3 个是 `compact_conversation_history`；
   `CodexResponsesRequestKind` 含 `Turn/Prewarm/Compaction/Memory`，`capture_final_request` 白名单为 `Turn`
   → 压缩路径本就不在捕获范围，非遗漏。
6. Lite 断言修正的正当性：`codex-api/src/common.rs:254` `instructions` 带
   `skip_serializing_if = "String::is_empty"`，`tools` 为 `Option` + skip-if-none。
7. 脚本语法：`bash -n mydev/scripts/with-build-lock.sh`、`bash -n .cargo/rustc-throttle.sh` 均通过。
8. F1 复现：见上文两组对照命令；`main:.cargo/rustc-throttle.sh:79` 含同样的 `2>/dev/null`，
   引入提交 `494742a`。
9. 机器状态：审查开始时无 cargo/rustc/nextest/`rondo-build-*.scope`，无构建锁残留。

## 四、本轮未做 / 边界

- 未重跑 GPT 已跑过的任何测试（schema/fmt/clippy/16 项 P0 定向、两轮完整 workspace），
  按用户指示直接采信其记录的事实部分。因此**本审查不独立证明代码可编译或测试为绿**，
  只证明改动的逻辑、覆盖面与措辞成立。
- 未运行 Docker、Bazel、真实 API/模型。
- 未修改被审工作树的任何文件（本日志除外）。
- 迁移的树级统计（1,543 路径 / 6,004 files / 三方合并等价 / lock SHA-256）属采信项，未重算。

## 五、结论与建议

1. **建议接受并合并本工作树。** 六项任务实际完成，无凑绿，文档是收窄承诺而非抬高。
2. **F1 另立小修**，一行改动，与本次合并无关（main 上本来就有）。修完建议顺手跑一次
   `just clippy`，因为在此之前的 lint 结论都是在"看不见警告"的前提下得到的，需要重新确认一遍。
3. F2 属措辞订正，F3/F4/F5 属可延后的小改进，F6 待下次文档整理时收敛，F7 建议后续全量统一存 JUnit。
4. 任务 4 归因矩阵可以直接作为"测试维护批次"的输入；按 GPT 建议的顺序
   （release + fixture 隔离 → network no-proxy/resolver → exec-server 定向 → 时序 flaky 保 raw）推进，
   不混入 P1。
