# Plan 068 独立验收审查

## 审查结论

- 审查对象：`9846332391e037d9354374205900a79a29b7444e`，进入审查时 worktree clean。
- 验收状态：`NOT_ACCEPTED`。
- 任务目标状态：`NOT_COMPLETED`。本地工件交接可信，但四对象正式资格结论存在阻断级口径错误，且 winner 卷仍存在。
- M3-C2 继续保持锁定。即使修正后 C1/C3 转为 `QUALIFIED`，当前 base 仍因 projected drift 和临时 verdict mismatch 未通过，不能解除前置。

## Findings

### P1：service projected parity 门混淆语义，C1/C3 资格结论不能成立

Rust `PROJECTION_TOLERANCE=1e-12` 只校验**同一次 worker 响应内部**的
`projected_score == sigmoid(raw_logit)`，见 `multidev/codex-rs/publication-critic/src/real_scorer.rs:38,439-440`。
正式 freeze 却把同一数值用作两次独立 CUDA BF16 inference 之间的 service score drift 门。

这个跨运行门没有经过代表性 fresh-worker reload commissioning：

- `qualification-basis.json` 只解释了 service raw drift `0.25`，没有 service projected drift 的工程理由；
  `unchanged_frozen_service_projected_gate=1e-12` 只说明沿用，不能替代口径依据。
- 同一 freeze 允许 raw drift `0.25`、一般 BF16 projected drift `0.005`，但把重复推理 projected drift 设成近似逐位相等，口径不协调。
- C1/C3 的 raw drift 分别为 `0.125` / `0.0078125`，verdict mismatch 均为 `0`，service stress 均为 `15/15`；
  它们只因 projected drift `9.578876694e-10` / `0.000950479009` 超过 `1e-12` 而成为 `NOT_QUALIFIED`。
- tracked 单元测试中的通用 fixture 使用 `0.001`，进一步说明 `1e-12` 不是实现合同固有要求。

这违反 ExecPlan“代表性全链 commissioning 后，再冻结有工程依据且非候选特化的数值门”的硬约束。不能在旧 formal
结果上事后改值重算，也不能继续把 C1/C3 当成有效模型失败。

修复要求：保留 `1e-12` 作为单次响应内部 projection 协议校验；用少量代表性 fresh worker reload 做窄 commissioning，
为跨运行 service parity 单独给出与 raw/verdict 及既有 `0.005` 部署漂移口径协调的统一工程门。不得按 C1/C3 当前结果倒推刚好通过的值。
随后冻结新的 clean source/config，使用新的 write-once namespace 完整重跑四对象正式资格轮并更新三态结论。

### P1：正式 service/worker 继承了完整开发会话环境

`eval/rondo_eval/publication_critic/local_deployment/service_runner.py:522-529` 使用 `os.environ.copy()` 启动 Rust service，
后者再启动模型 worker。这会把与推理无关的开发会话变量乃至可能存在的凭据一起传入正式 runtime，也让未冻结变量影响正式运行，
不符合根安全合同和 ExecPlan 的最小变量注入边界。

修复要求：改为面向本地 CUDA/动态库、离线模型、Python path 和根 watchdog 所需变量的窄 allowlist；明确排除 S3、API、HF token
及任意无关变量。加一个不含真实秘密的 sentinel 回归即可，不需要建设通用凭据审计设施。

### P2：formal service 输入与聚合 observations 缺少轻量直接绑定

`service_runner.py:508-520` 只确认 packet 是 JSON，没有记录冻结的 service sample identity / packet hash；offline 输出也没有 freeze hash。
最终 evaluator 接收另行组装的 observations，archive 只保存 freeze/result。当前正式 packet 已只读核对，确实对应
`pc-v1-cal-nc-pass`，没有发现本次实际错配；但新正式轮仍应消除人工组装误配的低成本风险。

修复建议：在 freeze/runner 中绑定一组 service sample identity 与 packet hash，让 offline/service/raw observation 至少带 run/freeze/artifact/input
的直接 hash 或由 raw 输出机械派生 observations。普通 JSON/hash 足够，不引入数据库、签名链、registry 或新可信平台。

## 已通过部分

- 本地交接 inventory 为 120/120 文件、`24,385,153,354` bytes，文件/目录权限为 `0600/0700`；base、C1/C2/C3、完整 C3
  checkpoint、依赖与身份交叉证据完整，未发现缺失、符号链接或 hash/bytes 错配。
- 当前 formal/debug namespace 隔离、write-once 归档、纯评估重算、unseen-test 隔离均正确。
- Rust scorer/service/probe 的既有协议接缝、typed failure、取消、worker restart、graceful/forced cleanup 与正文/raw score 隔离未发现问题。
- 审查者只运行轻量定向 Python 测试 45/45，通过；`git diff --check` 通过。未重跑真实模型、Rust Cargo、Docker 或其他重型门禁。

## 替用户作出的决定

1. **当前不确认删除卷。** 本地副本完整性可以保留为已通过事实，但 Plan 的删卷门还要求有效的四对象三态结论；P1 未修复前，
   不得再次删除或间接重试 exact volume `hi3iaz8rsr`。约 `$0.005833333/h` 的短期存储费用优先让位于唯一远端副本安全。
2. 修复上述问题并由新的 clean formal 结果通过复验后，若本地交接事实未发生退化，则最合理决策是精确确认永久删除
   `hi3iaz8rsr`、复核 0 Pod/0 volume 持续费用；不需要重新下载、训练、新建 Pod、启用云计算或启动 M3-C2。
3. 不要求扩大测试或审计。执行者只需完成口径 commissioning、环境最小化、轻量输入绑定、相关回归和一次新的干净正式资格轮；
   既有 113/113 Python、34/34 Rust 等无关且未受影响的重型证据无需机械重跑。

## 复验入口

执行者完成窄修、更新 Plan/同一执行日志并提交 clean checkpoint 后，重新通知本审查者。复验重点为新 gate 的事前工程依据、
新 formal 的 source/freeze/namespace 一致性、环境 sentinel、输入绑定、四对象结论和 worktree clean；其余已通过部分不重复扩大审查。
