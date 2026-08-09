# 审查遗留问题修复（F2～F7）

日期：2026-08-09
工作树：`.claude/worktrees/005-test-hermetic`，分支 `fix/005-test-hermetic`
边界：未改产品审批/沙箱语义，未改宿主配置，未合并、未推送。

F2/F3/F7在本批后的能力结论已由 `agent_log/2026-08-09-141630-watchdog-baseline-and-plan-finalization.md`
取代；本文件只保留当时实施与验收事实。

处理对象是 `agent_log/2026-08-09-025644-claude-cross-review-of-baseline-p0-audit.md` 里记录的
F2～F7（F1 已在上一批修复）。

## 改动

### F2 终止逻辑：让行为对得上"有界"的说法

`terminate_scope` 单轮有界（10 轮 × 10 次 0.1s 轮询），但三处调用方各自写了
`while is-active; do terminate_scope || sleep 1; done` 的无界外层循环，杀不掉的 scope 会让包装器
静默空转。新增 `terminate_scope_until_gone`，六处调用点统一走它：仍然不放手（提前返回等于把没人
监督的负载交还出去），但每 30 秒打印一次仍留在 cgroup 里的进程数，`MemoryMax` 继续兜底。
`doc/development-environment.md` 的描述同步改为"单轮有界 + 外层持续重试直到确认 inactive"。

### F3 `guardian_source_baseline` 的取值来源

常量取自 `CARGO_PKG_VERSION`，语义却是"上游 tag"。当前两者相等，但 RONDO 一旦带本地版本后缀，
这个字段会在无人察觉时说谎，而 P1 要靠它分层。补了说明该不变量的注释，并加
`guardian_source_baseline_matches_the_upstream_tag_shape`：版本里出现 `-` 即失败，并提示改用显式基线。

### F4 为测试放宽的可见性

`GuardianEvidenceRound::new` 曾为一个测试改成无条件 `pub(crate)`。改回私有，另加
`#[cfg(test)] new_for_tests`，`client_tests.rs` 相应调整。

### F5 不改（结论修正）

`Arc::get_mut(&mut turn).expect(...)` 原本被记为"偏脆"。复查后确认它是
`core/src/guardian/tests.rs` 里既有的通用写法（另有约十处相同用法），只改其中一行会破坏一致性，
全改属于无关重构。保持现状，失败方向是 panic 而非静默误绿，可接受。

### F6 实时文档收敛

`doc/WBS.md` 与 `doc/development-environment.md` 去掉"2026-08-09 独立复验修复了…""因此不能继续
称为…"这类修正史表述，只留当前事实；修正过程留在 plan 与本目录的日志里。

### F7 全量结果的机器可读留存

nextest 的 JUnit 落在 `target/nextest/<profile>/junit.xml`，`cargo clean` 或换工作树就没了——上一轮
严格全量的原始结果正是这样丢失的。包装器收尾时把它复制到本轮看门狗目录
`.codex/build-watchdog/<stamp>/junit-<profile>.xml`（git-ignored、不随 target 消失）。

### 附带：把锁的 fd 从 8/9 挪到 200/199

修好 F1 之后才看见的：cargo 通过 `CARGO_MAKEFLAGS` 把 jobserver 读写端放在低位 fd（实测 8/10），
而 `rustc-throttle.sh` 原本用 `exec 8>` 占槽，正是"fd 8 不是管道"这条警告描述的情形。
两个脚本分别改用 200 与 199。

**未闭合**：改完后 `failed to connect to jobserver ... fd 8 ... is not a pipe` 仍会出现，说明还有第二个
来源（已排除本仓两个包装脚本，它们现在只用高位 fd）。该警告只影响 rustc 之间的并发协调，不影响
正确性，留作后续排查项。

## 验收

- `just test -p codex-core -E '<guardian evidence 相关>'`：**17 项运行，17 通过**，
  含新增的 baseline 不变量测试。
- `just fmt-check`：通过；`just clippy -p codex-core`：无本轮代码产生的警告。
- JUnit 留存实测生效：`.codex/build-watchdog/20260809-075117-1000-2550068/junit-local.xml`
  记录 `tests="17" failures="0"`。
- 全部经 `with-build-lock.sh`，一次一组，`stop_reason=none/cleanup_reason=none`。
