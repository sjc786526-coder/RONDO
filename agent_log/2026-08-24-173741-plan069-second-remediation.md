# Plan 069 第二轮 correctness 修复

## 结论

- 外部复验报告的三项中等级 finding 均确认存在，并在 Plan 069 原边界内修复：canonical Root `SessionMeta` 现在持有版本化 durable Team intent，Team backend 只持有 committed snapshot；`.team-lineage` 旁路及其二次发布已删除；fresh durable Root 在打开 thread persistence 前拒绝无法证明 participant identity 的 source。
- durable-on resume 交叉验证 Session/root marker 与 snapshot；durable-off resume 先检查 canonical marker，因此即使整个 `team-sessions/v1` 丢失也不会恢复为空 Team。legacy/non-durable 的无 marker resume 保持原行为。
- fresh 成功顺序保持为：创建带 marker 的 buffered rollout、完成 Session 接缝、物化 canonical rollout、再以同一 Root authority 提交 generation 1。初始 snapshot CAS 的 Unknown/Unavailable reconcile 与 owner 保留逻辑未削弱。
- 全新上下文独立复验进一步发现 canonical marker 自身的 persist-after-success 错误仍会释放 owner；首修后同一审查者又指出 read-back 自身不可用的组合窗口。两项均确认并修复：persist 返回错误时先在同一 Root owner 内通过 canonical ThreadStore history read-back 验证完整 marker；读回仍不可用则返回 fully constructed degraded Session 并保留 Root owner，projection、Team tool、wait 与 close 在 marker 验证和 generation-1 注册完成前全部 fail-closed，并由下一次这些产品入口在同一 owner 内重试。缺失、损坏或 identity/version 不符仍拒绝激活。

## 验证

- `codex-protocol` marker serde：1/1 通过（watchdog `20260824-171712-1000-4046599`）。
- `codex-thread-store` Root authority/failed close：1/1 通过（`20260824-172444-1000-4073777`）。
- `codex-core` marker/snapshot 缺失与有界读取：2/2 通过（`20260824-172824-1000-4088997`）。
- `codex-core --test all` Unknown preflight、cold resume/整个 Team backend 丢失、立即 crash resume：3/3 通过（`20260824-172906-1000-4091503`）。
- `codex-core --test all` persist-after-success read-back 回归单独 1/1 通过（`20260824-175334-1000-4153075`）；随后与 Unknown preflight、cold resume/整个 Team backend 丢失、立即 crash resume 合并复跑 4/4 通过（`20260824-175420-1000-4155933`）。
- `codex-core --test all` persist-after-success + 首次 read-back unavailable 的 owner 保留/产品入口重试回归单独 1/1 通过（`20260824-180336-1000-4172767`）；随后两种 persist 组合故障与三条原产品路径合并复跑 5/5 通过（`20260824-180442-1000-4177068`）。
- `codex-rollout` SessionMeta 提取：1/1 通过（`20260824-173219-1000-4101852`）。
- `codex-state` 直接受影响夹具：3/3 通过（`20260824-173251-1000-4103351`）。
- `codex-app-server --test all` 直接受影响 resume 夹具：1/1 通过（`20260824-173341-1000-4108501`）。
- 最终 `just fmt` 与 `git diff --check` 通过。首次格式化曾触发 Rust 1.95 rustfmt 内部崩溃；随后 `cargo fmt --check --verbose` 和同一 `just fmt` 均正常通过，未发现格式差异。

首次 core 构建在代码测试前由仓库 watchdog 于项目存储 255 GB 主动停止。只删除经核实属于 069 当前 worktree、无活动 Cargo/Docker/模型进程占用的 `target/debug/incremental`，未触碰其他缓存；之后所有重型命令均用 `CARGO_INCREMENTAL=0` 和既有 just/build lock/watchdog。末轮项目存储约 253.1 GB，按外部复验指定的聚焦边界未重跑 clippy 或完整 workspace；前述通过项均为本轮代码的真实运行结果。

## 边界

- 未运行 Docker、真实模型/API、CI 或性能测评；未修改四份共享 WBS、Plan 068/070 资产或控制面协议。
- 为测试支持增加 `core_test_support -> codex-thread-store` 既有 workspace 内部依赖，并由 Cargo 正常更新对应 lock 单项；核对 068 clean、070 未占用 manifest/lock。
- 同一全新上下文独立审查者先后提出 canonical persist-after-success 和 read-back-unavailable 两项真实中等级 finding；执行者逐项修复并交还同一审查者复验，最终结论 `ACCEPT`，无剩余高/中 correctness finding。
- 未进入阶段 E，未处理 `#37198`，未 merge/rebase/push。当前 `IMPLEMENTATION_COMPLETE / PREACCEPTANCE_COMPLETE / FINAL_PASS_BLOCKED_BY_#37198`；最终 M4-S1 PASS 仍独立阻塞于 `#37198` 进入 main 及用户批准同步。
