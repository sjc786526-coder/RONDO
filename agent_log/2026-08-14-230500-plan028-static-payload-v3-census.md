# 2026-08-14 Plan 028 / WP3b-A2d：static payload v3 的 47/47 exact-token 普查（未通过）

分支 `028-wp3b-a2d-static-payload-v3-census`，起点 `c37ad11`。目标是用已验收的 static payload v3 对
47 条真实 `E_final` 完成两次 count-only exact-token 普查。**结论：未通过，未发布 baseline，无生产代码改动。**

## 实质动作

1. 运行前只读核对门禁：正式 baseline 不存在、8080 空闲、无 GPU 计算进程、共享构建锁空闲、
   `eval-data/local-approval/` 无残留；doctor 报 `configuration: valid`、`model: present`、
   `linux_cuda_built_model_unvalidated`、`model_backed_validation: not_run`。
2. 在共享锁与 GPU 独占下执行**一次**正式 census（count-only，`max_output_tokens=512`），
   结果写 ignored 临时路径。**fail-closed 于锚点**，按合同未执行第二遍。
3. 只做一次只读、无模型的结构核对以定位锚点差异（只输出角色与计数，不输出证据正文）。
4. 未改动任何生产代码、payload、模板、档位或 census 常量。
5. 按失败口径更新 Plan 028、`doc/WBS.md`、`doc/WBS/local-approval-model.md`，不写 `doc/WBS-COMPLETED.md`。

## 失败事实

```
status  = not_counted     blocker = anchor_token_count_mismatch
expected = 5313           observed = 5311
exit = 70                 log_bytes = 1384  log_lines = 16  infrastructure_lines = []
cleanup = server_stopped / port_released / private_artifacts_removed 均为 true
```

与前两轮不同，本次失败**不在服务侧**：模型加载、服务身份、`/props` 4096 与合成探针全部通过，
锚点请求被**成功计数**，没有 400、没有通用 500、也没有 transport failure。
这是本方向第一次证明真实 b10333 能对一条 v3 真实归档请求完成精确计数。
锚点之后的 46 条**一条都没有计过数**，因此没有全集分布，也给不出全集 4k/8k fit 数。

## 疑难问题：5,313 是 v3 之前的常量

只读结构核对（无模型、无正文输出）显示锚点为 `responses_lite`，原始 `input` 含 1 条
`additional_tools`（按 L1 合同移除）、2 条 `developer` 消息（1 条是 Guardian policy，1 条是证据）
和 2 条 `user` 消息；v3 出站为 3 条 `user`，即恰好 **1 条证据消息的角色由 `developer` 改写为 `user`**。

v3 之前，该消息经 llama.cpp `map_developer_role_to_system` 以 `system` 进入冻结模板；
Plan 023/024 正是在那个实现下测得 5,313。角色标签不同足以产生 2 个 token 的差异，方向也一致。
但本次**只运行一遍**，该解释未经独立复证，也不能反推其余 46 条的任何数值。

因此 `token_census.py` 的 `ANCHOR_INPUT_TOKENS = 5_313` 描述的是 v3 之前的 payload，
与它现在守卫的 v3 请求不是同一个对象。在锚点口径重新确立之前，47/47 普查在现有合同下不可能通过。
本任务不允许改动该常量，也不允许改写自身完成标准，故按交接边界停止并上交 WBS。

## 一处执行者失误（未消耗模型生命周期）

首次调用误用**主工作区**的 `scripts/with-build-lock.sh`。`runtime_bridge` 要求 watcher 进程的
exact cmdline 指向**当前 checkout** 的同名脚本，故在加载模型前即以 `watchdog_unavailable` 退出，
GPU 与端口未被触碰。改用 worktree 自身的脚本后正常（共享锁文件仍是
`/run/user/1000/rondo-cargo-build.lock`，互斥不受影响）。该次尝试不计入正式运行。

## 验收结果

- 47/47：**未达成**。第一遍 fail-closed 于锚点，无新增可发布计数，无全集 min/max/分位数与 fit 数。
- 两次一致性：**不适用**（按合同只运行一遍，无 digest 可比）。
- focused tests `test_local_approval` + `test_contracts_and_evidence`：**116/116 通过，14.252s**。
- 依赖锁：`uv lock --directory eval --check` 通过，85 packages。未按原样跑 `just eval-lock`——
  该配方硬编码 `$PWD/eval-data/uv-cache`，本 worktree 无该目录，改用指向主仓 cache 的等价命令。
- 清理与状态：8080 空闲、无 GPU 计算进程、`eval-data/local-approval/` 无残留、本任务临时目录已删除、
  构建锁已释放、`git status` 干净；capability 仍为 `linux_cuda_built_model_unvalidated`，
  `model_backed_validation: not_run`，无新增资格成功 evidence，正式 baseline 不存在。
- 未运行：第二次 census、任何 generation、qualification launcher、Cargo、Docker、云 API、全量 eval。
