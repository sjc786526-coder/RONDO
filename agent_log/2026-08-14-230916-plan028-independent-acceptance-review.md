# 2026-08-14 Plan 028 / WP3b-A2d 独立验收审查

- 审查对象：`028-wp3b-a2d-static-payload-v3-census@c00371e`
- 任务基线：`c37ad11`（`main@dc1de71`）
- 审查范围：提交差异、census 锚点/失败/清理代码路径、两份 WBS 与执行日志、focused tests、eval lock、
  baseline/端口/GPU/临时目录现场；未重新加载模型或运行 census。

## 结论

**执行验收通过；任务目标失败。**

执行者正确执行了 Plan 028 的失败合同：第一遍真实 count-only 运行成功到达冻结 b10333 并取得锚点计数，
但观测值 `5,311` 不等于冻结预期 `5,313`，因此在遍历其余 46 条之前 fail-closed。第二遍未运行，正式
baseline 未生成，生产代码/档位/capability/qualification 均未修改，本次服务和私有对象已清理。

这说明“遇到合同漂移时该怎么停”做对了，但不等于用户预期的 47/47 普查已经实现：全集 token 分布、
两遍一致性、4k/8k 覆盖和正式 baseline 仍然全部缺失。因此 WP3b-A2 继续保持 incomplete。

## 审查发现

### 1. fail-closed 路径正确，无阻断问题

`run_census()` 在服务就绪、身份和短探针通过后先计锚点；观测值不等于 `ANCHOR_INPUT_TOKENS` 时立即抛出
`anchor_token_count_mismatch`，不会进入 47 条循环。异常仍经过 `finally` teardown，失败路径不会构造或写入
census document。`c00371e` 没有修改该实现，只按失败口径更新 Plan、两份 WBS 和一份日志。

现场与提交共同确认：

- `eval/results/baselines/local-approval-exact-token-census-v1.json` 不存在且不在索引中；
- `doc/WBS-COMPLETED.md` 未改；
- 没有生产代码、测试、配置、模型/runtime、qualification 或 capability 差异；
- 第二遍未运行符合 Plan 028 §3.3/§3.4，不属于缺少应执行步骤。

### 2. v3 已改变锚点请求，旧 5,313 不能继续无条件充当当前锚点

审查者使用现有生产 reader/meta 校验和公共 builder 做了只读、无模型、无正文输出的结构复核：输入集合仍为
47 条；锚点为 `responses_lite`，raw input 共 5 项，角色计数为 `developer=3`、`user=2`。其中三个
developer 角色分别包含 Lite marker、policy message 和证据 message；marker/policy 被提取后，v3 出站 input
为 3 条 user message。该结果独立复核了执行日志所述“恰好一条证据 developer 被 v3 原位改写为 user”。

Plan 023/024 的 5,313 来自 v3 之前的请求；当前冻结 tokenizer 对 v3 请求实测 5,311。因此旧常量所绑定的
请求身份已经变化，本轮因两 token 差而停止不是 tokenizer 近似误差，也不应通过放宽锚点检查绕过。

执行文档已明确：本轮只有一次 5,311 真模型观测，“角色标签变化解释精确两 token 差”尚未独立重复测量，
不能推导其余 46 条。这个证据边界是诚实的。

### 3. 一处非阻断的文档精度提醒

`doc/WBS/local-approval-model.md` 使用了“当前阻塞点是锚点常量，不是服务兼容性”，根 WBS 使用了“失败点已从
服务侧前移到合同侧”。对**本次已观测的锚点请求**，这两句话成立：服务成功返回 exact count，直接失败点是
锚点合同。

但其余 46 条从未在 v3 下计数，不能据此宣布全集服务兼容已经成立。由于同一组文档同时明确写了“其余 46 条
未计数、没有全集分布”，当前不会造成实质性错误，本审查不要求为这一句话单独再做文档提交。下次更新 WBS 时
宜收敛为：“已知直接阻塞是 v3 锚点合同；其余 46 条的真实可计数性仍待完整重跑验证。”

### 4. 首次误用 main wrapper 是已披露、非阻断偏离

第一次命令误用了主工作区的 `scripts/with-build-lock.sh`，被 watcher checkout 身份检查在模型加载前拒绝；
随后使用 worktree 自身脚本才进入唯一一次正式模型生命周期。前一次没有启动服务、占用 GPU 或产生测量值，
也没有削弱共享锁，因此不影响结果有效性。该失误已如实写入执行日志，无需新增设施防护。

## 独立验证

- `git diff --check c37ad11..c00371e`：通过；任务 worktree 与主工作区均干净。
- focused tests：
  `tests.test_contracts_and_evidence` + `tests.test_local_approval`，**116/116 通过**，14.206s。
- eval dependency lock：共享 cache 下 `uv lock --directory eval --check`，**85 packages**，通过。
- 只读结构复核：47 条完整；锚点 `responses_lite`；raw role counts 为 developer 3/user 2，v3 input 为 user 3；
  未输出正文、路径、请求或 token 明细。
- 现场清理：8080 无 listener；无 `llama-server` 进程；NVML 无 compute process；GPU 现场为 1392 MiB、1%；
  `eval-data/local-approval/` 为空；正式 baseline 不存在。
- 未运行：真实模型复跑、第二遍 census、generation、qualification、Cargo、Docker、云 API、全量 eval。

## 替用户作出的决策

1. **接受 `c00371e` 作为一次正确的 Plan 028 失败执行。** 不要求在 Plan 028 内继续模型运行，也不要求为了
   “完成”而修改冻结合同；该分支可在用户后续批准时按失败历史合并。
2. **不回退 static payload v3，不删除或放宽锚点门。** v3 已解决公共 payload 的角色兼容，回退会重新引入
   已关闭的问题；取消锚点则会失去请求口径漂移检测。
3. **历史 5,313 保留为 pre-v3 实测事实，但不再作为 v3 请求的正确期望值。** 下一任务应做一次窄的锚点合同
   迁移：把当前 v3 锚点期望改为本轮 exact 实测的 **5,311**，同步必要注释和直接测试即可；不升级为通用
   measurement identity、版本注册表或审计系统。
4. **无需额外安排孤立的第三次“只测锚点”生命周期。** 新任务更新常量并通过无模型 focused 门禁后，直接把
   第一次完整 47/47 census 作为 5,311 的独立复证；若成功再执行第二遍一致性运行，任一遍锚点不是 5,311
   仍照常 fail-closed。这同时完成复证并减少一次模型加载。
5. 新任务需重新获得真实模型/GPU 授权；在完整 47/47 和两遍一致性完成前，不选择上下文档位、不发布 baseline、
   不晋级 capability，也不把本轮 5,311 外推到其余 46 条。

## 最终状态

| 维度 | 结论 |
|---|---|
| 执行是否做对 | **验收通过** |
| Plan 028 预期目标是否完成 | **失败：0/47 可发布，只有锚点一次 5,311 诊断观测** |
| WP3b-A2 | **incomplete** |
| 正式 census baseline | 不存在 |
| 上下文档位 | 未选择 |
| capability | `linux_cuda_built_model_unvalidated`，未晋级 |
