# Plan 044 / Multi M-5 阶段 A 门 1 整改复验

日期：2026-08-17 ｜ 审查对象：`worktree-044-multi-m5-real-workflow-and-nondegradation` @ `25d801e`
｜ 上一轮报告：`agent_log/2026-08-17-210000-plan044-m5-phase-a-independent-acceptance.md`
｜ 审查者：独立审查会话（未参与实现）

## 结论

**复验不通过。** 上一轮的 P1-1、P1-2 与三项 P2 建议都已真正落地并经本轮实测确认，整改质量高于建议本身
（成员模型那条比我提的更彻底）。但门 1 判据仍有一处**同类**缺陷：证据采集不绑定工具身份，
**模型不调用任何团队工具、只用 `exec_command` 回显一段伪造 JSON，门 1 就能通过**。

缺陷是窄的，修法明确，且完全离线。在它修好之前，"已具备真实运行条件"仍不成立。

## 上一轮问题的复验结果（全部通过）

- **P1-1 同 Event 合取**：用上一轮**原样**的反例（Root 在 e1 独角、成员 Version 挂在无关 e2）重跑
  `evaluate_collaboration` → `passed=False`，四项谓词失败。已真修。
- 分组正确性追到 Rust：`TeamStore::dump_entries` 的真实发射顺序是
  Participants → 每个 Event{Event, Version+其 VersionFact, Routes} → Facts → Visibility/Activity → Publication，
  与判据的文档序分组逐段吻合；`DumpEntry::Version` 确实**没有** `event_id` 字段，所以按顺序分组是唯一可行解，
  执行者偏离我建议的理由成立。`#[serde(tag="entry", rename_all="snake_case")]`、
  `ParticipantRole`/`RootState` 的 snake_case、`AgentPath::ROOT = "/root"` 全部与判据假设一致。
- **P1-2 root_woken**：与 `WakeDecisionView`（`{"decision":"signalled","target":"/root",...}`）逐字段吻合；
  `wait_agent` 的 TeamActivity 原文与 `multi_agents_v2/wait.rs:156` **逐字相同**，
  mailbox 的 `Wait completed.` 不会误命中。
- **P2-3 成员模型**：查证 `expose_spawn_agent_model_overrides` 的配置默认是 **true**，
  所以设成 false 是真正生效的收紧（把 `model`/`reasoning_effort` 从 spawn schema 摘掉），比我建议的"只补默认值"更钉死。
  `agents.default_subagent_model`（`AgentsToml`）与该 feature 键都确实存在。
- **P2-4 归因边界**：已写入不退化锁，含"不要预跑诊断"的规则，与上一轮 D4 一致。
- **P2-5 证据来源**：改为 harness 捕获的 Responses `function_call_output`；采集器对
  `action`/`entries`、dump 续页必须带 `cursor`、log 用 `offset` 的假设与 `inspect.rs` 完全一致
  （dump 返回 `next_cursor`、log 返回 `next_offset`，采集器没有混用）。

## 并发 / 生命周期专项（本轮重点核查，结论正面）

- **跨快照拼页**：`observe.rs` 的 dump 续页会校验 `instance`、`revision`、`availability_epoch`、
  `observe_generation` 四项，任一不符即 `DumpCursorStale` / `InstanceReset`，且无 cursor 的裸 offset 直接拒绝。
  因此采集器"带 cursor 就拼接、不带 cursor 就替换"在运行中发生 mutation 时**不可能**把两个快照的页拼在一起 ——
  最坏是续页报错、证据截断，属 fail-closed。
- **取样时序**：dump 在协议收尾后由模型发起，谓词不依赖 producer 可用性字段，成员此时是否已卸载不影响判定。
- **log 分页重复**：唤醒判定只看"存在一条 signalled"，跨页重复不影响结论。

## 新发现

### P1-3 门 1 证据采集不绑定工具身份，可被回显伪造（必须修）

`eval/rondo_eval/multi_m5/collect.py:103`：

```python
if name in _INSPECT_NAMES or action in {"dump", "log"}:
```

`or` 之后的分支使**任何**工具的输出，只要负载里带 `action: "dump"`，就被当成 team_inspect 的 dump 采纳。
`action` 还会从负载自身回填（`collect.py:101`），所以工具名可以完全无关。

实测（本轮构造并运行）：一段 JSONL 里只有 `exec_command` 的调用与输出，输出正文是
`{"action":"dump","entries":[...伪造的参与者/Event/Version/route/version_fact...]}`，
外加一条同样由 `exec_command` 回显的 TeamActivity 原文 —— `evaluate_collaboration` 返回
**`passed=True`、`reasons=()`**。全程没有一次真实团队工具调用。

这与模块自己的 docstring（"caller dump cannot leak a fabricated collaboration in"）和锁里
`evidence_source.required_tools: ["team_inspect","wait_agent"]` 直接矛盾：要求写了，判据没执行。
加重情节是新版指令模板第 7 步明确告诉模型"调用 team_inspect 的 dump 和 log，**harness 读这些工具输出**" ——
等于把判据的取食口径告诉了被测对象；一个完不成协议但想让 run 过的模型，回显一段 JSON 就够了。

`_record_wait_signal` 有同样的口子：TeamActivity 原文来自任何工具输出、甚至任意文本都算数。

修法（窄）：dump/log 只认 `name in _INSPECT_NAMES` 的输出，去掉 `or action in {...}` 兜底；
唤醒信号只认 `wait_agent` 的输出；可再要求 dump 负载带 harness 才有的信封字段
（`revision` / `total_entries` / `instance`），裸 echo 拿不出来。并把上面这个伪造用例固化为回归。

### P3 其它（不阻塞）

- 指令模板没让模型跟进 `next_cursor`。`MAX_OBSERVE_LIMIT = 50`，门 1 的小团队约 15–25 行，通常一页装得下；
  但会话稍长就会截断成假阴性，白烧一次付费尝试。指令里加一句"跟进 next_cursor 直到取完"即可。
- `max_members=1` 数的是该实例注册过的全部非 root 参与者。成员因瞬时故障被重新 spawn 会变成 2 个，
  判失败。三次尝试上限能兜住，属操作性代价，不改合同。
- 整改日志没列"改了 override 字符串之后重跑 loopback"。本轮由审查者补跑
  `just eval-multi-m5-loopback`：冻结二进制在 `--strict-config` 下接受新串，
  `team_inspect`/`wait_agent`/`spawn_agent` 等全部注册，round-trip true。属记录疏漏，不是缺陷。
- 既有缺陷未变：`just eval-test` 仍加载不了 `tests.test_l6_b10333_pair`、`tests.test_local_m4_holdout_anchor`
  （干净 `main` 同样复现，属 Local 侧，仍建议单开窄修）。

## 回归检查

- 完整离线 Python：**851 项，849 通过**，2 项 error 即上述既有 Local 加载失败。相对上一轮（841 项）
  新增 10 项测试，无新增失败，局部修复没有引发全局回归。
- `just eval-multi-m5-loopback`：通过（见上）。
- 未跑 Rust（`multidev/` 本轮零改动）、未跑 Docker、未跑真实 API、未产生任何费用。
- 主工作区仍为 `main@45efac6` 且干净；044 分支未合并、未推送。

## 替用户做出的决策

| # | 事项 | 决策 | 理由 |
|---|---|---|---|
| E1 | 是否放开真实付费 | **不放开**。P1-3 修好并复验通过前，不得进行任何真实 API、付费调用或 Docker 拉取/运行 | 用户本轮明确要求付费须另行授权；且判据可被伪造时，付费换回的结论不成立 |
| E2 | 阶段 B 能做什么 | 允许**纯离线前置准备**：门 1 runner 与门 2 轻量交错执行面的代码、预算记账接线、用 loopback/stub 做无 API 演练与测试 | 这些不花钱、不碰外部状态，且是阶段 B 真正开跑前必须先有的东西 |
| E3 | 上一轮 D2 的冻结值（provider、双侧模型、超时、轮次、运行上限、$120 硬上限、十个镜像、外发边界、只提交不合并） | **维持批准，不再重议** | 本轮未改动这些值，逐项复核仍成立 |
| E4 | `next_cursor` 分页 | 指令模板补一句要求跟进分页 | 一行成本，避免白烧一次付费尝试 |
| E5 | `max_members=1` 与成员重生 | 维持不放宽，靠 `max_attempts=3` 兜底 | 指令已把"只准一个成员"定为硬规则，放宽会让判据再次变松 |
| E6 | 伪造用例是否入回归 | **必须入**，与 P1-3 的修一起提交 | 门 1 已连续两轮栽在"判据接受非证据"，需要固化防线 |

## 验收判定

- **做得对不对**：不通过。上一轮两处 P1 已真修且经实测确认，但证据采集存在可实证的伪造路径（P1-3）。
- **是否实现预期**：未完成。门 1 在"模型一次团队工具都不调用"的情况下仍可通过，
  "已具备真实运行条件"这一表述在 P1-3 修好前不成立。
- 执行者对整改范围与未跑项的自述属实，文档已如实下调为"独立验收不通过、待复验"，没有拔高。
