# Plan 049 阶段 B activation pilot 停止

日期：2026-08-20
执行提交：`2b30b8e5e2fdc819c5d49fc05c6adfaae48aac02`
结论：**阶段 B `blocked`；当前正式 identity 不得重试或进入 formal。**

## 启动门

- 用户明确授权阶段 B、真实 API、所需 Docker、固定 activation pilot，以及本任务累计 100 USD 硬上限；本轮把用户的
  “可用余额不少于 100 USD”确认投影为入口要求的 `100.00`。现有合同是操作者确认门，不查询 provider 账户余额。
- `phase-a-acceptance-v4` 与 `phase-a-loopback-v5` readiness 通过：26 个 rehearsal run 完整，工具投影、Team Lens、
  body-free 聚合和密钥安全检查五项布尔值均通过。未输出变量名或内容。
- 启动前工作树 clean，HEAD 与独立验收提交一致；provider/model/effort/价格投影和空正式前缀均与锁一致。
- Docker 前基线：26 images / 11.5 GB、0 containers、0 volumes、0 build cache；Windows C: 可用
  `183578390528` bytes，高于 80 GiB 门。

## 实际运行与停止

- 通过 `just eval-plan049-phase-b-paid ... pilot phase-a-acceptance-v4 phase-a-loopback-v5` 启动唯一正式进程；共享
  build-lock、cgroup/watchdog、Docker counter 与 100 USD 持久账本均生效。
- 只执行 `pilot-p01-codex` a01（`terminal-bench/filter-js-from-html`）。Terminal-Bench 形成非 infra
  `completed/reward=0.0`；15/15 请求均为 `usage_priced`，无未结算 reservation、未知 usage 或 budget stop，结算
  `0.262759 USD`，硬上限剩余 `99.737241 USD`。
- 运行时 campaign 未能定位唯一 trace bundle，因而没有形成正式 Team Lens。campaign 持久发布
  `principled_stopped/non_infra_terminal_missing_trace` 后退出 78；没有创建 a02，没有执行其余五个 pilot 槽，
  没有启动正式十个配对。
- 纯只读重开验证 receipt 与唯一 record 有效，且 `require_safe_formal_prefix` 在任何 Docker/密钥/API 之前以
  `Plan 049 formal campaign has a latched stop` 拒绝当前 identity。

## Trace 根因

trace 实际已生成，先前的“空目录”判断不成立。只读机械投影确认，同一 `rollout-trace/` 下有两束结构完整、均可由
Team Lens 归约的 v1 bundle：

- 主 Root bundle 的 session source 为 `Exec`，包含 15 次 inference 与 14 次工具调用，共 119 个文件、
  `1540696` bytes。
- 第二束的 session source 精确为 `SubAgent/Other("guardian")`，包含 1 次 inference，共 9 个文件、`50759`
  bytes。
- 两束都在实际 agent 运行期间写完，早于正式 `run.json`；未人工展开或复制任何 prompt、response、reasoning、工具正文、
  命令输出或 raw trace 内容。

冻结 Codex 的普通 `ThreadSpawn` 会继承 Root trace writer，因此产品成员仍归入主 bundle；Guardian 则以
`SubAgentSource::Other("guardian")` 启动，并显式禁用父 trace，于同一 `CODEX_ROLLOUT_TRACE_ROOT` 新建独立 root
bundle。Plan 049 复用的 M-5 `find_trace_bundle()` 假设目录中恰好一束，看到两束就抛出
`rollout trace root holds more than one bundle`；formal 层将这一 `TraceError` 统一包装为
`non_infra_terminal_missing_trace`。因此根因是 **多智能体运行实际产生多 bundle，而消费者仍采用单 bundle 假设**，不是
环境变量丢失、目录权限、Docker bind mount、Harbor 下载或退出清理失败：adapter 已把 trace root 注入实际 agent exec，
`/logs/agent` 是 trial bind mount，产物均为 uid 1000 写入，adapter 清理仅删除 `/tmp` 下的 home/secrets，Harbor stop 也只
修正日志所有权后关闭容器。

该槽的任务结果与费用已经固定，不能改标 infra 或购买替代 attempt。虽然唯一 Root bundle 可离线归约，但当前正式 identity
已绑定验收提交并持久锁存原则性停止；本轮诊断没有改写 receipt、账本、archive、run marker 或 raw trace。若未来继续，
须先明确授权能同时保持原 a01 样本、累计费用和 harness identity 一致性的窄恢复方案，不得删除本次正式 namespace。

建议的最小修复不是放宽共享 M-5 locator：M-5 的单 rollout 门仍有自己的单 bundle 合同。Plan 049 应在薄编排层机械选择
唯一 `SessionSource::Exec` bundle，同时完整校验并只容许精确的 Guardian bundle 作为控制面旁证；第二个 Exec 或未知 source
继续 fail-closed。由于任何 tracked 修复都会改变 receipt 已绑定的 harness commit，当前 a01 的离线重建与后续 resume 还必须
配套一个显式、一次性的状态迁移门，证明只重建 Team Lens/归档、保留原 run identity、`0.262759 USD` 费用与任务失败结果，
绝不再次请求 provider。该迁移不属于本轮只读诊断，也不能靠手工删除或改写 ignored 文件替代。

## 资源与边界

- Docker 后状态与基线完全一致：26 images / 11.5 GB、0 containers、0 volumes、0 build cache；未清理任何既有对象。
- Windows C: 结束时可用 `183580635136` bytes；watchdog `stop_reason=none`、swap peak 0、内存采样峰值
  `1995841536` bytes。
- 新建 ignored namespace：`eval-data/plan-049/paid/plan-049-paid-v1/`；新增 watchdog 运行目录：
  `eval-data/plan-049/watchdog/20260820-212809-1000-50328/`。原始运行资产未进入 Git。
- 未运行 Cargo、本地模型、完整数据集、全 workspace、CI 或 PR；未合并、推送、关闭或重命名工作树。
