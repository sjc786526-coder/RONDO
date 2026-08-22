# Plan 056 有界观测执行与设施修复

## 实质修改

- 新增 Plan 056 独立 identity、20-slot round-major 状态机、串行 Docker/Harbor coordinator、每 attempt 未定价兜底、
  task-budget 收口、schema-v2 body-free 结果与安全恢复边界；默认 `status` 不加载配置、密钥、Docker 或 API。
- 从 clean `2765ff8f82ce21262af46bdf93a62c75b381b631` 构建并冻结 RONDO Local legacy、code-mode companion 和
  runtime bundle；10/10 零 API 预检通过。
- 正式第 1 个 slot 发布；第 2 个已发送 slot 因投影完整性失败触发整包 invalid。没有重发、补位、补题、补轮或
  第二个付费 campaign。公共结果固定 1/20、25 attempts、`0.631065 USD`、reservation 0、无候选推断。
- 修复两个真实设施问题：持久 budget state 的只读 totals 汇总；Team Lens 在 runtime-end 晚于 tool-end 时的假阴性。
  后者使用第 2 题原始 trace 只读复放确认修复，但不改写 campaign 终态。

## 验证

- Plan 056 实现阶段相关集合最终 209/209 通过；身份/预算直接测试在关闭路径修复后为 17/17。
- Team Lens + harness observation + Plan 056 相关集合 69/69 通过；乱序实测 trace 的 terminal availability 为
  `available`。Ruff 对新增 Plan 056 文件通过；`py_compile` 与 `git diff --check` 通过。
- Cargo 构建、Docker 和正式 API 均经共享锁/资源看门狗串行执行。未运行全 workspace、CI、PR、Codex 对照、
  validation、holdout、E-A、完整数据集、本地模型、训练、云任务或上传。

## 资源与资产

- 保留 common-root ignored 资产：`eval-data/sources/plan056-rondo-local-2765ff8f/` detached source；约 13 GiB
  build target；三个 frozen bundle；Plan 056 campaign、budget 和各 build/preflight/paid/close metrics。
- 读取既有 v28 lock/Terminal-Bench source、项目局部 `eval/.venv` / `eval-data/uv-cache`、固定 bwrap 资产和 10 个
  pinned task image；未读取 Plan 054/055 私有资产或 `.env.local` 内容。
- Docker 总量与 VHDX 无增长；Plan 056 容器、网络、卷均已清空，镜像保留。Windows `C:` 终态余量
  186,090,741,760 bytes，高于硬门限。

## 后续授权

v1 关闭后，用户把 Plan 056 累计预算提高到 100 USD，并授权真实 rehearsal 与可修复设施问题后的全新 campaign
重启。v1 的费用、公共无效结果和私有工件继续保留；本日志不把后续 rehearsal 或最终 20/20 冒充为 v1 的续跑。

rehearsal-v2 从全新 identity 干净启动，第 1、2 题完整发布，第 2 题确认 Team Lens 修复已跨过 v1 的旧投影故障。
第 3 题的真实请求和 trial 完成后，收尾 Docker 事实命令在 30 秒采样窗口内连续失败；当前 campaign 因已发送 slot
无法形成完整投影而关闭为 invalid，后 7 题未发送。v2 为 34 attempts、`0.569748 USD`，累计 `1.200813 USD`、
reservation 0；容量门未触发，Docker/VHDX 增长为 0，最终无 Plan 056 容器、网络或卷。设施窄修将 Plan 056 的
完整采样窗口提高到 60 秒、只读命令最多重试 4 次，保留实时和 fail-closed 语义；其他调用方默认不变。下一次
rehearsal 使用 v3 全新 identity 从第一题重启。

rehearsal-v3 完成 10/10 零 API preflight，前 3 题完整发布并验证 Docker 事实采集窄修；第 4 题请求与 trial
完成后被投影器判为 lifecycle 不完整，campaign 按已发送 slot 规则关闭，后 6 题未发送。v3 为 52 attempts、
`0.842369 USD`，Plan 056 累计 `2.043182 USD`、reservation 0。Docker/VHDX 增长均为 0，最终没有 Plan 056
容器、网络、卷或 build cache；公共无效结果和全部原始工件保留。

只读检查 v3 第 4 题原 trace 后确认：一个 code-mode `exec_command` 在 sandbox open 阶段被拒绝，产品返回了完整
terminal structured result，但 native process 尚未创建，因而按既有事件语义不存在 runtime begin/end。投影器仅对
`exec_command + code_cell + completed terminal result + exact nonzero-exit structured shape` 接受这一 pre-runtime
形态；普通缺失、单侧 runtime、`write_stdin` 和畸形 result 仍 fail-closed。所有 exec 重复判断统一使用严格解析的
caller `requester + cmd + workdir`，pre-runtime 输出体积使用 native render source bytes，避免遗漏紧随其后的同命令
重试或截断前字节。新增正负回归通过，v3 原 trace 已离线复投影为合法 schema-v2 body-free 聚合。下一次 rehearsal
使用 v4 全新 identity 从第一题重启。

rehearsal-v4 完成 10/10 零 API preflight 和连续 10 题真实单轮；10 个 slot 均有完整 Terminal-Bench、API、原生
trace 投影和 Docker receipt，6 pass/4 fail。v4 为 111 attempts、`1.970204 USD`，Plan 056 累计 222 attempts、
`4.013386 USD`、reservation 0。Docker/VHDX 增长均为 0，Windows `C:` 从 193,259,507,712 降至
192,947,449,856 bytes，最终没有 Plan 056 容器、网络、卷或 build cache。两次并行重任务短时持锁均通过等待解决。

首次 v4 finalize 的公共聚合已经是有效 `rehearsal_complete`，但 finalized state allowlist 漏了该 rehearsal outcome，
因此在写最终 state 前 fail-closed。补齐 mode-aware allowlist 和回归后，同一 v4 离线幂等 finalize 成功，没有新 API
请求。该完整 rehearsal 不进入正式分母，也不执行候选判断；下一阶段从正式源码和 binary 复冻开始。

formal-v5 使用提交 `c2be21d01ae34c971b9f75334b265191bce0acbd` 的全新静态构建，10/10 零 API preflight
通过。正式运行前 3 个 slot 完整发布；第 4 个 slot 已开始第 8 次上游尝试，但 transport open 未取得 HTTP 响应，
旧 metadata 没有可区分这种 pre-header failure 的终态枚举，projector 按严格 schema 拒绝。campaign 如实关闭为
invalid，未重发该 slot，后 16 个 slot 未发送；v5 为 42 attempts、`1.637680 USD`，累计 264 attempts/
`5.651066 USD`、reservation 0。公共 body-free 无效结果、私有原始工件和资源记录均保留，Docker/VHDX 增长为 0。

根因修复只扩展观测生命周期：transport open 失败记录精确 `stream_end_kind=open_error`，并要求 status 0、usage
无效且无 SSE terminal 字段；实际收到非 SSE HTTP 响应则记录 `non_sse`。旧 v5 的缺失枚举继续 fail-closed，既不
修改原始 metadata，也不复投影或恢复该 campaign。完整预算代理 62 项、观测投影 33 项、Plan 056 状态机 21 项及
根因定向正负回归通过；后续以新的 formal-v6 identity 从第一题干净启动。

formal-v6 使用修复提交 `4965d7483d9e2812ec8e39debdb5988107e8101a` 重建并复验 Local
legacy/companion/runtime bundle；binary、code-mode host、bwrap SHA-256 分别为 `cc523bd8...a0d5`、
`ddda3ddb...1e0`、`77360cb7...2c4c`，全部构建/发布/复验均经共享锁和资源看门狗且 `stop=none`。新 campaign
冻结 20 个 slot，lock SHA-256 为 `263cc3fa...9e7f`，初始化未产生 API 请求。

用户追加授权精确清理仅由 Plan 056 创建且不再被 formal-v6/复验/交付引用的可再生成资源。确认构建已结束、
manifest 归属和引用后，通过 `binary_freeze cleanup` 的 exact-commit 入口删除旧 `2765ff8f` 与 `c2be21d0`
Cargo target，分别释放 13,552,737,989 与 13,552,728,113 bytes，合计 27,105,466,102 bytes（25.244 GiB）。
不可恢复内容仅为可重建的编译 object/incremental/cache；对应 source、frozen bundle/manifest、campaign、预算账本、
真实费用、公共结果和 metrics 均保留，当前 formal-v6 target 未清理。
