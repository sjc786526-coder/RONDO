# 2026-08-14 Plan 029 / WP3b-A2e：static payload v3 的 47/47 exact-token 普查（通过）

分支 `029-wp3b-a2e-static-payload-v3-census`，起点 `f3c2d57`。目标是把 v3 锚点窄改为 5,311 后完成两遍
一致的 count-only 普查并发布唯一正式 baseline。**结论：通过，两遍逐字节一致，baseline 已发布，
WP3b-A2 闭合。**

## 实质改动

1. `eval/rondo_eval/local_approval/token_census.py`：`ANCHOR_INPUT_TOKENS` 由 `5_313` 改为 `5_311`，
   同步模块 docstring 与两处行内说明；常量注释补一句为什么 pre-v3 是 5,313（那条证据 `developer`
   消息当时经 `map_developer_role_to_system` 以 `system` 进入冻结模板）。没有新增 schema、
   版本注册表、容差或第二套锚点机制。
2. `eval/tests/test_local_approval.py`：4 处直接代表锚点或 `锚点 - 1` 的断言/fixture 随之更新
   （`5313 → 5311` 三处、`observed 5312 → 5310` 一处），另修一句已过时的 Plan 023 注释。
   历史文档中的 pre-v3 5,313 未批量替换。
3. 新增 `eval/results/baselines/local-approval-exact-token-census-v1.json`（正式 baseline）。

## 执行顺序

先过无模型门禁再加载模型：focused `tests.test_local_approval` + `tests.test_contracts_and_evidence`
**116/116，14.274s**；`uv lock --directory eval --check` **85 packages**。
运行前现场：正式 baseline 不存在、8080 空闲、无 llama-server、GPU 无 compute process、
`eval-data/local-approval/` 无残留、共享锁空闲、Windows `C:` 实际剩余约 192 GiB、项目根 18.4 GB；
doctor 为 `configuration: valid` / `model: present` / `linux_cuda_built_model_unvalidated` /
`model_backed_validation: not_run`。

两遍都从本 worktree 的 `./scripts/with-build-lock.sh` 启动，走同一个 census 正式入口、static payload v3、
公共 Local request builder 和冻结 b10333 count endpoint，结果先写各自的 ignored 临时路径。

## 结果

```
两遍均：status=complete  missing_counts=0  counted=47/47  refused=0
        anchor=5311 (expected 5311)  generated_tokens=0  exit=0
        cleanup: server_stopped / port_released / private_artifacts_removed 全 true
digest      = 22b8452717f1bcfa692cffa69389ebb4a21a0aef1a9187cd066879a6b0831144（两遍相同）
file sha256 = 0c49ca78d8ca53ff2331fec7734e67f0d2302223d6e5f7a5d64554d5be882606（两遍相同）
```

全集分布（47/47）：min 5,311、p50 8,989、p90 12,352、p95 13,754、max 22,499；47 条全部
`responses_lite`。按 `input+512`：**4k 适配 0/47，8k 适配 11/47**。

两份临时结果确认逐字节一致后，才把该字节一致结果复制为唯一正式 baseline，并删除临时文件与任务私有目录。

## 值得记的两点

- **锚点常量是唯一阻塞点，没有第二个缺陷。** Plan 028 停在锚点之后，一直不知道其余 46 条在 v3 下能否
  被计数。这次第一遍就 47/47 一次跑通，没有触发任何整改循环——包括此前从未被计过数、含
  `assistant → developer` 相邻关系的那 23 条。Plan 026 的通用 500 未再复现，但本次**没有单独定位**
  那一次失败，只能说它在 v3 下不再发生。
- **两遍都很快（各约 1 分钟）。** count-only 不做任何生成，模型权重又在页缓存里，所以耗时几乎全在
  加载与 47 次 tokenize。这不构成任何性能结论。

## 验收结果

- 47/47：**达成**，两遍各自独立取得，锚点 5,311 由这两遍相互复证。
- 两遍一致性：**逐条记录、摘要、digest 与整文件字节全部一致**。
- focused tests：**116/116 通过**，14.274s（模型加载前）。
- 依赖锁：`uv lock --directory eval --check` **85 packages** 通过。未按原样跑 `just eval-lock`——
  该配方硬编码 `$PWD/eval-data/uv-cache`，本 worktree 无该目录，改用指向主仓 cache 的等价命令。
- 清理与状态：8080 空闲、无 llama-server、GPU 无 compute process、`eval-data/local-approval/` 为空、
  构建锁已释放、主工作区干净；capability 仍为 `linux_cuda_built_model_unvalidated`，
  `model_backed_validation` 与 `model_backed_structured_output` 仍为 `not_run`，无新增资格 evidence。
  两次运行的 watchdog metrics 保留在 worktree 的 ignored `.codex/build-watchdog/` 下作为运行凭据。
- 未运行：任何 generation、qualification launcher、L7、Cargo、Docker、云 API、全量 eval、全量测试。
- 未做：上下文档位选择——本任务只形成完整事实，档位定案按 WBS 作为下一个决策门。
