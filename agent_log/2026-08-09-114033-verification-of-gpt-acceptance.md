# 对 GPT 验收结论的独立核验

日期：2026-08-09
工作树：`.claude/worktrees/005-test-hermetic`（`b9f724c`）
被核验对象：`.claude/worktrees/0809-claude-fix-acceptance/agent_log/2026-08-09-105456-claude-fix-acceptance.md`
与同目录 `plan/005-claude-review-and-test-fix-acceptance-execplan.md`
边界：本轮只做核验与记录，**未修改任何代码**，未跑重型测试，未改宿主/网络，未合并、未推送。

## 总评

**GPT 的验收结论我逐条复核后全部认可，没有发现误报。** 它指出的每一处问题我都独立复现到了硬证据，
其中 F7 和资源数字两项，证据比它给出的还要更强或更具体。我自己的错误分三类：
数数错（42/39 报成 40/41）、读错字段（把最后一次采样当成峰值）、以及三处"已闭环"判断下早了
（F3、F7，外加 skills 覆盖被弱化没自觉）。

分歧只集中在**部分修复方案的取向**，不在事实层面。下面第二部分逐条列出。

---

# 第一部分：已达成共识的闭环结论

## 1.1 我对 GPT 上一轮工作的交叉审查 —— 双方认可

GPT 接受我的审查结论（SHA 更正、上游快照未污染、P0 捕获路径、第三个 `build_responses_request`
调用属 Compaction 不构成遗漏、无依赖变化、无删测试/无新增 ignore）。这部分不再重复取证。

GPT 对我一处措辞提出收窄，**我接受**：我在审查日志第 179 行写"lint 门禁一直处于'看起来永远干净'的
状态，其'通过'不构成证据"。准确说法是——stderr 被吞只让**警告不可见**，
不会吞掉子进程的非零退出码，硬编译错误仍会让构建失败。由于 `just clippy` 是
`cargo clippy --tests`（没有 `-D warnings`），警告本来就不影响退出码，所以丢失的是
"这轮有没有警告"这一项证据，不是全部返回状态。我的原话偏宽。

## 1.2 F1 / F4 / F5 / F6 —— 双方认可关闭

无异议。F5 我把"偏脆"改判为"不改"，GPT 同意理由（是该测试文件既有惯例、失败方向是显式 panic）。

## 1.3 失败计数：我错，GPT 对

按 `agent_log/2026-08-08-233753-p0-strict-acceptance.md` 里的 81 项终态清单机械统计：

```
codex-tui 35 | codex-network-proxy 20 | codex-core 10 | codex-mcp-server 4
codex-skills-extension 3 | codex-exec-server 2 | 其余 7 个包各 1
codex-tui 细分：status 19 + chatwidget 10 + history_cell 4 + bottom_pane 2 = 35
```

- 第一批实际覆盖 **42** 项（TUI 35 + MCP 4 + skills 3），不是我写的 40。
- 剩余严格失败 81 − 42 = **39** 项，不是我写的 41。
- 清单中**不含** external migration 与 OAuth 浏览器两项（已 `rg -i 'migration|oauth'` 确认为空）。
  它们是附加治理项，不能计入失败数。GPT 的"39 个失败 + 2 个附加工作项"是正确口径。

我的错法：把 codex-tui 记成 33（漏掉 bottom_pane 那 2 项没并回总数），chatwidget 记成 9（实为 10），
两处相抵后得到 40。属于纯粹的清点疏忽。

## 1.4 资源数字：我错，GPT 对，且我的错因可定位

逐份 `summary.env` 统计（13 轮）：

| 轮次 | rc | stop | memory_peak_sampled | swap_peak_sampled |
|---|---|---|---|---|
| 030821（TUI 快照重生成） | 0 | none | **20,403,429,376** | 0 |
| 033145（三包联跑） | 0 | none | 12,940,890,112 | **141,979,648** |
| 075117（core 定向） | 0 | none | 16,565,501,952 | 0 |
| 105318（GPT 独立复跑） | 0 | none | 19,563,085,824 | 0 |

第一批全局最高内存 **20,403,429,376 B（20.4 GB）**，最高 swap **141,979,648 B（约 142 MB）**。
我在日志里写的"内存峰值 16.4GB、swap 0"错了。

**错因**：我抄的是首轮 stdout 里那行 `[rondo] command=cargo elapsed=226s ... memory=16439394304`，
那是**最后一次采样值**，不是峰值；峰值只在 `summary.env` 的 `memory_peak_sampled_bytes` 里。
这是个可复发的坑，值得记下来：**以后引用资源数字一律读 summary.env，不读 stdout 的收尾行。**

GPT 同时指出"没有触发资源停止，安全结论未受影响"，这点成立：13 轮 `stop_reason` 全为 `none`。
另外 20.4 GB 是 `memory.current` 口径，与 `nonreclaimable_stop_bytes`（20,401,094,656，
针对 anon+kernel）不是同一个量，数值接近属巧合，不代表擦线。

## 1.5 F2 未完成：确认，且比 GPT 描述的更严重

**(a) "每 30 秒"是错的。** 实测 `systemctl --user is-active --quiet` 单次约 **9.9 ms**。
`terminate_scope` 单轮 = 10 attempts × (12 次 systemctl ≈ 0.12 s + 1.0 s sleep) ≈ 11.2 s；
外层再 `sleep 1` → 每次 `waited += 1` 实际约 **12.2 s**。因此 `waited % 30 == 0` 首次触发在
**约 366 秒（6.1 分钟）**，而打印出来的字面是 `30s`。GPT 估的 330 s 与实测同量级，方向正确。
我文档里"每 30 秒打印一次"是错的能力声明。

**(b) `is-active` 的失败与 inactive 不可区分 —— 实测证据比 GPT 陈述的更强。**

```
$ systemctl --user is-active --quiet nonexistent-rondo.scope          -> rc=4
$ DBUS_SESSION_BUS_ADDRESS=unix:path=/nonexistent systemctl --user is-active <unit>
inactive            # ← 总线不可达时，systemd 直接输出 "inactive"
                    -> rc=4
```

不是"可能被当作已停止"，而是**总线不可达时 systemd 明确报告 `inactive`**。
更要紧的是：这个 fail-open **不限于我 F2 改的那段**。主监控循环
`while systemctl --user is-active --quiet "$unit"; do ... done`（原有代码，非本轮引入）
用的是同一个判据。也就是说：**若 user D-Bus 在构建中途失效，整个看门狗会认为 scope 已结束并正常收尾，
把一个无人监督的重型构建留在机器上。** 只修 `terminate_scope_until_gone` 不能关闭这个洞。

结论：F2 判为"部分完成"我接受，并且认为其优先级应高于 GPT 给的定位。

## 1.6 F3 未闭环：确认

我写的测试是：

```rust
assert_eq!(GUARDIAN_SOURCE_BASELINE, format!("rust-v{}", env!("CARGO_PKG_VERSION")));
assert!(!env!("CARGO_PKG_VERSION").contains('-'), ...);
```

第一条是同义反复（只是把常量定义重述一遍），第二条只拦得住**带后缀**的版本。
若 RONDO 把 workspace 版本改成无后缀的 `0.148.0` 而上游基线仍是 `rust-v0.147.0`，
测试照样通过，`guardian_source_baseline` 照样写出一个不存在的上游 tag。
**我声称它"守住了不变量"是不成立的**，F3 不能算关闭。

## 1.7 F7 未闭环：确认，且我复现出了直接证据

GPT 说"07:54 的轮次复制了内部时间 07:53 的旧报告"。实测：

```
round_start=075117  内部 timestamp=2026-08-09T07:53:34.458+08:00  tests=17 failures=0  sha=c7f059d0...
round_start=075417  内部 timestamp=2026-08-09T07:53:34.458+08:00  tests=17 failures=0  sha=c7f059d0...
$ cmp 075117/junit-local.xml 075417/junit-local.xml  -> 内容完全相同
```

`075417` 那轮是 `just clippy -p codex-core`，**根本不跑 nextest**，不会写新的 `junit.xml`；
我那段无条件 glob 复制就把上一轮的报告原样搬了进去，内部时间戳甚至早于该轮开始时间。

所以：复制能力成立，**归属保证不成立**。我在 `doc/development-environment.md` 写的
"需要事后复盘失败清单时以这份留存为准"是错的能力声明。F7 不能算关闭。

## 1.8 skills ancestry 测试覆盖被弱化：确认

`ext/skills/src/host_roots.rs:242`：

```rust
async fn find_project_root(..., project_root_markers: &[String]) -> AbsolutePathBuf {
    if project_root_markers.is_empty() {
        return cwd.clone();          // ← 直接短路，下面的祖先探测整段不执行
    }
    ... 遍历 cwd.ancestors() × markers 探测 ...
    cwd.clone()                      // ← 全部未命中时的回退
}
```

我传 `project_root_markers = []` 之后，测试走的是**短路分支**，
原本要覆盖的"非空 marker 遍历全部祖先、都没命中、回退 cwd"这条路径不再被执行。
测试名叫 `..._without_project_marker_does_not_walk_parents`，字面上也确实是在讲后者。
**GPT 判"覆盖弱化"成立**，且它给的修法（改用一个确定不存在的非空 marker）我复核可行：
未命中时函数末尾仍 `return cwd.clone()`，断言不用改，而 `/tmp/.git` 也满足不了一个自造的 marker 名。

## 1.9 两处低危项：确认

- 版本 sanitizer 用 `line.replace(CODEX_CLI_VERSION, ...)` 做整行裸替换，理论上会误伤同串内容。
  当前版本号是 `0.147.0`，实际用例无影响，属低危。
- `set_home_dir_override` 不清 `cache_by_cwd` / `cache_by_config`。当前两个测试都在首次加载前设置，
  无影响；但作为 setter 语义不完整。

## 1.10 文档能力声明与陈旧项：确认

- `doc/development-environment.md:271-272` 的"每 30 秒""确认 scope inactive"——按 1.5 两条，均不成立。
- 同文件 `:276` 的"以这份留存为准"——按 1.7，不成立。
- `doc/WBS.md:65` 的 P0 表格仍写"本工作树复验通过，待审查/合并"。该批已在 `58cc429` 合并进 main，
  **确实过时**。我上一轮只收敛了 §1 的正文，漏了 §3 的表格。

## 1.11 plan/004 中被 GPT 认可的部分

fake-IP、NO_PROXY glob 失效、`/tmp` marker、WSL PATH、V8 feature unification 的根因，
以及"不删 marker / 不放行 fake-IP / 不关 Clash 验证 / 不 ignore 不弱化断言"这组红线，双方一致。

---

# 第二部分：分歧、部分接受、以及"缺陷共识但修复方案我不完全认可"

先说清楚：**没有一条是我认为 GPT 判错了事实。** 下面 D1～D4 是"缺陷承认、但它给的修法我认为还不够
或需要调整"；D5～D7 是我要在它的结论上加限定或补强的地方。

## D1（缺陷共识，修法我认为不够）F3 改用显式 `rust-v0.147.0` 常量

**共识**：当前测试关不住这个洞。

**我的保留**：换成硬编码常量只是把"静默说谎"换成"另一种静默说谎"。
今天写死 `rust-v0.147.0`，下次基线升级到 0.148.0 时，如果没人记得改这个常量，
字段照样会指向一个错误的上游 tag——而且比现在更隐蔽，因为它连"跟着版本走"这点关联都没有了。

**我建议的闭合条件**：常量必须绑定到一个**基线升级任务本来就必须改的单一事实源**，并由测试交叉校验。
可选的落法（按可行性排序）：

1. 在仓库里放一份机器可读的基线记录（例如 `codex-baseline.toml` 里的 `upstream_tag = "rust-v0.147.0"`），
   常量从它读（`include_str!` + 编译期解析或 build script），测试断言它与
   `codex-source-code` 快照的 `git describe --exact-match` 一致（该文件已是只读快照，可离线核）。
2. 退一步：保留硬编码常量，但同时断言它与 `doc/development-environment.md` §3.4 记录的 tag 一致
   （文本比对），让文档成为事实源。
3. 最低要求：硬编码常量 + 在 `CLAUDE.md` 的"上游基线升级"条目里明确列出必须同步修改的位置清单。

单纯把 `env!("CARGO_PKG_VERSION")` 换成字符串字面量，我认为不构成 F3 的关闭条件。

## D2（缺陷共识，修法我要补一条）F7 只归档本轮新写报告

**共识**：当前机制不能证明报告属于本轮，必须修。

**GPT 的修法**："只归档本轮新写报告，并对预期报告缺失/复制失败明确记录。" 我同意方向。

**我要补的**：光靠"比时间戳/比 mtime"不够稳（同一秒内的轮次、时钟回拨、nextest 复用文件）。
建议把判据做成**结构性**的而不是启发式的：

- 归档前先记录 `junit.xml` 的 inode + mtime + size，命令结束后再取一次，**三者任一未变即判定为旧报告**，
  不归档并在 `summary.env` 写 `junit_local=stale`；
- 更干净的做法是**每轮用独立输出路径**：给 nextest 传一个指向本轮 `run_dir` 的 JUnit 路径
  （nextest 支持 `--profile` 级配置或环境变量指定输出位置），从源头消除归属歧义，连复制都不需要；
- 无论哪种，`summary.env` 都必须落一个显式字段：`junit_local=<path|absent|stale|copy_failed>`。
  **"没有报告"必须是一条被记录的事实，而不是一段静默。** 我原来的实现里复制失败是完全静默的，这点 GPT 说得对。

## D3（缺陷共识，修法我认为会改变测试语义）Landlock 改用本地受控 listener

**共识**：我在 plan/004 里写的"清掉代理变量后继续请求公网，对照失败就 skip"确实不 hermetic——
skip 在本项目规则里不能当通过，而且依赖公网可达性本身就是不确定输入。

**我的保留**：GPT 建议改成"本地受控 listener + 先证明未沙箱 wget 可达 + 再证明沙箱路径被阻断且
listener 未收到请求"。这个设计我认可其确定性，但它把测试的**语义**从
"沙箱阻断出网"换成了"沙箱阻断 TCP connect（含回环）"。这两件事在 landlock 下不等价：
回环连接与外网连接走的是不同的规则面，测试名 `sandbox_blocks_wget` 与它在
`assert_network_blocked` 家族里的位置也都是按"出网"来组织的。

**我建议的处理**：接受本地 listener 方案，但**必须同时**
（a）改测试名与注释，明确它证明的是"沙箱内 TCP connect 被拒"；
（b）确认 landlock 的网络规则对回环和非回环是同一条判定，若不是，则这条测试不能替代原有的出网覆盖，
需要另外保留一条明确标注为"需要公网、默认不跑"的 live 用例，而不是让出网覆盖静默消失。
否则这就是我们两边都反对的那类操作——用一个更容易绿的测试替换掉原来的覆盖面。

## D4（缺陷共识，修法需要更具体）E 族 V8

**共识**：我给的三个选项里，选项 2（只在 standalone 生效）和选项 3（移出 workspace）
实质上就是把断言从全量门禁里拿掉，这点 GPT 批评得对，我不该把它们列成可接受的备选。

**我的保留**：GPT 要求"先定义 V8 POC 的矩阵合同"，方向对但没有落到可执行。我认为闭合形态应当是
把现在这一条含混断言拆成两条各自成立的断言：

- **合同 A（两种模式都必须跑）**：`linked_v8_has_sandbox()` 必须与**实际链接进来的 v8 库**的能力一致。
  这需要一个不依赖本 crate feature 的探测口（比如从 v8 crate 自身暴露的常量/符号读），
  没有这个口就先补这个口——这是真正的缺失点。
- **合同 B（只在独占构建下有意义）**：`cfg!(feature = "sandbox")` 与本 crate 的 feature 声明一致。
  这条可以按构建模式条件化，但必须在全量模式下**显式输出一条"本断言在统一构建下不适用"的记录**，
  不能静默跳过。

也就是说：允许"某条断言在某模式下不适用"，但不允许"这个测试在全量下什么都不验"。

## D5（我要补强 GPT 的结论）F2 的 fail-open 范围比它写的大

见 1.5(b)。GPT 把这条写在 F2 的部分接受里，读起来像是我这次改动引入的局部问题。
实际它是**原有看门狗主循环就带的判据缺陷**，我的改动只是把同一个判据复制到了更多地方。

**我建议的修法**（超出 GPT 提的范围）：判活不能只靠 `is-active` 的退出码。
应当以 `cgroup.procs` 是否可读、是否为空作为第一判据（这是内核事实，不经 D-Bus），
`systemctl is-active` 降级为辅助信号；两者矛盾时按"仍然活着"处理（fail-closed）。
这样即使 user D-Bus 整个失效，看门狗也不会误判收尾。
计时同时改成 epoch 差值，打印真实秒数。

## D6（我要补强 GPT 的结论）B 族的分组错在哪，需要写清楚

GPT 说 `#2/#4/#5` 喂不进裸 client。我逐个复核，**它是对的**，但原因值得写明白，否则执行者容易改错地方：

- `#1` `route_aware_client_pool_tests.rs:149` 确实是测试自己 `reqwest::Client::new()` ——
  我的 B-1 修法（换成 `.no_proxy()` client）对这一项**成立**。
- `#2` `codex-api/src/files.rs:589` 调的是产品函数 `upload_openai_file(&base_url, &auth, ...)`，
  client 在函数内部构造；`#4` `core-plugins/src/remote/search_tests.rs:386` 同理，
  经 `recording_remote_plugin_service_config` 进产品路径。这两项**必须走产品侧的直连 seam**，
  测试侧换 client 根本没有落点。

所以正确的分组是 **B-1 只含 #1，#2/#4/#5 全部并入 B-2**。我 plan/004 里的分组是错的，需要改写。
另外 `#4` 不是"连关闭端口"，而是"accept 后立刻 drop stream"，期望的是连接中途的传输错误，
经 SOCKS 代理后错误形态会变——根因同族，但断言的错误类型不同，执行时要分别核对。

## D7（我要补强 GPT 的结论）A 族的两处硬伤

GPT 指出的两点我都复核属实，且证据具体：

1. **`NetworkProxyState` 有手写 `Clone`（`runtime.rs:262`）和手写 `Debug`（`:254`）。**
   我在 plan/004 里写"裸结构体、没有任何 derive、直接加字段即可、§5 风险一节可以整节忽略"——
   **这句是错的，而且危险**：它会让执行者跳过唯一需要小心的地方。加字段必须同步改 `Clone`，
   `Debug` 因为是 `finish_non_exhaustive()` 才不受影响。

2. **我给的示例 IP 会被产品自己判死。** `network-proxy/src/policy.rs:52-70` 的
   `is_non_public_ipv4` 明确把 `198.51.100.0/24`（TEST-NET-2）、`203.0.113.0/24`（TEST-NET-3）、
   `198.18.0.0/15` 都列为非公网。我示例里 `"blocked.com" => 203.0.113.10` 和
   catch-all `_ => 198.51.100.10` **照抄就会复现同一个 NotAllowedLocal 失败**。
   必须换成真正的公网地址，且注释要写明"这里不能用文档/测试保留段"。

3. **GPT 还指出静态 resolver 会打坏既有 DNS-failure 回归——属实。**
   `runtime.rs:1605 host_blocked_rejects_allowlisted_hostname_when_dns_lookup_fails` 用
   `does-not-resolve.invalid` 走的正是 `host_blocked`，依赖真实解析失败。
   我那个 catch-all 返回 `Ok(...)` 会让它失效。正确做法是：resolver 对未登记主机**返回 DNS 错误**
   而不是兜底 IP，把"解析失败"也变成注入的一部分。

---

# 三、我认可的后续处置

1. F3、F7 重新打开，按 D1、D2 的闭合条件重做，不接受"换个常量/换个复制条件"就算完。
2. F2 按 D5 扩大到主监控循环，判活改用 `cgroup.procs` 为主、`is-active` 为辅，计时改 epoch。
3. skills ancestry 按 GPT 的方案改用非空且确定不存在的 marker，恢复祖先遍历覆盖。
4. 我上一批两份 agent_log 里的失败计数（40/41 → 42/39）与资源数字（16.4 GB/0 → 20.4 GB/142 MB）
   需要更正；`doc/WBS.md:65` 的 P0 表格与 `doc/development-environment.md:271-276` 的三处能力声明
   需要按事实改写。
5. plan/004 按 D3、D4、D6、D7 修订后才能作为实施入口；在此之前它只能当调查底稿。
   GPT 这个判断我完全同意。

以上全部为核验记录，**本轮没有改动任何代码或文档**。

---

# 附录：最后两处取向分歧的复核（2026-08-09 追加）

## A. Landlock —— GPT 对，我的技术前提是错的

我 D3 的保留建立在"回环与出网在 landlock 下走不同规则面"这个假设上。查源码后该假设不成立：

`linux-sandbox/src/landlock.rs` 装的是 **seccomp** 过滤器，不是地址级网络策略。
`NetworkSeccompMode::Restricted` 分支（:187-215）里：

```rust
fn deny_syscall(rules, nr) { rules.insert(nr, vec![]); }  // 空 rule vec = 无条件匹配
...
deny_syscall(&mut rules, libc::SYS_connect);   // 无条件拒绝，不看任何参数
deny_syscall(&mut rules, libc::SYS_bind);
deny_syscall(&mut rules, libc::SYS_listen);
...
// 唯一带条件的是 socket：arg0 == AF_UNIX 放行，其余一律拒绝
rules.insert(libc::SYS_socket, vec![unix_only_rule]);
```

`connect` 是**无条件拒绝、不检查目标地址**；`socket` 只按 address family 分支（AF_UNIX 放行）。
因此回环与公网走的是同一条判定，甚至在 `connect` 之前就已经被 `socket(AF_INET)` 挡掉。

**结论**：本地 listener 不会缩小产品契约，GPT 的默认门禁方案我完全接受，我 D3 的(b)项作废。
(a)项（改测试名/注释为"sandbox blocks TCP connect"）GPT 已经同意，保留。

## B. V8 —— GPT 对，我的"合同 A"确实是同义反复

`v8-poc/src/lib.rs:17-24`：

```rust
pub fn linked_v8_has_sandbox() -> bool {
    unsafe extern "C" { fn v8__V8__IsSandboxEnabled() -> bool; }
    unsafe { v8__V8__IsSandboxEnabled() }
}
```

它本身就是对链接库的直接 extern 探针。我提的"断言 `linked_v8_has_sandbox()` 与实际链接库能力一致"
等于拿探针和自己比，**没有信息量**。GPT 的批评成立。

接受 GPT 的收口：全量 workspace 执行**单向蕴含**
`cfg!(feature = "sandbox") ⟹ linked_v8_has_sandbox()`（feature unification 只增不减，该式在任何
构建配置下都成立，且能抓到"声明了 feature 却链接了无 sandbox 库"这个真实故障）；
严格的 `false` / `true` 双向断言交给官方 canary 的两个独占矩阵。

**我要补一句**：canary 里 `default artifact ⇒ false` 那一半不是可选装饰。单向蕴含在
`v8__V8__IsSandboxEnabled()` 退化为恒返回 `true`（符号被 stub、链接到错误库）时会静默通过，
只有 canary 的 `default=false` 严格断言能钉住另一个方向。两条必须成对存在，不能只落地第 1 条。

## C. 顺带发现：`sandbox_blocks_wget` 的根因，双方都还没证明

复核 Landlock 时看到 `assert_network_blocked`（`linux-sandbox/tests/suite/landlock.rs:481-487`）
的判据只有一条：

```rust
// A completely missing binary exits with 127. Anything else should also be non-zero...
// If—*and only if*—the command exits 0 we consider the sandbox breached.
if output.exit_code == 0 { panic!("Network sandbox FAILED ..."); }
```

这意味着**代理污染本身解释不了这项失败**：即使 `http_proxy` 让 wget 改连 `127.0.0.1:7897`，
`socket(AF_INET)` 照样被 seccomp 拒绝，退出码仍非零，测试仍会通过。

能让它失败的只有两种情形，含义完全不同：

1. `exit_code == 0` —— 沙箱真的被击穿（产品问题）；
2. `process_exec_tool_call` 返回的不是 `SandboxErr::Denied`（如 2s 超时、spawn 失败），
   命中 `details => panic!("expected sandbox denied error, got: ...")` 这条分支（fixture 问题）。

旁证：同一文件里的 `sandbox_blocks_curl` / `sandbox_blocks_ping` / `sandbox_blocks_nc`
**都不在 81 项严格失败清单里**，只有 wget 一项在。这指向 wget 特有行为（默认重试次数、
DNS/连接超时与 2s `NETWORK_TIMEOUT_MS` 的关系），而不是通用的代理或沙箱问题。

**因此**：我 plan/004 把这项归入"代理污染"缺证据，GPT 沿用该归因写下的"清理代理继承"前提同样缺证据。
GPT 的本地 listener 方案在设计上仍然更优（确定性、可加未沙箱对照、可断言具体拒绝原因），
但**不能用"修掉代理污染"来论证它**。落地前第一步必须是拿到该测试的原始 `dbg!` 输出，
先分清是上面两种情形中的哪一种——这恰好也是 F7 想解决的那类证据缺口。

---

# 附录二：`sandbox_blocks_wget` 原始日志复核（2026-08-09 追加）

GPT 找到了我以为已经丢失的上游原始日志。我独立打开核对，**其结论逐字成立**。

原文在 `.codex/build-study/0.147.0-upstream/test-attempt-08-full-complete.log`：

```
TRY 1 FAIL [  10.011s] codex-linux-sandbox::all suite::landlock::sandbox_blocks_wget
  panicked at linux-sandbox/tests/suite/landlock.rs:469:24:
  expected sandbox denied error, got: Sandbox(Timeout { output: ExecToolCallOutput {
    exit_code: 124, stdout: "", stderr: "", duration: 10.002965247s, timed_out: true } })

TRY 2 FAIL [  10.010s] ... duration: 10.002728253s, timed_out: true
```

- panic 位置是 `:469`，正是 `details => panic!("expected sandbox denied error")` 那条分支，
  **确认为我此前推断的第 ② 类**（fixture 拿到 Timeout 而非 `SandboxErr::Denied`），
  与 `exit_code == 0` 的沙箱击穿分支无关。
- `NETWORK_TIMEOUT_MS = 10_000`（`landlock.rs:39/41`），而同文件 `:436` 的注释仍写
  "a generous 2-second timeout"——**注释过时**，我上一轮据此做的重试/超时推算用错了数。GPT 纠正正确。
- RONDO 较早一轮该测试 `PASS [0.040s]`（`003-codex-0.147.0/.codex/p0-0.147.0-full-nextest.log:9037`），
  证实行为非稳定必现。
- 代理污染仍未被任何证据支持。

## 我要补的两点（避免下一轮据此做错推断）

1. **不要把 `stdout: ""` / `stderr: ""` 读成"wget 没来得及报错"。** 命令是
   `wget -qO- http://openai.com`，`-q` 就是静默模式，本来就不打印任何诊断。
   两个流为空由命令行参数完全解释，**不构成关于 wget 内部状态的任何证据**。
2. **"为什么撑满 10 秒"目前只有假设，没有证据。** 一个可测的假设是：seccomp 让
   `socket(AF_INET)` 返回 EPERM，wget 默认 `--tries=20` 配合默认 `--waitretry` 线性退避
   （1s、2s…上限 10s）足以吃满整个超时窗口。**验证方法是去掉 `-q`（或加 `-d`）跑一次一次性诊断**，
   先拿到真实输出再下结论，不要在方案里预设机制。

## 对最终建议的态度

GPT 调整后的论证我完全接受：默认门禁改本地受控 listener，理由是 **hermetic 且断言更强**，
而不是"已证明修复代理污染"。四条收紧条件（未沙箱轮先证明可达、沙箱轮限一次确定连接、
要求快速非零结束且 listener 未收到请求、timeout/缺 binary/任意非零一律不再算通过）我认为正是
本项目"skip 与未运行不能表述为通过"这条规则在该用例上的正确落法。

V8 的"全量单向蕴含 + canary 严格 default=false / sandbox=true 双矩阵必须同时落地"，与我附录一的
补充一致，无分歧。
