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

修复批次仍需交还同一独立审查者复验，本日志不提前记录为通过。
