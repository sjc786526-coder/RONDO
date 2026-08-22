# Plan 052 主分支集成

## 本次处理

- 将 `worktree-052-direction1-bottleneck-census@7314c3a` 合并到
  `main@4823c40`；代码与测试改动自动合并，手工处理 `doc/WBS.md`、
  `doc/WBS/teacher-harness-study.md`、`doc/WBS/eval-benchmark.md` 和
  `doc/WBS-COMPLETED.md` 的文档冲突。
- 保留 main 已有的方向 3 / Plan 053 当前事实，同时登记 Plan 052 已完成、
  “证据不足，暂不选择行为优化”的结论，以及方向 1 下一包为另行授权的
  10 题 × 2 轮有界测量。
- 在 WBS 明确统一使用“方向 1”和“方向 3”的规划口径：`mydev/` 是方向 1
  源码位置，不再把“Local”当作方向名称；必须出现 `RONDO Local` 或
  `rondo-local` 时，仅表示产品或运行身份，不表示已关闭的方向 2。
- Plan 055 专用 worktree 已有未提交实现改动，本次只核对状态并完整保留，
  未读取其未提交内容、未改写、未同步 main，也未将其纳入 Plan 052 合并。

## 合并后验证

- Python：`tests.test_harness_observation tests.test_team_lens`，51/51 通过。
- Rust：通过仓库构建锁运行两项定向测试，2/2 通过：
  - `code_mode_exec_delivery_records_only_model_call_identity`
  - `public_exec_parse_failure_records_one_model_output_delivery`
- `git diff --cached --check` 通过，无未解决冲突标记。
- 首次 Rust 调用因沙箱无法创建项目内构建看门狗目录，在 Cargo 启动前以
  exit 80 停止；取得项目内写入权限后按同一受控入口重跑并通过，不计为代码失败。

## 边界

- 未调用真实 API、Docker 或本地模型，未训练、未产生费用，未运行全量测试。
- 本次不实现方向 1 的下一轮测量，也不接管 Plan 055 的实现或文档收口。
