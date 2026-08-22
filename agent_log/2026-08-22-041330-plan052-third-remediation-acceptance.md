# Plan 052 第三轮整改验收

日期：2026-08-22
审查提交：`a6693bfad2a71bff84ae77731b49adbd0c44db72`
结论：**PASS**

## 验收结论

未发现剩余 correctness/functionality 阻断。上一轮 public code-mode `exec` 早期错误可能被误报为
`0 deliveries / measured` 的问题已经关闭：默认命名空间的 public `exec` 在统一 caller-facing 工具边界记录一次
body-free delivery，最终结果具备可靠 render 时附带安全聚合；解析、启动、首次响应错误以及取消或 post-hook
替换后无法可靠描述 render 的结果记录为 delivery + missing。Fatal 不产生模型可见工具结果，因而不虚构 delivery。

该记录点位于工具路由、取消与 post-hook 处理之后，只覆盖 direct-model public custom `exec`；code-mode runtime
内部工具仍使用既有 tool lifecycle，不形成第二份产品侧聚合。trace 未开启时不建立新状态、不计算 render metadata、
不写事件，产品默认行为保持不变。离线 schema-v2 投影对重复 delivery、悬空 code cell、无 initial response 的伪
render 及相关观测冲突失败关闭；旧 code-cell render 只作一致性核对，不能把最终 missing 升级成 measured。

Plan 052 的事实链现为：原生 rollout trace / API metadata / 必要的原生 body-free 事实 -> Local 任务级安全投影 ->
历史普查与比较。重复的 Rust 在线 collector 已删除，没有建设第二套 telemetry、常驻服务或复杂审计设施，符合本任务
“职责不重复、必要能力完整、与现有架构契合”的设计标准。

四问的回答与证据边界一致：v28 中 C2 为 2/24、C1 弱代理为 1/24，但缺少足够影响证据，不能宣称已有“最值得
处理”的行为候选；依据只来自 10 个真实 Local canary 的 30 份 API metadata（311 请求）与 24 份可读 exec JSONL，
6 份集中缺口没有按零处理；下一轮唯一变量是对同一 10 题 x 2 轮开启原生 trace 与安全离线投影，不改产品行为；
其 20/20 完整性、跨轮/跨任务负担门槛及后续单候选有效/无效/回滚判据均已写入权威 WBS。证据不足分支本来就是
Plan 052 的成功终态，因此“不硬选优化项”不是任务失败。

## 定向验证

- `test_harness_observation` + `test_team_lens`：51/51 通过。
- `codex-rollout-trace::code_mode_exec_delivery_records_only_model_call_identity`：1/1 通过，62 项按过滤跳过。
- `codex-core::public_exec_parse_failure_records_one_model_output_delivery`：1/1 通过，3331 项按过滤跳过。
- 两项 Rust 测试均经仓库共享构建锁、cgroup 与资源看门狗运行，最终 `stop=none`；未扩大到 crate 或 workspace 全量。
- `git diff --check` 通过；Plan 052、main、Plan 053、Plan 055 工作树均干净。

首次 Python 命令因 worktree 不携带 ignored `eval/.venv`，第二次因工作目录未落在 `eval/` 而分别在收集阶段失败；
改用主物理根既有项目 venv 并从 worktree 的 `eval/` 运行后通过，不属于代码失败。首次 Rust 尝试在文件沙箱内因无法
访问 cgroup bus 按设计以 81 退出且未启动 Cargo；同一精确命令在宿主资源门禁下通过。

未重跑 Docker、真实 API、本地模型、训练、validation、holdout、完整数据集、宽 Rust、全 workspace、CI 或 PR。

## 代用户作出的决策

1. **接受当前原生事实链设计。** 保留 eval 侧 schema-v2、投影、比较与历史普查；保留为补齐 public `exec` 最终
   交付语义所必需的原生 body-free 事件；不恢复已删除 collector，也不增加额外 telemetry 或审计平台。
2. **接受“证据不足，不选行为优化”的结论。** 当前不能把频率更高的 C2 直接称为最值得处理；教师实现不进入
   发生率或影响结论。
3. **后续唯一工作包仍为 10 题 x 2 轮测量。** 本次验收不授权真实 API、Docker 或 20 USD 支出，也不提前启动该包；
   应按 WBS 另立任务并取得一次明确执行授权。正式边界前普通接线问题可窄修复验，正式数据出现后不得替换 slot、
   补题、补轮或改变 20-run 分母。
4. **Git 交付边界不变。** 本次只提交审查报告到 Plan 052 分支，不合并、不推送、不归档；这些动作等待用户批准。

## 最终状态

- 验收：**通过**（实现正确，未发现功能性阻断或局部修复引入的明显回归）。
- 任务目标：**完成**（观测链、真实历史普查、诚实决策和唯一后续测量包均已落地）。
