# Claude 审查、修复与剩余测试方案独立验收

日期：2026-08-09

工作树：`.claude/worktrees/0809-claude-fix-acceptance`，基线 `b9f724c`。本轮只写执行计划与验收日志，
未修改 Claude 的交付代码，未修改网络、`/tmp` 或宿主配置，未合并、提交或推送。

## 结论

1. Claude 对上一轮六项任务的交叉审查主体成立，可以接受；F1 的根因和修法正确。
2. 第一批 hermeticity 修复大体正确，三个包已由本轮独立受监督复跑确认全绿；但有一项测试覆盖弱化，
   失败计数与资源数字也写错，不能原样接受整份日志。
3. F1、F4、F5、F6 可接受；F2 只部分完成；F3、F7 不能判定已关闭。
4. `plan/004` 的环境根因和安全红线大体正确，但当前不是可直接执行的方案：严格失败实际为 39 项，
   多个落点与 live source 不符，V8、Landlock、时序和部分单点方案仍需重写。

## 1. Claude 交叉审查

- tag/commit、更正 7 处 SHA、上游快照未污染、第三个 `build_responses_request` 调用属于 Compaction、
  测试未删除/忽略且无 Cargo 依赖变化等结论均可由 live tree/diff 支持。
- F1 成立：旧 `exec 8>slot 2>/dev/null` 会永久重定向当前 shell 的 stderr；花括号限制作用域后，
  rustc/clippy 诊断重新可见，fd 200/199 也没有发现新的锁语义问题。
- 对旧 lint 证据应稍作收窄：stderr 丢失使“无 warning”和 `cargo clippy --fix` 实际处理诊断的证据失效，
  但不会吞掉子进程非零退出码；不能笼统说所有旧 clippy 返回状态都毫无意义。

## 2. F2～F7 后续修复

### 接受

- F4：生产 `new` 恢复私有，只暴露 `#[cfg(test)] new_for_tests`。
- F5：`Arc::get_mut(...).expect(...)` 是本测试文件既有惯例，失败方向为显式 panic，不改合理。
- F6：去掉实时文档里的修正史这一编辑目标已完成。

### 部分接受或不接受

- F2：六处调用已统一到 `terminate_scope_until_gone`，不会主动把已知仍活跃的 scope 放走；但计数变量
  每个最长约 10 秒的 kill round 只加 1，再额外 sleep 1 秒，所以“每 30 秒”最坏约 330 秒才输出，
  且打印的 `${waited}s` 不是实际秒数。`systemctl is-active` 的查询错误也和 inactive 同为非零，仍可能
  被当作已停止。应以 epoch 计时，并区分 inactive 与 unknown，必要时交叉检查 `cgroup.procs`。
- F3：生产字段把产品 `CARGO_PKG_VERSION` 当成上游源码身份，语义来源不正确；新增的后缀测试又只是
  对拼接常量的冗余检查。既有 evidence bundle 集成测试已经硬钉 `rust-v0.147.0`，因此普通版本变化会
  被测试发现，不能声称 `0.148.0` 仍会全绿。仍应改用显式、可核对的 tag + peeled commit 机器事实源，
  消除产品版本与上游身份耦合及重复事实。
- F7：复制能力存在，但没有绑定“本轮”。`075417.../junit-local.xml` 的内部时间为 07:53:34，
  早于该轮 07:54:17，且与 `075117...` 报告内容相同，已经直接证明旧报告会被复制进新轮次。
  非 nextest Cargo 命令、nextest 写报告前失败或其他 profile 的历史报告都会污染归属；复制失败也静默。
  应只归档本轮新写报告，并对预期报告缺失/复制失败明确记录。

因此 `doc/development-environment.md` 中“每 30 秒”“确认 inactive”“事后以该轮 JUnit 为准”的当前
能力声明不成立；WBS 的 P0 表格仍写“本工作树复验通过，待审查/合并”，在 `58cc429` 已合并后也已过时。

## 3. 第一批 hermeticity 修复

### 已确认成立

- MCP 初始化期望从 `CARGO_PKG_VERSION` 推导，保留了产品版本输出的断言。
- TUI 版本规范化保留字段与当前布局，未发现删断言/批量接受版本快照凑绿。
- synthetic cwd 的 ChatWidget fixture 预置无项目根缓存，符合这组展示测试的既有前置条件。
- WSL 线程局部注入覆盖 WSL/非 WSL 两种输出，没有修改全局环境变量。
- skills home override 在当前两个测试中均于首次加载前设置，真实 home 泄漏已隔离。

### 问题

- 中：`repo_ancestry_without_project_marker_does_not_walk_parents` 传入 `project_root_markers=[]` 后，
  `find_project_root` 直接返回 cwd，不再覆盖原来的“非空 marker 搜遍祖先、全部未命中后回退 cwd”。
  应改用确定不存在的非空测试 marker。
- 中：严格轮 81 项中本批实际覆盖 42 项，不是 40 项：MCP 4、TUI 35（版本 23、ChatWidget `/tmp`
  10、WSL 2）、skills 3（ancestry 1、home 2）。当前严格失败理论集合为 39。
- 低：版本 sanitizer 对整行裸替换版本子串；home override setter 不清缓存。当前用例未受影响，后续可
  通过限定匹配位置和构造期注入收紧。
- 日志资源数字不实：第一批原始 summaries 的最高 memory peak 为 `20,403,429,376` B，最高 swap
  为 `141,979,648` B，不是 16.4 GB / 0；项目峰值约 70.3 GB、stop/cleanup 均未触发则成立。

### 本轮独立验证

在 Claude 原干净工作树、同一 `b9f724c` 源码快照上，仅运行一组重型测试：

```text
just test -p codex-tui -p codex-skills-extension -p codex-mcp-server
Nextest run id: 2a9330fa-54c5-45c3-b5de-7c96ec0c1566
3,547 run / 3,547 passed / 4 skipped
run_rc=0, stop_reason=none, cleanup_reason=none
memory_peak_sampled_bytes=19,563,085,824; swap_peak_sampled_bytes=0
```

本轮 JUnit 的 3,547/0 与内部 timestamp 对应本轮，测试结束后无 cargo/rustc/nextest 残留，原工作树
tracked 状态仍干净。构建中继续出现已知 jobserver fd 8 警告，本轮不归因、不修复。

## 4. `plan/004` 验收

### 可接受的调查结论

- Clash TUN fake-IP 落入 `198.18/15`，产品按非公网 fail-closed 是正确安全行为。
- `127.*` 等 NO_PROXY glob 不是可靠的 IP/CIDR 匹配，测试必须显式隔离 ambient proxy。
- `/tmp` marker、WSL PATH、V8 feature unification、时序/真实 GitHub/浏览器副作用的主归因方向有证据。
- 不删 `/tmp`、不放行 fake-IP、不关 Clash 验证、不 ignore/弱化断言等红线正确。

### 必须修订后才能实施

1. **集合**：当前是 39 个严格失败；external migration 是历史偶发且最新严格轮通过，OAuth 一直通过但
   有浏览器副作用。可称“39 个失败 + 2 个附加 hermeticity 工作项”，不能称剩余 41 项失败。
2. **A 族**：共用 helper 注入静态 resolver 会破坏既有 DNS-failure 回归，必须给错误/超时/私网路径
   分别显式 resolver；建议中的 `198.51.100/24`、`203.0.113/24` 又会被产品明确判为非公网；
   `NetworkProxyState` 还有手写 Clone/Debug，不能说加字段零影响。优先使用 `#[cfg(test)]` seam。
3. **B 族**：core #6 实际是 managed proxy 对 `example.com` 的 DNS fake-IP，#7 是真实 login shell
   环境，均不经过 `session/tests.rs` 的 `HttpClientFactory`；#2/#4/#5 使用 route-aware pool/factory，
   一个返回裸 reqwest client 的公共 test helper也喂不进去。应分别用 IP/显式 resolver、受控 shell env、
   factory/pool 级直连 seam；doctor 更适合注入 probe。
4. **Landlock**：清代理后继续请求公网、对照失败便 skip 仍不 hermetic。应使用本地受控 listener，先证明
   未沙箱 wget 可达，再证明沙箱路径被阻断且 listener 未收到请求。
5. **C-4/C-5**：写 `.git` 并改断言会改变测试语义。应给内部函数加 FS seam，生产仍传 `LOCAL_FS`，
   测试传 `RootedFs` 并保留原断言。
6. **E 族**：根因正确，但当前三个选项不是闭合修法；把断言只留在 standalone 或移出 workspace 本质
   是从全量门禁删除。应先定义 V8 POC 的矩阵合同，再保证 full workspace 和独立模式均有实际断言。
7. **F/G**：200 次需要精确命令、每轮证据和与 full-workspace 并发相近的负载；G-1 需规定事件序列/
   child/server 状态证据；G-2 的 local cloner seam 在 external migration 层尚不存在；G-3 应列为
   全量运行前置副作用治理，不计失败数。

综上，`plan/004` 适合作为调查底稿，不适合作为当前唯一实施入口。建议先修订计划，再按独立批次落地，
每批验证串行且继续走看门狗；本轮不重复完整 workspace 全量。
