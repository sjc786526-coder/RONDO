# E-B8 第五次验收审查（`d0da450`）

## 结论

**通过 E-B8 设施实现验收；未解锁正式 v7/付费 campaign。**

`d0da450761169c4bcf5f48ebd5526ba41aec2fc0` 已实质闭合第四次审查的 1 个 blocker、1 个 HIGH
和 1 个 MEDIUM；额外处理的 TREESAME merge 历史隐藏问题也属实且修复正确。本轮继续核对正式生产调用链、
冻结 Responses Lite 源码形状、Git 合并生命周期及 receipt 加载边界，没有发现新的 blocker、HIGH 或 MEDIUM。

这里的“通过”只指原 E-B8 合同要求的公平比较设施已经机械闭合。仓库仍没有正式 v7 identity，也没有执行
identity → producer CLI → worker CLI、Oracle、wire canary 或真实 API 生命周期；这些仍须等待 pilot 后重复合同、
独立 cap 与用户授权，不能把本结论表述为正式 campaign 或产品能力比较已解锁。

审查覆盖 `191cb50..d0da450`，并回看当前 projection、receipt producer/loader、paid proxy 与 harness Git
投影。除本日志外没有修改实现、测试、WBS、plan 或冻结历史；没有运行 Docker、真实 API、真实模型或付费入口。

## 三项修复验收

### 1. Responses Lite `AdditionalTools` 投影：通过

- `TASK_INDEPENDENT_PROJECTION_VERSION` 已升至 2。
- 真实 Lite `input[0]` 的 `additional_tools` 必须是 developer role 且 `tools` 为数组；重复、移位、畸形，或与
  顶层 `tools`/`instructions` 混用均 fail-closed。
- Lite tools 进入独立 `tool_specs` 分区，同时 `additional_tools` 与后续 developer/system message 进入
  `stable_input_prefix`；扫描仍在首个非稳定角色处停止，因此 user task body 不进入稳定合同。
- 回归夹具已改为冻结源码的实际 wire shape，不再把 AdditionalTools 文本伪装为普通 developer message。

本轮重跑第四次审查的原始纯复现：8-model 与 1-model Lite 请求现在得到
`task_independent_tool_specs_differs` 和 `task_independent_stable_input_prefix_differs`；保持 catalog 相同、只改变
user task body 时仍得到空 reasons。修复同时闭合“抓到真实稳定差异”和“不误抓任务正文”两侧要求。

### 2. identity 完整 Git 历史：通过

- 对相对冻结 harness commit 净状态为 `A` 的新 identity lock，不再只信任最终 diff；实现使用
  `git log --full-history --no-renames` 检查完整路径历史，并逐 commit 与所有 parents 比较。
- 正常直接 addition、worktree 分支经 `--no-ff` 合并及后续无关提交仍可用；addition 后修改会拒绝，即使后来恢复
  原 blob 也不会重新放行。
- merge 结果与任一 parent 相同不重复计为变更；但侧分支曾改写 identity、merge 最终恢复主线 blob 的
  TREESAME 情形仍会从完整历史中发现并拒绝。
- active pointer 保留可更新语义；没有扩展成签名或可信审计机制。

该逻辑与项目正常“worktree commit → no-ff 合并本地 main”流程兼容，也闭合了第四次审查复现中“本代新增 lock
后再次提交改写仍被视为 A”的缺口。本轮没有发现新的可绕过净 diff 或 merge 简化的路径。

### 3. 六段完整请求 digest provenance：通过

- producer 现在保留双侧各自精确的 main → Guardian → main 有序 trace，不再压缩成 role map；post-Guardian main
  继续参与同侧稳定合同校验。
- `PREFLIGHT_RECEIPT_SCHEMA_VERSION` 已升至 2；receipt 固定要求 6 条
  `side/role/sequence/full_request_sha256`，顺序为 RONDO 三段后 Codex 三段。
- 缺行、乱序、布尔/非法 sequence、非法 SHA 或角色轨迹不完整均拒绝；只保存 digest，不保存请求正文，也不把
  跨侧完整 digest 相等作为断言。
- receipt 仍只冻结 `main`、`guardian` 两类稳定合同，加载后 seed 付费门禁的语义未扩大。

这与 WBS 的“完整请求 digest 各侧分别保存，只作 provenance/drift”一致，且保持了轻量、固定上限的工件结构。

## 遗漏问题复查

本轮特别复查了以下容易被全绿测试掩盖的边界，未发现新的可执行问题：

1. Lite 顶层字段缺失、AdditionalTools 首位约束、随后 developer instructions 与首个 user 截断均与冻结源码和
   Responses Lite 测试形状一致；真实 tool catalog 不再产生空投影。
2. receipt 的六段 provenance 来自实际成功注册的同一批 parsed request，不参与跨侧等值判定；第一侧付费请求仍由
   receipt 预置合同约束，未恢复“首侧先放行”。
3. identity addition、后续修改、恢复、no-ff merge、无关提交以及 TREESAME merge 都有 focused 回归；完整历史
   检查只约束新 identity lock，不误冻结 active pointer 或引入新的 campaign 身份体系。
4. projection/receipt schema 都在尚无正式 v7 identity/receipt 时升级，没有历史正式 v7 工件兼容负担；历史
   campaign schema v1—v6 路径未被改写。
5. 第三次审查已闭合的 harness 启动前门禁、Guardian 真实轨迹和 receipt 批次幂等语义在本批没有回退。

## 验证记录

本轮独立运行：

- `tests.test_fair_comparison`：87/87 通过，0 skip，3.112s；清除了 ambient HTTP proxy。
- `just eval-lock`：通过，`Resolved 85 packages in 13ms`。
- 第四次审查原始 Lite 纯复现：真实前缀为 `['additional_tools', 'message']`；catalog 差异得到两个稳定分区
  原因，task-only 差异得到空 reasons。
- `git diff --check 191cb50..d0da450`：通过。
- `eval/locks/`、`eval/results/`、`mydev/`、`eval/uv.lock` 相对 `e23d82f` 无改动，`multidev/` 不存在；
  主工作区与目标 worktree 在写本日志前均干净。

本轮没有重复较重验证。实现者日志
`agent_log/2026-08-13-210150-eb8-fourth-review-remediation.md` 记录的证据已核对并作为形成时点证据纳入：

- 定向 26/26、全量 eval 578/578，均 0 fail、0 skip；
- synthetic Docker fix-git 双侧 2/2，完整 canary 10/10 tasks、20/20 sides；每侧均为
  main → Guardian → main，60/60 非空 Lite 投影、provenance 与 gate registrations 通过；
- 真实 API 0、费用 0，未 pull/build 镜像，最终 Docker 占用与基线一致，临时对象已清理。

这些 Docker/全量数字不是本轮独立重跑结果；其 synthetic identity 边界也不能替代正式 v7 生命周期。

## 最终边界

E-B8 设施代码可以结束 blocked 状态并作为工作包 1 的已完成实现保留。下一步若要建立正式 v7 campaign，仍必须：

1. 在 pilot 后冻结奇数且不少于 3 的重复合同与聚合公式；
2. 单独授权 campaign cap，并通过唯一 successor 入口创建新 identity；
3. 再执行正式 identity commit → receipt producer CLI → worker CLI 的入口级验收；
4. Oracle、wire、真实 API/付费 campaign 仍按各自授权边界执行。

本次验收不要求、也不建议增加签名、外部可信根、审计平台、统计显著性框架或 Multi 产品设施。
