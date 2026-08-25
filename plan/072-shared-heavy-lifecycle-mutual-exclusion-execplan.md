# Plan 072：共享重型任务启动前冲突观察门 ExecPlan

> 本计划是 Plan 072 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；范围内普通实现、fixture 和测试问题可以自主修复并有界重跑。
> 本计划只描述 Plan 072；跨任务路线、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

把 Plan 058 / Plan 054 历史碰撞后由 Agent 人工执行的启动前确认，固化为 canonical shared wrapper 内的轻量机械门禁：

1. wrapper 先取得 canonical flock；
2. 在真正 payload 启动前，只读观察是否仍有其它 active/populated 的 RONDO heavy scope；
3. 若出现“flock 已可取得，但旧重型 scope 仍活着”的矛盾事实，立即 fail-closed，不让 Cargo、模型、Docker 或其它 payload 开始；
4. 旧 scope 消失后，后续 wrapper 可按现有流程正常启动。

这是共享锁的第二个观察角度，用于把历史上已经实际采用的人工错峰检查前移到启动资格门。它不负责调度、等待、接管或清理旧任务，也不扩展为一般生命周期治理。

任务结束形成以下一种诚实结论：

- `EXISTING_EQUIVALENT_GUARD`：当前已有等强启动前观察门，只补必要回归和结论；
- `STARTUP_GUARD_ADDED`：当前缺少等强门禁，已在 shared wrapper 责任层完成轻量补丁；
- `INCONCLUSIVE_BLOCKED`：宿主环境或可观察事实不足以可靠判断，明确保留阻塞。

### 完成/验收标准

- [ ] 从 live wrapper、watchdog helper 和直接相关历史记录确认当前是否已有等强门禁；不追求历史 PID 的唯一归属，也不扩展调查其它假设问题。
- [ ] canonical wrapper 在取得 flock 后、启动 payload 前完成一次 active RONDO heavy scope 观察；发现矛盾时以稳定非零结果 fail-closed，payload execution marker 不得出现。
- [ ] 观察对象是可验证的当前 RONDO heavy scope/systemd cgroup 活性事实；inactive、failed-but-not-active 或已经 gone 的历史 unit 不得造成永久误报。
- [ ] 门禁无法可靠取得必要 scope/cgroup 事实时 fail-closed，不以“检查失败”等同“没有冲突”。
- [ ] 门禁只观察并拒绝：不等待、不 kill、不清理、不接管旧 scope，不增加 registry、daemon、数据库、GPU lock service 或调度编排。
- [ ] 旧 scope 确认消失后，同一 wrapper 可正常启动 harmless payload，证明门禁不会把一次历史冲突变成永久阻塞。
- [ ] 保留现有 canonical flock、cgroup watchdog、runtime lease、运行期外部 Cargo 检测、资源阈值和 scope cleanup 语义；不修改模型、Docker、Cargo 任务自身实现。
- [ ] 后续 Plan 071 从 WBS 得知继续复用 canonical wrapper，并由启动前观察门机械替代额外人工确认；Plan 072 不修改 071 分支或规定其运行组织。
- [ ] 只运行 shell/Python/fake/短时 model-free 聚焦验证；未运行 Cargo、Docker、真实模型、GPU、API、测评或全量测试。
- [ ] 独立审查确认补丁确实在 payload 前阻止历史型矛盾、没有扩大成调度设施，任务 worktree 已本地提交并保持 clean。

## 2. 当前依据与任务边界

### 当前依据

- 历史日志确认：Plan 054 模型生命周期内检测到外部 Cargo，Plan 058 一侧却通过 canonical wrapper/lock/watchdog 完成；材料不足以证明历史唯一根因。
- 事故后的实际止损是：除取得 lock 外，再由 Agent 人工确认前一模型任务已经终态、资源已释放，然后才重建。该人工检查有效，但没有成为 wrapper 启动资格的一部分。
- 当前 wrapper 已有 canonical flock、启动前 Cargo 进程检查、systemd scope、持续 watchdog 和 scope 残留清理；只读调查尚未看到 flock 取得后对既存 active RONDO heavy scope 的一致性检查。
- runtime lease 能让模型在 wrapper/lock/watchdog 事实丢失后 fail-closed，但这是任务已启动后的自保，不替代 contender 的启动前拒绝。

### 允许修改

- `scripts/with-build-lock.sh`；职责更合适时可窄改 `scripts/build-watchdog-lib.sh`。
- 与上述门禁直接对应的一处轻量测试及最小 task-owned helper/fixture，优先放入现有 `eval/tests/` 或更契合的现有测试位置。
- 本计划的“当前状态”和“关键决策记录”。
- 完成后精炼更新 `doc/development-environment.md`、必要的 `doc/WBS.md` / 相关子 WBS、一份 Plan 072 `agent_log/`；完成型结论可向 `doc/WBS-COMPLETED.md` 追加一条。
- worktree 内 git-ignored 的 Plan 072 watchdog metrics，以及 `/tmp` 下自动清理的 model-free fixture。

### 不允许修改

- `eval/rondo_eval/runtime_bridge.py`、模型 runner、Docker supervisor、Cargo/Just 任务入口和 `mydev/` / `multidev/` 产品代码；若执行证据意外表明 shared wrapper 无法承担该门禁，应停止并请求调整范围，而不是向下游复制检查。
- 069、071 或其它 worktree/分支及其 tracked/ignored 内容；不得向这些分支注入、复制或 cherry-pick 本任务补丁。
- 历史 plan/log/audit snapshot、冻结结果、模型权重/adapter、训练或测评资产。
- `.env.local`、`rondo.local.toml`、宿主机配置、systemd 服务配置、全局工具链、Docker 对象和项目外文件。
- CI、PR、远端资源、发布、上传、付费、合并、推送、rebase、worktree 删除或分支重命名。

### 不允许读取/查看

- `.env.local` 内容、密钥/凭据、模型权重正文、私有测评正文和其它 worktree 的未提交文件内容。

## 3. 硬约束

1. 实际编辑只在 `.claude/worktrees/072-shared-heavy-lifecycle` 的 `worktree-072-shared-heavy-lifecycle` 分支进行；结束时只提交本分支，不合并、不推送。
2. 补丁只处理已观察过的历史型矛盾：**canonical flock 可取得，但旧 RONDO heavy scope 仍 active/populated**。不借本任务全面审计其它资源竞争或生命周期问题。
3. 检查发生在 flock 成功后、任何 payload/systemd-run 启动前。冲突或观察失败都必须在 payload marker 前返回非零；不得先启动再依赖模型侧 fail-closed。
4. 只把可验证的 RONDO heavy scope/cgroup 当前活性作为新增事实源；不泛扫 `python`、`docker`、模型名或 GPU 进程，不读取任务专用结果文件来推断终态。
5. 新门禁只观察和拒绝，不自动等待、重试、kill、reset、清理或接管已存在 unit；旧任务如何结束仍由其 owner 和现有 watchdog 负责。
6. 若当前已有等强行为，只补能防止回归的最小测试，不制造生产代码差异。若缺口可复现，修复集中在 shared wrapper/helper，不在各任务入口重复实现。
7. 动态验证只使用明确命名、task-owned、model-free 的 transient scope、短时 Python/shell helper 和 marker；不得调用 Cargo、Docker、模型、GPU、API 或测评。
8. 创建 fixture 前先确认 canonical flock 可取得且没有未知 active RONDO heavy scope；任一基线不干净就 defer/阻塞，不创建 fixture、不清理现场，避免把等锁或他人 scope 拒绝误判为本门禁生效。
9. 测试 teardown 只处理本测试创建并精确识别的 PID/unit/path；不得清理来源不明的 scope、lock、进程、缓存或 worktree。无法确认 task ownership 时立即停止。
10. 普通 shell、fixture、同步、断言或环境适配问题可以自主修复和重跑。只有需要越过原则边界、接触真实重型资源或无法可靠观察 scope 事实时才报告阻塞。
11. 本任务预计无需在主工作区直接创建 git-ignored 资产。可只读使用项目已有 Python venv并绑定 worktree 源码；若确实必须在主工作区写入新的 task-owned ignored fixture，先单独报告准确路径、原因和保留/清理方式。

## 4. 软性建议

以下是实现建议，不是固定路线；执行者可依据 live systemd/cgroup 行为选择更干净的等强方案。

- 优先把观察逻辑做成 wrapper 或现有 watchdog helper 内的短函数，复用当前 unit 命名和 cgroup 活性语义，不增加 Python 生产模块或持久状态。
- 只把真实 active/populated 的 `rondo-build-*.scope` 视为冲突；如何安全列举、核对和处理 unit 在检查过程中的消失竞态，由执行者根据 systemd 当前行为选择。
- 最小 model-free 回归可直接创建一个精确命名的 task-owned active RONDO scope而不持有 flock，模拟历史上的 lock/scope 矛盾；随后启动 canonical wrapper contender，断言其 payload marker 未出现。
- fixture 自己结束/精确清理该 scope 后，再运行一次 contender 并断言 marker 出现。无需构造真实模型、Cargo、Docker，也无需覆盖完整信号和子进程清理矩阵。
- 若对 systemd 的生产级进程测试不适合进入默认单测，可保留一个轻量 pure test 加一个明确的短时 model-free 验证入口；不要建立新的测试平台。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 从 clean 本地 `main@d941d0a0df7687cc0d546de2012ba1d5db58b10b` 创建专用 worktree/分支。
- 已阅读根规则、README、当前 WBS、模板、三份原始问题报告和当前 wrapper/watchdog/lease/model service 相关实现与测试。
- 只读结论是：历史碰撞和人工错峰事实成立，历史唯一根因未知；现有 tracked wrapper 没有等强的 active heavy scope 启动前一致性检查。
- 用户进一步收窄任务：只把上述人工启动前确认固化到 shared wrapper，不做全面生命周期验证或调度设施。
- 在 helper 增加 canonical scope 枚举、systemd state/ControlGroup 与 `cgroup.events populated` 核对；wrapper 在 flock 成功后、
  两条 payload 路径前调用，冲突或 unknown 稳定返回 `84`，不改变旧 scope。
- 初次动态基线发现 069 的 active heavy scope 后保留现场并 defer；用户报告资源释放后，主执行者在同一 FD 持锁期间确认
  lock 可取得且 active scope 为 0，才创建第一套 072 fixture。
- 独立审查发现 inactive/failed + 非空 populated cgroup 被过早 clear；已收紧为必须读取 cgroup 事实并增加回归。
- 调试链完整打通后冻结候选；最终从 clean `c517896924977fe6f044fdc514edc83586294884` 创建全新 fixture，正式聚焦
  7/7 通过（4.414 秒），既有 helper 9/9、`bash -n` 与 diff 门通过。正式轮后 HEAD 不变、worktree clean，
  无 active RONDO scope 或 Plan 072 临时目录残留。
- 最终独立复审结论为 `ACCEPT`、`remaining_findings=[]`；没有主工作区 ignored 写入，也没有运行或接触禁止项。

### 当前工作

- 任务完成；本计划随最终文档提交冻结，后续路线只见 WBS。

### 本任务剩余步骤

- 无。执行者完成本地最终提交与 clean/隔离复核后停止，等待用户决定是否合并。

### 阻塞项

- 当前无阻塞。

### 当前验收状态

- `STARTUP_GUARD_ADDED` / `PASS`：clean-HEAD 正式聚焦 7/7，独立复审 `ACCEPT`、`remaining_findings=[]`。

### 交接边界

- Plan 072 完成后冻结本计划；Plan 071 只从 WBS 消费“使用 canonical wrapper 及其启动前门禁”的当前事实，自主决定自身运行组织。
- 执行者完成本地提交与 clean 检查后停止；不得合并、推送、rebase、删除 worktree或重命名分支。

## 6. 验证与完成门禁

### 静态与 pure/focused

- `bash -n` 检查实际修改的 shell；`git diff --check`；新增文件体积/权限和主工作区、069、071、072 worktree 状态复核。
- 只运行新增观察函数/解析逻辑及直接受影响 wrapper 行为所需的最小测试；不扩大到整个 eval suite 或 Rust workspace。
- Python 命令绑定 worktree `eval/` 源码，必要 cache 指向 task-owned 临时目录；不在线安装依赖。

### model-free 正反例

1. 在创建 fixture 前确认 canonical flock 可取得、没有未知 active RONDO heavy scope；基线不干净则停止本轮，不触碰现场。
2. 以精确 task identity 创建 active RONDO heavy scope，确认 canonical flock 未被该 fixture 持有。
3. 启动 contender wrapper；确认它在 payload 前稳定失败，contender marker 不存在，既有 scope 未被 contender 修改或清理。
4. 由 test harness 精确结束自己创建的 scope并确认其 gone。
5. 以全新 marker 再启动 contender；确认 harmless payload 正常执行且 wrapper 正常收口。
6. 整个场景有短时 deadline；任一 scope/PID/path ownership 或 cleanup 无法确认时测试失败并停止，不继续制造新 fixture。

### 正式聚焦验收与独立审查

- 调试打通后提交候选，从 clean committed HEAD 和全新 task-owned fixture 完整运行一次上述适用门禁，记录精确命令、结果、耗时、HEAD 和明确未运行项。
- 独立审查重点只看：检查是否位于 payload 前、历史型 lock/scope 矛盾是否被拒绝、无冲突时能否正常启动、是否误清理旧任务或扩建调度设施。
- `INCONCLUSIVE_BLOCKED` 只要求审查确认局部证据和阻塞判断诚实；完成型结论要求 `remaining_findings=[]`。

## 7. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 不追求历史唯一根因，只机械阻止已观察到的 lock/scope 矛盾在 payload 前重现 | 用户要固化事故后的人工启动前确认，而不是全面生命周期审计 | 目标、结论 | 已采纳 |
| 002 | 新事实源只采用 active/populated RONDO heavy scope，不扫描通用模型/Docker/Python 进程 | scope 与现有 canonical wrapper/watchdog 架构契合，噪声小且无需 registry | wrapper、测试 | 已采纳 |
| 003 | 门禁只观察并拒绝，不等待、清理、接管或调度旧任务 | 保持补丁轻量，旧任务生命周期继续由原 owner/watchdog 负责 | 行为、安全 | 已采纳 |
| 004 | 用一个 model-free 矛盾 fixture 加清除后的正常正例验收，不建设完整异常退出矩阵 | 精确覆盖历史问题，同时避免把任务扩大为一般生命周期平台 | 测试 | 已采纳 |
| 005 | Plan 071 只通过 WBS 消费 canonical wrapper 当前事实，不触碰其分支或冻结其执行策略 | 保持并行隔离与规划唯一来源 | Git、交接 | 已采纳 |
| 006 | systemd 只发现 canonical unit/复核消失竞态，当前存活以 ControlGroup 的 `populated` 为准 | inactive/failed 不保证非空 cgroup 已无人；unknown 必须拒绝 | helper、错误语义 | 已采纳 |
| 007 | 正式 fixture 持锁完成自身 identity/population 核对后才释放 lock 制造矛盾，teardown 只处理 exact owner | 避免把真实竞争、未知 scope 或清理副作用误算为门禁证据 | 测试、安全 | 已采纳 |
