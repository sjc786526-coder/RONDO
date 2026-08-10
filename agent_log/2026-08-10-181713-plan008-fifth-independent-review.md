# Plan 008 第五次独立审查：v5 第一阶段整改

时间：2026-08-10（Asia/Shanghai）

审查对象：`fe517bcf9bace5325d205803ff00e0c036008e8d`

对比基线：`5f584273297cac3ec91799d8cf53904c748357f7`

整改记录：`agent_log/2026-08-10-180332-plan008-fourth-review-remediation.md`

## 1. 范围与结论

本轮只判断第四轮“第一阶段”静态整改是否闭合，重点复核：

- v4 是否以可复核 tracked 事实退出当前入口，v5 是否是唯一当前 identity；
- completed/failed no-API summary 与 ledger 的事务、side、终态和恢复语义；
- failed summary 是否诚实保留实际可得的 Docker/fake/artifact/cleanup 事实；
- 去 `chown` 后真实 fix-git adapter 是否具备可被 v5 no-API 门禁证明的生产可达性；
- 285/285、85 packages 与聚焦 79/79 是否可独立复现。

本轮没有运行 Docker、Cargo、真实 API 或模型，没有读取 `.env.local`，没有修改实现或权威文档；只复跑
pure/fake/loopback 轻量测试并读取保留现场。除本日志外未写入仓库。

**结论：不能宣告第一阶段已经“无隐患、无缺陷、无 bug”并完成。**

`fe517bc` 对上一轮三项问题的主体修复真实有效，不是表面补测：v4 retirement、v5 identity、错侧恢复、
terminal summary 原子写入与持续回读均成立，v5 也确实尚无 ledger，没有冒充 Docker 结果。但在下一次真实
Docker 前仍有两项高等级验收阻断和数项中等级证据/恢复缺口。现在消耗 v5 slot 可能得到 false-green，
或在失败后留下不真实的永久摘要，因此不应进入第二阶段。

当前交付状态也准确：worktree 在审查前 tracked clean；`main == origin/main ==
2cc9140022f69803afff7bc373e3beeee0579be9`，`fe517bc` 未合并、未推送。分支在合并前已命名 `zz-done/...`，
仍不符合项目约定顺序。

## 2. 已确认关闭的第四轮问题

### 2.1 v4 retirement 与 v5 identity 成立

受跟踪 `eval/locks/p1-terminal-bench-pair-v1.json` 当前为：

- `pair_id = p1-fix-git-pair-v5`；
- no-API batch 为 `p1-no-api-smoke-v5`；
- paid 继续 disabled；
- retired v4 精确绑定 terminal status、ledger SHA、harness commit、run、side 与审查日志。

独立重算当前 lock SHA-256 为：

`7e6b69c60987cca55565cfa1e2414d7b1840b098048875b496003cee97105252`

retirement 中的 v4 ledger SHA：

`23ceecfebfb058fe6dd814df09a217674f62374740d3e2282b90f4aff069edef`

与 common-root 保留现场逐字节一致；真实 harness commit 是
`07d0a487f8c498032a6da7ce4fd37a91c607bdac`。整改日志对上一轮人工转录笔误的订正正确，没有改写 v4
ledger。`pair.py:38-68,740-778,1493-1538` 又要求 tracked retirement 与内置闭集完全一致，当前源码入口
不能再创建 v4。

主 common-root 与整改 worktree 均不存在 `p1-fix-git-pair-v5-no-api.json` 或 v5 summary；没有用测试临时
ledger 冒充实跑。

“同一 identity 只运行一次”的机器范围应明确为本项目 Git common-root；不要求引入跨物理独立 clone 的中心
协调、签名或数据库。若文档声称全球 exactly-once，应收窄措辞，而不是扩大轻量个人项目的可信体系。

### 2.2 side-bound recovery 成立

`pair.py:343-372` 在读取 summary 或修改 ledger 前先核对 active run side 与 `requested_side`。错侧调用返回
非零并保持 ledger/summary 不变；正确侧才允许收敛。`docker_smoke.py:860-885` 对 recovered completed 返回 0、
recovered failed 返回非零，上一轮“Codex 命令可消费 RONDO summary”的问题已关闭。

### 2.3 terminal summary/ledger 主体事务成立

- ledger schema v4 为每个 no-API claim 固定 summary 相对路径；
- CLI 正常和普通 Exception 路径都先原子保存 canonical summary，再让 `finish()` 从固定路径回读；
- completed/failed 都必须有 digest，ledger 每次打开都重读 summary、重算 hash 并核对 terminal status；
- summary fsync 后、ledger finish 前死亡可由同侧恢复；summary 耐久前死亡保持 active 并 fail-closed，不补造
  “Docker 未启动”。

这些机制见 `pair.py:159-234,294-372,1018-1465,1541-1649` 与
`docker_smoke.py:934-995`。原子持久化骨架可靠，下述问题发生在被持久化事实的内容和生产验收覆盖，而不是
ledger 再次可被清零或 summary hash 可被伪传。

### 2.4 去敏边界的可靠部分

root `_checked_exec()` 只把 stderr 分类成闭集，并以 stage/command-id 报错；summary 不保存原始 argv、
stdout/stderr、exception cause、密钥或宿主绝对路径。mount/network 只保存去 source 路径后的 projection digest；
trial result/exception 只保存 SHA。未发现 structured summary 写入 API key 或 raw secret 的路径。

## 3. 下一次 v5 Docker 前的阻断

### R5-H01（高，false-green）：root-owned Git 仓库对 UID 1000 仍可能不可用，但 no-API 门禁不检查 Git

冻结 fix-git task 的 `environment/Dockerfile` 在默认 root 用户下运行 `setup.sh`；setup 使用 root 执行
`git clone`、commit 和 checkout，因此 `/app/personal-site` 是 root-owned。生产 materializer 又把 service/agent
固定为 `1000:1000`。

`adapters.py:316-357` 当前只由 root 对固定 workdir 执行 `chmod -R a+rwX`，然后以 UID 1000 检查目录和
`.git` 文件是否 writable。它没有改变 repository owner，也没有为固定路径设置并验证 scoped
`safe.directory`。Git 的 dubious-ownership 检查不因 mode 0777 而消失；因此普通 UID 1000 的
`git status/add/commit` 仍会拒绝这个 root-owned repository。

当前 v5 no-API fake 在 `docker_smoke.py:65-73,605-639` 只要求 code-mode 执行
`printf rondo_code_mode_smoke`。`DockerNoApiSmokeResult.passed` 在 `:107-120` 只要求 Harbor completed、两次
fake request 与 tool round-trip，不要求 reward/task pass，也不执行 Git probe。这样，adapter 即使完全不能操作
fix-git repository，v5 双侧仍可能写 completed，产生 B2 false-green；之后 B3 才暴露 Git 不可用。

这是本次去 `chown` 修复的直接生产缺口，不是要求 agent 在 no-API 阶段解决完整任务。高性价比修复是：

- 在 agent 的受限运行环境中只对精确 `/app/personal-site` 建立并验证 scoped `safe.directory`，不恢复 chown、
  capability 或全局 `safe.directory=*`；
- adapter preflight 以 UID 1000 执行至少一个只读 Git identity/status probe；
- v5 fake 的 code-mode round trip 也实际包含安全只读 Git probe，并验证其结构化成功，再输出固定 marker。

v5 尚未 claim，修复后仍可让首次 ledger claim 绑定新的 clean harness commit，无需退休未运行的 v5。

### R5-H02（高，失败安全证据）：cleanup 未验证可被写成 `verified_empty`

`docker_smoke.py:316-400` 的 `_docker_failure_from_samples()` 只看最后一个 sample 的 task container/network/volume
数量是否为零；只要三个计数为零就写 `cleanup.state=verified_empty`。它没有核对 sample phase，也没有保留
supervisor 的 cleanup failure reason。

生产 supervisor 的事实更严格：只有 cleanup counter 复采成功时才追加 `phase=cleanup_verified` 或
`cleanup_unverified`（`docker_supervisor.py:1465-1484`）；若 cleanup counter 自身失败，会返回
“automatic task-container cleanup was not verified”，且可能只保留更早的空 baseline sample
（`:1234-1260`）。当前 summary 会把这种“无法验证 cleanup”的异常错写成 `verified_empty/0/0/0`。

这不会把 failed pair 改成 completed，但会让永久失败证据错误宣称资源已清理；用户可能据此跳过必要的
人工检查。下一次 Docker 前必须让 typed failure context 携带 cleanup outcome/reason，或只有明确
`cleanup_verified`（以及 supervisor 正常返回后已验证的 teardown phase）且 exact counts 满足时才写
verified；其余一律 `unverified`。回归应覆盖 cleanup 命令/复采失败而 samples 只有旧空 baseline 的路径。

## 4. 中等级证据与恢复缺口

### R5-M01（中）：late failure 丢失实际 fake、agent、Harbor 与 artifact 事实并补造 0/null

`run_docker_no_api_smoke()` 在 Harbor 完成后还可能于 result parser、agent JSONL 或 post-supervision validation
抛错。此时 server 仍拥有已经收到的 requests/tool-round-trip，Harbor returncode、trial path/result/exception 也
可能已经存在。但 `docker_smoke.py:731-748` 的异常包装只转交 Docker samples。

外层 `_early_failure_summary()` 在 `:1044-1092` 随后无条件写：

- `fake_requests=0`、`fake_contract_hits=0`、`agent_json_events=0`；
- `code_mode_tool_round_trip=false`；
- `host_returncode=70`；
- trial result/exception SHA 均为 null。

两种轻量故障注入均已复现：

1. 已完成 2/2 loopback requests 和 tool round-trip，随后 agent JSONL 验证抛错；durable 投影仍为 0/0/false；
2. 第一个 accepted request 后 executor 抛带 samples 的 supervision error；实际为 1/1，投影仍为 0/0。

这与 `doc/eval-data-layout.md` 的“实际可得，未观察字段才 unavailable/null，不补造 0”冲突。应传递 typed、
闭集的 failure context，保存实际 request/hit/tool/event counts、Harbor rc、artifact digests；真正未观察到的字段
显式为 null/unavailable，而不是伪造 0。

### R5-M02（中）：summary 的有效 runtime 投影未证明 non-root 与精确资源合同

completed summary 已绑定 image、VHDX、container metrics、seccomp、cap_drop、NNP、private cgroup、limits 和
mount/network digest；运行时 supervisor 也会逐字段检查。但 durable runtime projection
`docker_smoke.py:285-313` / `pair.py:1217-1255` 没有保存/校验：

- container `user`（应为 `1000:1000`）；
- `network_mode` 与 `read_only_rootfs`；
- memory/swap/pids 是否精确等于 2 GiB / 3 GiB / 256（codec 只要求正数）。

non-root user 是本次 nested user namespace 与去 chown 合同的关键事实。若 summary 被用作可独立重算的 B2
机器证据，至少应补 user 与 exact limits；network mode 可投影为明确字段或受跟踪预期 digest，继续不要保存
mount source 宿主路径。

### R5-M03（中）：failed 恢复会改变原始退出分类

正常结果 `_smoke_exit_code()` 对 infra failure 返回 70，其他 agent/evidence/contract failure 返回 65。
durable summary 已保存 `outcome`，但 `NoApiSummaryEvidence` 只返回 digest + terminal status；恢复入口对所有
failed 无条件返回 70。

因此 non-infra failed summary 已 fsync、进程在 ledger finish/ack 前死亡时，首次应为 65，恢复却变为 70；
`_early_failure_summary` 自身还把 `host_returncode` 固定成 70。不会触发 Codex slot，但违反 Plan 008 的稳定
终态/退出码分类。summary evidence 应携带可信 outcome/exit class，恢复原分类，并分别回归 65 与 70。

### R5-M04（中）：安全 stage/command-id 未覆盖 agent-user 命令

结构化 `_checked_exec` 只包住 root install/workdir chmod。agent 用户执行的 workdir/Git probe、secret stat/auth、
runtime checks 与最终 Codex exec 仍直接调用 Harbor `exec_as_agent`。冻结 Harbor 0.20 的 installed base 对非零
退出会把完整 command 与截断 stdout/stderr 写入异常
（`eval/.venv/.../harbor/agents/installed/base.py:487-516,518-559`）。

safe summary 的 `_trial_failure_diagnostic()` 不接受这种消息，统一降为
`stage=result, command_id=no_api_contract, stderr=empty`。未证明这里会把 API key 明文写入 tracked summary，
但整改日志“adapter error 不带 raw argv/stdout/stderr、每个失败都有真实 stage/command-id”的表述过宽，
private trial 也会保留较多 raw command/output。应把关键 agent-user 步骤也包成闭集安全诊断；Codex 大输出失败
至少保留分类，不把 raw 内容搬入 durable summary。

## 5. 低风险与文档边界

- CLI 崩溃发生在 terminal ledger 已 parent-fsync、stdout/return 前时，重启只恢复 active，不能重放已 terminal
  receipt；不会二次 Docker，但 completed retry 会变成 65。可考虑 idempotent terminal receipt，列低可用性。
- pair gate 仍需显式 `--pair-validation`，根级没有唯一 canonical v5 recipe。standalone 会标
  `pair_validation=false`，不能伪造 ledger，列低操作风险。
- 整改日志写 `observed_complete`，实现枚举实际为 `observed`；应订正。
- `doc/development-environment.md:366-376` 仍把完整 no-API 状态写成早期 builtin seccomp 阻断，应标历史或同步
  当前 custom seccomp/v4 retired/v5 pending 状态。
- ignored 约 220 MiB，主要是允许的 `eval/.venv`、嵌套 uv cache 与 pycache，无 `target`。justfile 相对
  `UV_CACHE_DIR` 仍把 cache 放到 `eval/eval-data/uv-cache`，与顶层数据分区约定不一致。
- 父目录 symlink、VHDX 文件 identity 等此前低风险项未因本批改变；本轮第一阶段也未宣称解决。

## 6. 独立验证

本轮独立复跑：

- `just eval-test`：285/285，0 failure/error/skip，约 21 秒；
- `just eval-lock`：85 packages；
- 聚焦四模块静态/独立口径为 79/79：adapter 18、docker-smoke 12、pair 18、results 31；
- pair + docker-smoke 定向 30/30；
- `git diff --check 5f58427..fe517bc`：通过；
- worktree 审查前 tracked clean，v5 ledger 不存在。

285 项包含真实 fork/`os._exit`、loopback、临时 ledger/summary 与 Harbor 实装闭包，并非全部 mock；但 ownership、
Git safe-directory、Docker cleanup phase、有效 runtime 投影仍没有真实 Docker 或等价 shell 集成证据。测试绿灯
不能覆盖上述跨模块问题。

## 7. 验收与后续顺序

`fe517bc` 可保留为有效的部分整改提交，但**不能作为第一阶段最终验收点，也不应现在消耗 v5 Docker slot**。
建议继续在同一 worktree 做一个窄的“第一阶段补充整改”，不运行 Docker：

1. scoped Git safe-directory + UID 1000 只读 Git probe，并让 no-API code-mode marker 实际依赖该 probe 成功；
2. cleanup evidence 绑定 supervisor 明确 phase/outcome，未知或复采失败一律 unverified；
3. typed failure context 保留实际可得的 fake/tool/event/Harbor/artifact 事实，未知字段使用 null/unavailable；
4. durable runtime evidence 补 container user 和 exact limits，必要时补 network mode/read-only-rootfs；
5. 恢复按 durable outcome 保持 65/70 分类；关键 agent-user 步骤使用闭集安全 diagnostics；
6. 补生产 claim→异常→summary→recovery、cleanup probe failure、Git dubious ownership 的窄回归，并同步文档。

v5 尚未运行，因此上述代码修复后可以继续使用 v5；首次 claim 会绑定修复后的 clean harness commit。只有补充
整改再次独立审查通过，才进入原计划的严格 RONDO→Codex、最多两 run、首槽失败即停的 no-API Docker 阶段。

项目内补充整改不需要新增外部权限类别；本轮只读审查结束后需要用户明确指示执行方继续。此时仍不要授权
Cargo、真实 API 或模型，也不要合并/推送为“第一阶段完成”。
