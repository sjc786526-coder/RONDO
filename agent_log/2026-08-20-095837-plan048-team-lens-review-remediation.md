# Plan 048：独立审查修复

## 审查结论与修改

- 首轮独立正确性/功能性审查未通过，复现 6 类真实问题：Fact observation 误报、遗漏 `team_retire`、原生事件
  fail-open、Team View 交叉关系未校验、失败/取消 inference usage 误报完整，以及 terminal 起点早于 runtime begin。
- 已分别修复：dump Fact 保留未知 availability；归约 retire 并标记过期 attention snapshot；补原生 v1 variant 必需字段、
  envelope、code-cell/MCP/compaction 关联；校验 Team/Common 双向引用、root 角色和 usage 聚合；任何 inference 缺 usage 均
  按状态降级；terminal 优先使用 runtime-start，缺失时仅保留 dispatch fallback 并标 `partial`。
- fixture 改用冻结 Rust schema 的原生字符串 status 和带 name 的 `ToolCallKind::Other`，未提交真实 raw trace。

## 验证

- `PYTHONPATH=eval python3 -m unittest -v eval/tests/test_team_lens.py`：18/18 通过。
- 指定 24/24 个 RONDO M-5 bundle 只读归约成功，JSON/HTML 重复生成均字节一致；动态 Fact 语义纠正后 1 个 bundle
  五类 Team capability 全 `available`，其余诚实降级，不影响零 hook 结论。
- 未运行 Cargo、Docker、真实 API、模型、完整数据集或全量测试；未执行 `just eval-sync`。

## 第二次复验修复

- 第二次复验确认首轮 6 项均关闭，但复现 ownership、capability 语义、deduplicated attention stale 和 Agent summary
  可选字段四个残留问题。
- 已补 turn/tool owner 映射以及 terminal/interaction 归属和 kind 一致性；`available` 不得携带 reason，降级状态必须有
  reason，usage/Fact 缺值不得声称 `available`；attention 改用 result/dump revision 并排除 deduplicated；Agent
  summary 的 `task_name` 非空时严格要求字符串。
- `PYTHONPATH=eval python3 -m unittest -v eval/tests/test_team_lens.py`：19/19 通过；24/24 指定 bundle 归约和重复
  JSON/HTML 确定性继续通过。

## 第三次复验修复

- 第三次复验确认第二轮 4 项均关闭，但复现 interaction endpoint 与产品四态边界两个残留问题。
- 已用 `parent_agent_id` 要求 `spawn_agent` 为 parent→child、`agent_result` 为 child→parent；共有 capability 不得
  `not_applicable`，RONDO Team capability 不得 `not_applicable`，只有无 projection rows 时 projection 可
  `unsupported`，其余 Team 类别不得 `unsupported`。
- 19/19 定向测试与 24/24 指定 bundle 归约、JSON/HTML 确定性继续通过。

## 第四次复验修复

- 第四次复验确认第三轮问题已关闭，但发现 `ThreadStarted.metadata_payload` 合法缺失时 parent 未知，被 endpoint
  等式误拒绝。
- 现仅在 parent 非空时校验 parent 等式，始终要求 spawn/result 非 self 且 child/source 为 spawned；非 root Agent
  parent 缺失时输出 `partial / agent_parent_missing`，并新增可选 metadata 缺失回归。
- 20/20 定向测试与 24/24 指定 bundle 归约、JSON/HTML 确定性继续通过。

## 最终独立验收

- 第五次独立复验明确 `PASS`：第四轮 optional metadata 场景正确降级，历轮功能反例继续受控处理。
- 审查者独立确认 20/20 定向测试、24/24 指定 RONDO bundle、JSON/HTML 确定性、CLI、diff check 和 tracked
  worktree 状态通过，未发现新的可复现正确性或功能问题。
