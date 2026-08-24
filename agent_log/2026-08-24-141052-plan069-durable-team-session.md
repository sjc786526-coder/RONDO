# Plan 069 durable Team Session implementation

## 实质改动

- 为 canonical Team State 增加版本化 checksummed snapshot、完整状态恢复校验、committed read、commit generation、unknown/unavailable reconcile 和 read-only view。
- 把 thread-store Root active writer 扩展为 Root write/close capability；weak handle 不延长 owner，permit 连续覆盖 Team commit 与成功返回，关闭失败可 abort 后重试。
- 接通默认关闭的 durable 配置、Session fresh/cold resume、stable shared Team handle、legacy/marker fail-closed、显式初始化清理、child admission gate 和最小 Root close barrier。
- 将 route delivery、wake 与 retained evidence 的 durable failure 保留到调用边界，不制造仅内存成功或伪造 delivery state。
- 增加领域故障注入、真实子进程 owner 竞争/恢复、真实 Session/tool cold resume、durable-off marker 拒绝和 failed-close retry 回归；更新 config schema 与 Cargo lock。

## 疑难与收口

- Session 集成测试最初因执行环境未给 loopback 配置 `NO_PROXY` 而经代理返回 502；只在测试命令子进程为 `127.0.0.1,localhost` 设置 no-proxy 后通过，未修改宿主配置。
- 首次 `just bazel-lock-update` 因环境没有 `bazel` fail-closed；随后把 npm/Bazelisk 下载缓存放在 `/tmp`，由 Bazelisk 获取 Bazel 9.0.0 并通过共享 build lock/watchdog 执行，成功且 `MODULE.bazel.lock` 无差异。Bazel 本身仍复用了既有默认用户缓存路径；watchdog 已终止残留 Bazel server，未清理或改写该来源不明缓存。
- `team_tools` 全切片中的 068 Publication Critic process fixture 需要本任务未获授权的 service binary；未使用其资产，改跑排除该 process fixture 的 20 项切片并全部通过。
- 干净上下文独立终审发现一个中等级 correctness 问题：transient/unknown durable commit 后，owner 的产品调用路径不会自动 reconcile。
  已在 Team capability resolve 前串行 reconcile，并补 unavailable 与 after-write unknown 的重试/去重回归；同一审查者复验接受，无剩余高/中 finding。
- 标准 `just test` 在测试前因上游 rusty-v8 默认归档 URL 返回 404 失败。改用仓库 checksum-verified Codex V8 等价配方；前三次冷构建被
  memory PSI 门禁停止，一次被 255GB 项目主动停线停止。只清理本任务可重建的 incremental（22.34GB）和随后本任务整个 target（52.4GiB），
  未清理其他 worktree/cache；以 2 jobs、关闭 incremental/debug info 完成完整执行。

## 当前验收

- Team State lib：146 passed，1 skipped。
- Thread Store lib：187 passed；真实 Root owner 子进程竞争/failed-close handoff 通过。
- Core durable 聚焦：真实子进程恢复继续 mutation、配置/close/admission 7 项通过；新增真实 Session/tool cold resume + marker 拒绝 1 项通过；failed-close/no-completion/retry 1 项通过。
- Team tools（排除 068 process fixture）：20 passed。
- config schema 已生成；Bazel lock update 成功且无 tracked diff。
- checksum-verified V8 完整 workspace 轮：14,373 tests run，14,363 passed（4 slow）、10 failed、24 skipped。7 项失败缺少未授权的
  `RONDO_PUBLICATION_CRITIC_SERVICE_BIN`，1 项是 068 Publication Critic 字段顺序断言，2 项是未修改 realtime localhost 连接失败路径
  等待事件超时；后二项在低负载及取消代理的独立窄重跑中仍失败。069 `durable_team_cold_resume_preserves_identity_and_continues_mutation`
  在完整轮通过。
- `just fix -p codex-team-state`、`-p codex-thread-store`、`-p codex-core` 与 `just fmt` 成功；fix 报告的本任务告警已窄修，按仓库规则未在 fix/fmt 后重跑测试。
- 当前状态为 `IMPLEMENTATION_COMPLETE / PREACCEPTANCE_COMPLETE / FINAL_PASS_BLOCKED_BY_#37198`；未运行阶段 E 的 main 吸收、persisted cwd/live override
  聚焦回归和最终全新 Session/store 正式轮，也未运行 Docker、真实 API/模型、训练、测评、CI/PR、合并或推送。
