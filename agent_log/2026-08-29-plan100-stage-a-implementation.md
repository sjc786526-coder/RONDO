# Plan 100 阶段 A 本地实现

## 实现

- 新增 Plan 100 专用 development-validation 薄层：精确绑定 v10 validation 27 candidates / 12 pairs，仅把 canonical public packet 交给 evaluator，
  labels、pair 与 continuity basis 在 write-once provider receipt 完成后才本地 join。
- Rust eval-only 接缝复用既有 cloud scorer 的 HTTP、retry、usage、served-model 和 body-free 日志路径，增加 scalar / direct gate / five-dimension
  三种严格输出、每次 attempt UTC 时点、bounded raw assistant response 与本地五维 non-compensating AND；产品 scorer、typed wire 和默认路径不变。
- Python runner 实现 task-wide 20 RMB durable reservation、按北京时间实时价档和 usage 分类结算、离线 token recount 后才使用 0.1 RMB 末级 fallback、
  receipt-first 恢复、parse failure 正式 terminal、技术失败停轮、81-row fake formal、独立复算和 body-free tracked projection。
- 独立审查后把 B1 准入硬化为 9/9 strict success、至少一项且全部 usage-present attempt 的 prompt/completion recount 精确校准，并要求 B2 freeze
  与成功 B1 的 source/provider/request/release/comparison/price identity 完全一致；authority 后 provider resume 保持锁定，但允许只读独立复算。
- raw/tracked formal 结果绑定 task-wide ledger snapshot/aggregate，覆盖 commissioning、retry、恢复与技术无效 clean run，不再只报告本轮 formal 费用。
- tracked 合同与 fixture 冻结阶段 A descriptor、v2 prompt 候选、1 synthetic + v10 public min/max commissioning、A/B/C metrics 与 formal 准入。
  经审查者语义裁决，完整有效 formal 未命中既有四个质量谓词时返回既有 `CONSTRAINT_OR_DATA_ISSUE` 并单列 `residual_mixed_signal=true`；该
  fallback 不改变 metrics、不伪造 concentrated blocker、不证明数据缺陷或 backbone 原因，也不直接支持付费解冻训练。
- 修正 DeepSeek 价档为北京时间周一至周五 09:00–12:00、14:00–18:00 peak，周末全天 off-peak；价卡 identity/合同/边界测试同步更新，首次
  真实请求前仍必须 live refresh/freeze。
- 阶段 A 准入复核后固定主物理根唯一 Plan 100 task root：B1 可首次创建唯一账本，B2 必须复用 existing 账本、读取该 root 内实际 B1 binding，
  并在每次 provider-capable 运行前重新验证 clean HEAD、contract、environment、executable、descriptor 与 recounter。B1 已结算记录必须逐项保留。
- authority 成为 task-wide provider 封口；独立 recompute 只读打开既有账本且验证 authority 的 run/freeze/result hash。formal transient technical
  receipt 只在显式同 freeze resume 时追加失败 logical 的下一 ordinal，已完成 terminal 不重放；无 response 且无 usage 的 attempt 禁止伪 recount，
  按 0.1 RMB 末级 fallback 结算。
- 新增 bounded detailed projection，交付 A/B/C candidate error、各臂 12 pair rows、A 完整 operating curve 和 C target/invariance，不含 packet、
  response 或 credential；aggregate tracked summary 保持不变。

## 边界与事件

- 阶段 A 初始宽检索造成 qualification 正文意外输出；发现后立即停止并主动报告。独立事件审查以提交 `387702e9` 裁决
  `ACCEPTED_WITH_CONTAINMENT`；后续只使用显式 allowlist，本实现未引用、复述或据此调整 prompt/schema/fixture/threshold/rubric/label/data/route。
- 当前执行者与收到该输出的上下文永久不承担未来 qualification/test 释放、阈值返调或最终资格裁决。阶段 A 未调用真实 API/模型，未使用
  GPU、RunPod、Docker、训练、上传、冻结测试、产品动作、合并或推送。

## 验证

- `PYTHONPATH=eval python -m unittest -v eval.tests.test_publication_critic_plan100_structured_diagnostic`：20 tests 通过。
- 隔离 uv pytest：`20 passed, 24 subtests passed`。
- Plan 100 Python 文件定向 `ruff check`：通过；JSON 合同/descriptor 解析与 `git diff --check`：通过。
- `just fmt`：通过。
- 正式 build-lock/shared `rondo-multi` target 下 `just test -p codex-publication-critic`：`68 passed, 0 skipped`。
- 显式移除 `DEEPSEEK_API_KEY` 后运行 tracked descriptor + synthetic packet，进程到达 `invalid_configuration`，证明 descriptor/packet 本地验证通过且未发请求。

## Ignored 资产

- `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan100`：约 92 MB，阶段 A 的 uv/pytest/ruff 任务缓存；保留供阶段 B 与复验复用。
- `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi`：约 228 GB，仓库唯一共享正式 Rust target；按硬边界复用并保留，不是 Plan 100 独占资产。
- worktree `.codex/build-watchdog`：约 76 KB，本次两轮正式 Rust 测试的 watchdog/JUnit 证据；保留至阶段 A 验收。
