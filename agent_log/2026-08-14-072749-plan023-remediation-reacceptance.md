# Plan 023 修复复审与验收

时间：2026-08-14 07:27 PDT

审查对象：`023-local-4k-qualification` 的 `b7efddc`（父提交 `64da6bf`）

范围：复核上一轮 F1—F3、检查相邻的 capability/fail-closed 路径、运行 focused 门禁和无模型现场检查；未启动模型、未做 token census，未进入 Turn B。

## 结论

**修复验收通过。** `b7efddc` 已完整关闭 `agent_log/2026-08-14-061059-plan023-independent-review.md`
中的三项发现；本轮未发现新的阻断问题。实现仍保持 qualification 与正式 launcher 隔离，失败不会产生
model-backed 成功证据或晋级 capability。

这里的“验收通过”只表示代码、失败语义和文档收口通过复审，不表示 Turn A 的产品目标成功：

- Turn A 已完成一次受控真实执行并形成了**完成但失败（completed-with-failure）**的终态；
- 所选、冻结的真实 `E_final` 经服务端实测为 5,313 input tokens，超过固定 4096 上下文，未返回结构化判定；
- 因完成条件缺失，Turn A **未通过资格验证**，capability 正确保留为
  `linux_cuda_built_model_unvalidated`，Turn B 未开始；
- 已有证据只能说明这一条样本不适配 4k，不能外推为其余 46 条归档或整个真实集合均不适配。

因此，本工作树可以作为“资格设施已落地、首次 4k qualification 正确失败并收口”的交付物；不得把它描述为
`gpu_model_serving_validated` 已完成。

## F1：真实 E_final 选择与读取门禁——已闭环

修复不再接受任意位于 `eval-data/runs/.../E_final.json` 的文件：

- 新增受跟踪 selector，预绑定唯一相对路径、`E_final` 与 meta 的精确 size/SHA、review/run identity、期望
  Guardian model/effort；
- 复用生产 safe-reader 与 meta validator，拒绝 symlink ancestor、非普通文件、大小漂移和生产 meta 合同漂移；
- 再与受跟踪 `eval/results/runs.jsonl` 交叉核对 run outcome、artifacts、model 与 effort；
- E_final/meta 各按冻结字节解析，读取前后比较 `(dev, ino, size, mtime_ns)`，请求 payload 不再二次回读路径，
  消除了上一版的同源自证和 TOCTOU；
- focused 负例覆盖伪造归档、selector/meta/ledger 漂移、未选归档、symlink ancestor 与生产 meta 无效。

只读加载当前 selector 得到 `status=valid`，且 source/meta digest 均已绑定；未输出证据正文。

### 关于 selector 形态的决定

**保留现在的单一精确 selector，不在 Plan 023 中扩成多归档清单。** 本次 qualification 的合同就是选择一条
真实 `E_final` 做首次审批验证；单一绑定让换样本成为明确、可审查的 Git 改动，也避免给正常 launcher 引入通用入口。
若后续上下文路线决定需要批量 replay 或 exact-token census，应在对应后续工作包中另建批量 manifest/选择规则，
而不是提前放宽本门禁。

## F2：4k 结论范围——已闭环

WBS、方向 WBS、Plan 与原执行日志均已收敛到可证明事实：只有所选样本的服务端计数为 5,313 tokens，
4096 无法容纳。原先由字符长度推导的“47 条全部装不下”“现存最小”“4k 整体证伪”和“唯一 blocker”
不再作为结论。修复日志也如实记录探索时曾做字符长度观察，但未打印、未持久化，且不再用作判断依据。

这满足 fail-closed 要求，也没有为了补结论而越权读取其余归档或新增模型生命周期。

## F3：VRAM 全窗口采样——已闭环

采样现在对整个生命周期 fail-closed：

- 首个采样异常、任一动态出现的外来 compute PID、采样线程无法退出或零样本都会阻断；
- 自身 llama-server 进程树被排除，外来进程每 200 ms 重验；
- request 后补一次采样，`finalize()` 在允许读取 peak 前重放线程错误；
- 早期正 delta 不能掩盖后续采样缺口。

新增回归覆盖 mid-window failure、动态外来 PID 和 join timeout。实现可能因宿主计数器异常保守失败，但不存在
已发现的错误成功路径，符合 qualification 的失败语义。

## 相邻路径复核

- 正式 launcher 对未晋级 CUDA runtime 仍在 Popen 前拒绝，测试保持覆盖；qualification 没有变成通用 bypass。
- model-backed capability 仍只由完整、严格证据投影；失败、指标缺失、schema/service/identity 错误或清理不完整均不发布证据。
- Plan 018 的 model-free/base runtime 历史没有被覆盖；当前仅存在 qualification 输入 selector，不存在成功 evidence lock。
- source-built CUDA 的真实 `build_info=b1-0865990` 按 backend 精确绑定，client/doctor/router 不再错误套用
  package build 10333 身份；对应回归通过。
- 本轮未发现需要修改 `mydev/` Rust、`multidev/` 或扩大设施的理由。

## 独立验证

在任务 worktree、共享 eval venv/cache 下执行：

1. focused unittest：
   `tests/test_local_approval.py tests/test_config_hardening.py tests/test_config_and_artifacts.py`
   —— **115 passed**，退出 0；
2. `just eval-lock` —— 通过（该命令只验证 uv dependency lock）；
3. 宿主 GPU 视图下无模型 doctor —— 退出 70，内容为
   `configuration=valid`、`model=present`、
   `runtime_capability=linux_cuda_built_model_unvalidated`、
   `model_backed_validation=not_run`、`service=not_started`；
4. 现场检查 —— 无 `llama-server`，8080 无监听，无 GPU compute process，
   `eval-data/local-approval/` 无任务残留；
5. `git diff --check 64da6bf..b7efddc` —— 通过。

未运行：真实模型、其余 E_final census、Rust、Docker、云 API、训练、全量 eval、Turn B、L7、Local M3、8k。
这些均不属于本轮修复复审。

## 验收状态

- `b7efddc` 修复闭环：**PASS**。
- Plan 023 失败收口的实现与记录：**ACCEPTED**。
- Turn A 资格成功判定：**FAIL / 未晋级**，属于已完成的失败结果，不是仍在执行中的成功任务。
- 后续路线应先在 WBS 中决定上下文预算或输入压缩策略；在此之前不得进入 Turn B。

本报告提交在任务分支；未合并、未推送，主工作区保持不变。
