# Plan 068 删除前独立复验

## 结论

`LOCAL_HANDOFF_ACCEPTED`

- 复验对象：`adb92e89b60ff232840510a34eca784c10de0284`；进入复验时 Plan 068 worktree clean。
- 上轮两项 P1 与一项 P2 均已正确闭合，未发现局部修复造成的功能或安全回归，`remaining_findings=[]`。
- 本结论只批准按既有一次性授权永久删除 exact RunPod network volume `hi3iaz8rsr` 并复核止费；不批准删除其他资源，
  不解锁 M3-C2，也不授权训练、云计算、产品启用、合并或推送。

## Finding 闭合

1. 跨 fresh-worker projected parity 与 Rust 单响应 projection 校验已分离。C1 四个 fresh CUDA BF16 worker 均顺序完成
   load/score/shutdown/reap，pairwise raw/projected drift 为 0；统一 `0.005` 门在 v3 formal 前冻结，复用已有 BF16 部署 projected
   drift cap，不按 C1/C3 结果贴线。单响应内部 `1e-12` 校验保持不变。
2. service 与 probe 均使用同一个窄环境 allowlist，仅传入 CUDA/动态库、离线模型、Python path、线程数和根 watchdog 所需变量；
   不再使用完整会话环境。无秘密 sentinel 回归确认无关变量不会进入 service，probe 复用同一 helper。
3. freeze/offline/service/observations/result/archive v2 已用普通 JSON/SHA-256 直接绑定 run、freeze、artifact、cohort、packet、
   real service/probe/python 程序和 raw evidence。实现保持轻量，没有引入数据库、签名链、registry 或通用审计设施。

## 正式结果复验

- 唯一有效正式轮为 `plan068-formal-20260824T222852Z-qualification-v3`，绑定 clean source
  `3906152d1348c273f1cd94404f2a3978f2a836fc` 与 canonical freeze
  `4497b02ed95583e3b2daf5ad1a102199d8144db27b20375255eefdfe3f5f1ce0`。
- 27/27 正式小型 evidence 文件的 bytes/hash 匹配；observations canonical hash 与 result/summary 一致；纯 evaluator 重算与
  write-once archive 完全相等。
- 旧 `...T201213Z...` 已因错误门明确失效；`...T221100Z...` 是 service binary 选择错误的基础设施失败轮，没有 result/archive，
  两者均未拼入 v3。
- 有效结论为 base `NOT_QUALIFIED`、C1 `QUALIFIED`、C2 `NOT_QUALIFIED`、C3 `QUALIFIED`。C1/C3 真实 service verdict
  mismatch 为 0、stress 均 15/15；代表 C1 的 typed failure/restart/cancel/shutdown/cleanup 完整。base 未通过，因此
  `m3_c2_prerequisite_satisfied=false` 正确，M3-C2 必须继续锁定。

## 本地交接与定向门禁

- 本地 120/120 工件保持逐文件 bytes/hash/身份闭合，总计 `24,385,153,354` bytes；无符号链接，权限为文件 `0600`、目录
  `0700`。完整 checkpoint 为 12 文件、`10,555,059,139` bytes，optimizer/scheduler/RNG 验证事实保留。
- unseen-test 未导出、读取或运行；没有访问 `.env.local`、权重正文或其他并行 worktree 现场。
- 本审查运行 Plan 068 轻量 Python 定向测试 41/41，`git diff --check` 通过；未重跑真实模型、Cargo、Docker 或未受影响的重门禁。
- 复验时通过已鉴权 RunPod MCP 实时查询：Pod 总数为 0；network volume 总数为 1，且精确为 `hi3iaz8rsr`、`US-KS-2`、
  `STANDARD`、60GB。未修改任何远端资源。

## 替用户作出的决定

1. 我确认永久且不可恢复地删除 RunPod 网络卷 `hi3iaz8rsr`。执行者只能精确删除该 ID；不得按名称模糊匹配或删除任何其他资源。
2. 删除后立即只读复核：目标卷不存在、Pod 仍为 0、compute 与 volume 持续费用均为 0。若精确删除失败，保留现场并如实报告，
   不绕过安全层、不新建 Pod、不采用间接删除。
3. 删除及复核成功后，更新 Plan 与同一执行日志、提交最终 task-branch checkpoint 并保持 clean，再交本审查者做删除后最终验收。
   不合并、不推送、不启动 M3-C2。

## 当前双维状态

- 验收状态：**通过（删除前本地交接与资格复验）**。
- 任务目标状态：**预期业务目标未达成**。资格执行本身正确完成且 C1/C3 合格，但 base 不合格使“base + 至少一个训练候选进入
  M3-C2”的目标失败；Plan 068 流程终态仍待精确删卷、止费复核和最终提交。
