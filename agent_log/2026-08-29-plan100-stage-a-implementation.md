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
  五类路线原文字面条件不穷尽所有 formal 组合，未暗中扩写；未映射签名显式令 formal 无效并归入技术型 `INCONCLUSIVE`，交由阶段 A 审查裁决。

## 边界与事件

- 阶段 A 初始宽检索造成 qualification 正文意外输出；发现后立即停止并主动报告。独立事件审查以提交 `387702e9` 裁决
  `ACCEPTED_WITH_CONTAINMENT`；后续只使用显式 allowlist，本实现未引用、复述或据此调整 prompt/schema/fixture/threshold/rubric/label/data/route。
- 当前执行者与收到该输出的上下文永久不承担未来 qualification/test 释放、阈值返调或最终资格裁决。阶段 A 未调用真实 API/模型，未使用
  GPU、RunPod、Docker、训练、上传、冻结测试、产品动作、合并或推送。

## 验证

- `PYTHONPATH=eval python -m unittest -v eval.tests.test_publication_critic_plan100_structured_diagnostic`：14 tests 通过。
- `pytest -q eval/tests/test_publication_critic_plan100_structured_diagnostic.py`：`13 passed, 9 subtests passed`。
- Plan 100 Python 文件定向 `ruff check`：通过；JSON 合同/descriptor 解析与 `git diff --check`：通过。
- `just fmt`：通过。
- 正式 build-lock/shared `rondo-multi` target 下 `just test -p codex-publication-critic`：`68 passed, 0 skipped`。
- 显式移除 `DEEPSEEK_API_KEY` 后运行 tracked descriptor + synthetic packet，进程到达 `invalid_configuration`，证明 descriptor/packet 本地验证通过且未发请求。

## Ignored 资产

- `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan100`：约 92 MB，阶段 A 的 uv/pytest/ruff 任务缓存；保留供阶段 B 与复验复用。
- `/home/sjc/desktop/RONDO/.codex/cargo-target/rondo-multi`：约 228 GB，仓库唯一共享正式 Rust target；按硬边界复用并保留，不是 Plan 100 独占资产。
- worktree `.codex/build-watchdog`：约 76 KB，本次两轮正式 Rust 测试的 watchdog/JUnit 证据；保留至阶段 A 验收。
