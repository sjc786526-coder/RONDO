# Plan 062：方向 1 教师源码热路径优化与轻量测评 ExecPlan

> 本计划是 Plan 062 的稳定任务合同。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认；普通编译、测试、benchmark、fixture、
> 局部兼容和格式问题应在授权范围内自主诊断、窄修并重跑。
> 本计划只描述 Plan 062；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。
>
> 只有执行者收到用户明确引用本计划、并包含 §2—§3 所列源码修改、普通只读网络/源码查询、项目内依赖处理、
> 受控重型 Cargo、定向测试、轻量测评、任务自建临时对象清理和工作树提交授权的一次性提示词后，才可进入实施。
> 最终只提交 `worktree-062-teacher-hotpath-optimizations`；合并、推送和分支归档等待用户另行批准。

## 1. 目标

### 最终目标

1. 保持 RONDO 当前 Codex CLI `v0.147.0` 基线身份和所有模型可见语义不变，学习教师源码中已经筛选出的三个
   行为保持型热路径机制，并按 RONDO 当前数据结构与架构自主实现：
   - 历史 orphan output 归一化由多轮 owning scan 收敛为借用式单轮索引收集、单轮 orphan 定位，并且只在确有
     orphan 时修改向量；
   - 模型可见工具规格构建一次后由不可变共享所有权跨 prompt 复用，避免每轮深拷贝完整工具规格；
   - unified-exec 输出快照直接形成连续字节，并在 sandbox denial 检查中尽量借用 UTF-8 视图，避免多层中间复制。
2. 三项变化都不得改变 history 顺序、synthetic output、工具注册/暴露顺序、请求 JSON、tool schema、输出截断、
   omission marker、sandbox 判定、错误文本、审批、Guardian、取消、恢复或工具执行资格。
3. 为本任务建立一条专用、默认不运行、无真实 API 的轻量测评入口；职责契合时复用现有 mock Responses、
   `codex-core` 测试支持、Divan、`just` 和结果归档方式。测评至少输出 wall time 与 allocation/allocated bytes 中
   可稳定取得的指标，并绑定 baseline/candidate 源码身份、workload 参数和运行环境。
4. 先在调试态逐项实现、修复并打通定向正确性与测评 workload；全部路径至少成功一次后再冻结代码、配置和
   workload，从 clean commit 完整运行一轮定向门禁与轻量测评，以该轮作为本任务正式结果。
5. 本任务只判断这三项优化是否正确落地、是否减少确定性工作量以及是否出现明显性能退化；不运行真实 API、
   Terminal-Bench、Docker 或冻结 Codex 对照，也不把微观 CPU/分配变化表述为任务成功率提升。

### 完成/验收标准

- [ ] orphan output 归一化使用借用 call ID，FunctionCall 与 LocalShellCall 的输出匹配语义保持一致；client-side
      ToolSearchOutput、server-side ToolSearchOutput、缺 call ID、CustomToolCallOutput 与 debug/release
      `error_or_panic` 行为均由回归覆盖。
- [ ] 无 orphan 的常见路径不执行第二次全量 `retain`/重写；存在一个或多个 orphan 时只删除准确位置，其他 item
      的字节内容与相对顺序保持不变。existing synthetic output、image/audio strip 与 history normalization 顺序不变。
- [ ] `ToolRouter` 与 `Prompt` 对模型可见工具规格采用不可变共享所有权；构建边界只发生一次 `Vec`→共享 slice
      转换，常规 turn、remote compact 与 remote compact v2 均复用同一规格，不为 benchmark 扩大公共 API。
- [ ] 请求序列化对普通 Responses、Responses Lite 和 WebSocket 的工具 JSON、顺序和字段保持一致；tool search、
      hosted tool、MCP/deferred tool、CodeModeOnly、parallel-tool-call 能力及工具执行 registry 不发生语义变化。
- [ ] unified-exec snapshot 在锁内最多构造一份连续 retained bytes；合法 UTF-8 路径不再无条件复制成 owned String。
      head/tail cap、omitted byte 计数、omission marker、空输出、非 UTF-8、超限输出和 sandbox-denial diagnostics 保持。
- [ ] 三项产品变化都有直接的定向正确性回归；优先补充已有 test module，不建立重复测试套件，也不增加只为测试
      存在的通用产品 API。
- [ ] 新轻量测评入口一条命令即可运行并自动记录 baseline/candidate、workload、迭代/采样参数、wall time 与可取得的
      allocation 指标；原始 benchmark 输出留在 Plan 062 ignored namespace，tracked 结果只保存 body-free 聚合。
- [ ] workload 至少包含：逐步增长的多轮工具 history、非空工具规格重复构造，以及小/中/接近上限的 unified-exec
      输出；不得通过复制一份“旧算法”到长期代码中伪造 A/B。baseline 与 candidate 使用同一 benchmark 实现和参数。
- [ ] 正式测评不预设必须达到统计显著或固定百分比；每项至少有源码结构事实证明对应复制/扫描被消除，candidate
      不得在对应 allocation 指标上出现无法解释的材料退化。wall time 作为辅助指标，噪声或无显著差异如实报告。
- [ ] 关闭任何与本任务无关的变量；模型可见请求、工具结果、CLI/config/app-server API、rollout 持久格式和默认功能
      保持行为等价。若三项不能在上述边界内干净实现，宁可缩小或撤销对应项，不夹带架构升级。
- [ ] 调试阶段允许保留已验证进度，针对未打通 case 自主窄修和重跑；最终代码/workload 冻结后，从 clean commit
      完整运行一次 benchmark smoke、定向测试、`codex-core` crate 门禁与正式轻量测评，不拼接调试轮结果。
- [ ] 所有 Rust 构建、测试和 benchmark 都通过仓库共享 build lock/watchdog；拿不到锁、cgroup、Windows `C:`
      实际余量或资源计数器时 fail-closed。未运行全 workspace、Docker、真实 API、本地模型、CI 或 PR。
- [ ] 完成一次由本计划审查者执行的聚焦独立验收。执行者只把实现提交为 worktree commit 并标记“等待审查”；
      普通 finding 后续可在同一授权范围内窄修复验，原则性范围变化必须重新询问用户。
- [ ] 只同步本计划当前状态、方向 1 WBS、必要的 body-free 测评结果与一份精炼 agent log；不改 README，不堆叠
      多份历史。最终 worktree clean，不合并、不推送、不重命名或归档分支。

## 2. 范围

### 允许修改

- `mydev/codex-rs/core/src/context_manager/` 中 orphan output 归一化及现有对应测试。
- `mydev/codex-rs/core/src/tools/`、`client_common.rs`、常规 turn 与 remote compact 构造点、请求序列化适配及
  对应定向测试中，与不可变工具规格共享直接相关的窄改。
- `mydev/codex-rs/core/src/unified_exec/` 中输出 snapshot/连续字节视图及现有对应测试。
- 为 Plan 062 轻量测评所必需的 `codex-core` benchmark target、`Cargo.toml` dev dependency/bench 声明、
  `mydev/justfile` 专用入口；若职责更适合共享 `eval/`，可在 `eval/rondo_eval/`、`eval/tests/` 和
  `eval/results/observations/` 新建一个职责明确的 Plan 062 runner/schema/result，但不得复制第二套通用测评平台。
- `plan/062-direction1-teacher-hotpath-optimizations-execplan.md` 的当前状态和关键决策、
  `doc/WBS/teacher-harness-study.md`、必要的顶层 `doc/WBS.md` 当前指针、一份精炼 Plan 062 `agent_log`。
- worktree 内 task-owned、git-ignored 的 Cargo target、`.codex/build-watchdog/`、benchmark raw/tmp 目录；普通依赖
  下载、只读源码查询和 `/tmp/rondo-plan062-*` 临时源码/patch scratch。任务结束只清理能精确确认由 Plan 062
  创建且不再需要的临时对象。

### 允许只读核对

- 根/`mydev/` 规则、README、当前 WBS、Plan 052/056/058、相关完成记录/日志、tracked 源码/测试、Git 历史、
  `codex-doc/`、`codex-source-code/` 与教师源码中仅和三项机制直接相关的部分。
- 主工作区和其他 worktree 的 Git/资源状态，只用于保护并行任务、确认共享构建槽和避免覆盖；不读取其他
  worktree 的未提交正文。
- 普通公开源码和依赖文档的只读网络查询；只允许下载到本任务明确的项目缓存或 `/tmp/rondo-plan062-*`，不得
  发布、上传、修改远端状态或引入另一套产品源码。

### 不允许修改

- RONDO 的 `v0.147.0` 基线身份、`upstream-source-baseline.toml`、冻结 `codex-source-code/`、模型 catalog、
  Guardian、审批、sandbox、安全策略、C2 guidance、方向 2/3、`multidev/`、Publication Critic 或训练资产。
- 工具模型可见内容、工具选择/执行资格、history/rollout 持久协议、CLI/config/app-server 对外接口，以及与三项
  热路径无关的 TUI、MCP、日志数据库、并行工具调用、skills、plugin、memory 或 Guardian 优化。
- Plan 052/056/058 的历史 campaign、lock、trace、结果、费用和 ignored 私有资产；不得恢复 E-A、创建新的
  Terminal-Bench campaign，或把旧正式数据重解释为 Plan 062 性能证据。
- 主工作区 tracked/ignored 文件。按当前架构，Plan 062 的源码、target、watchdog 与 benchmark 工件均可留在
  062 worktree 或任务 `/tmp`；若执行时发现工具硬性要求写 Git common root，先停止并向用户单独报告具体路径、
  原因、数据类型、体积和清理方式，未获批准前不得直写。
- Docker、真实 API、真实本地模型、训练、云任务、付费资源、数据外发、完整 Terminal-Bench、全 workspace 测试、
  CI、PR、合并、推送、分支重命名/归档、全局工具链/宿主配置修改或项目外持久文件。
- 第二套 trace/telemetry、数据库、常驻服务、签名链、隐私/可信审计、复杂鉴权、严格因果平台，或为了取得漂亮
  benchmark 数字而增加的生产 instrumentation。

### 不允许读取/查看

- `.env.local` 内容；本任务不需要任何密钥，连变量存在性检查也不是必要步骤。
- validation/holdout 题目正文、solution、verifier、逐题结果，Plan 052/056/058 或方向 3 的 ignored 私有工件，
  其他 worktree 的未提交文件。
- 项目外个人文件、其他仓库、密钥、凭据、私有数据和与 Plan 062 无关的 ignored 内容。

## 3. 硬约束

以下约束具有强制性。它们冻结行为、资源、测评和交付边界，但不固定局部类型名、文件拆分或 benchmark 实现细节。

1. **自主实现，不改变产品身份。** 三项机制来自教师源码的学习和筛选，必须结合当前 RONDO 类型、调用链和测试
   自主实现；保持 `v0.147.0` 基线身份，不导入成组的无关功能、配置、依赖或架构变化。产品文档、提交说明、
   日志和对用户汇报统一表述为“学习教师源码后筛选并自主实现的优化”。
2. **行为等价优先于微观收益。** history、tool specs 与 exec output 的模型可见字节、顺序、边界和错误语义必须
   保持。任何 correctness、sandbox-denial、resume/compact、请求序列化或工具暴露退化都要求修复或撤销对应优化；
   不能以 benchmark 改善换取语义变化。
3. **三个变量分别可审查。** orphan normalization、tool specs ownership、unified-exec snapshot 各自形成清楚的
   小 diff、测试与测评映射。允许同一任务内集成，但不得把无关重构、格式 churn 或其他候选夹带进来；单项出现
   原则问题时可以撤销该项并诚实完成其余项，不为凑足数量扭曲架构。
4. **测评不侵入生产路径。** 优先使用现有 `core_test_support`、mock Responses、Divan 和 `just` 入口构造
   deterministic workload。不得为了访问 private internals 而扩大稳定公共 API、引入常驻计数器或改变默认产品
   行为；若 end-to-end workload 已能形成相称证据，就不额外建设逐函数探针。
5. **baseline/candidate 同口径。** 先完成行为中性的 benchmark scaffold 并使 smoke 通过，再在未实现三项优化的
   clean commit 上记录 baseline；随后实现三项优化。两侧必须使用同一 benchmark 源码、fixture、参数、release
   profile、机器资源边界和记录器。不得在看到 candidate 后修改 workload 来放大收益；确需修 benchmark 时旧两侧
   一并作废并从新 clean scaffold 重测。
6. **指标解释有界。** tracked 结果至少绑定 benchmark/schema 版本、baseline/candidate commit、dirty=false、
   case 参数、采样数、wall time 与可取得的 allocation/bytes 指标。只对同一机制对应 workload 解释微观变化；
   不外推任务成功率、API 延迟、模型质量或通用 agent 性能。测不到显著 wall-time 改善不是失败，明显且不可解释的
   allocation 或时间退化则必须调查、修复或撤销对应项。
7. **先调试打通，再 clean 正式轮。** 调试阶段从最小 case 开始，保留已通过的构建产物与结果，只重跑未打通或
   受修复影响的 case；普通编译、fixture、benchmark parser、格式和窄兼容问题由执行者自主修复。所有目标路径至少
   成功一次后运行格式化，冻结代码/config/workload，提交 clean candidate；然后从该 clean commit 完整运行一次
   benchmark smoke、定向 correctness、`just test -p codex-core` 与正式轻量 benchmark。该轮失败时只窄修真实问题，
   重新冻结后整轮重跑；调试轮不能拼入正式结果。
8. **重型 Cargo 全局串行。** `just test`、`just bench`、必要 `just fix` 和其他重型 Cargo 必须使用根共享
   `scripts/with-build-lock.sh`/watchdog 接入，遵守 jobs/test-threads/rustc throttle；不得直接 Cargo 或关闭
   lock/watchdog。开始前确认没有其他 worktree 构建，并让脚本读取 Windows `C:` 实际余量、cgroup 和所有资源
   计数；exit 72 等待后重试，125/137 按资源终态处理，不杀 PID、不绕过门禁。
9. **验证范围相称。** 调试先跑精确 test filter，再跑 `just test -p codex-core`；benchmark 使用 Plan 062 专用
   smoke/正式入口。运行 `just fmt`，只有实际规模或 lint finding 需要时才运行 scoped `just fix -p codex-core`。
   不运行全 workspace、Bazel、Docker、真实 API、真实模型、CI 或 PR；skip/未运行不得写成通过。
10. **数据和临时对象简单可恢复。** raw benchmark 输出只放 062 worktree ignored namespace，tracked JSON 只保存
    无正文聚合和必要环境身份；不建设签名、journal、数据库或隐私审计。临时教师源码/scratch 只允许
    `/tmp/rondo-plan062-*`，清理前核对精确路径和归属；Cargo target 体积大时不自行删除，除非能证明为 Plan 062
    独占且用户授权范围明确。
11. **普通问题自主收敛，原则边界才停。** 短时锁占用、依赖下载、编译/测试失败、fixture、benchmark 输出解析、
    生成文件和窄兼容问题不构成用户阻塞；执行者应诊断、窄修、等待或有界重跑。需要改变产品语义/基线身份、扩大
    到其他候选、主工作区直写、全量测试、未授权外部状态、禁止资产、项目外持久写、破坏未知修改或资源门不可用时
    必须停止并请求用户。
12. **工作树与审查交付。** 所有 tracked 实现、测试、测评和文档只在 062 worktree；不 stash、回退、覆盖或删除
    未知修改。执行者完成后更新本计划为“实现提交、等待独立审查”，提交工作树并报告 commit/diff/测试/测评/未运行
    项；不得自行宣布最终验收，不合并、不推送、不归档。审查者在用户后续交接后独立验收。

## 4. 软性建议

以下建议基于 `main@60ada10dc6d44c39271f6ec699e599515af3c8df` 的 live code。执行者可依据实际 diff、测试和
测评采用更干净的等价方案，但不得改变 §1—§3。

- orphan normalization 当前位于 `core/src/context_manager/normalize.rs`。可用三个借用 `HashSet<&str>`（函数/
  local shell 共用一组、tool search、custom tool）单次收集 call ID，再单次收集 orphan position；只有 position
  非空时才 `retain`。保留现有 `error_or_panic` 调用时点和消息，不需要引入新状态对象。
- tool specs 当前由 `ToolRouter` 保存 `Vec<ToolSpec>` 并在 `model_visible_specs()` 深拷贝。可在 router 构造边界转成
  `Arc<[ToolSpec]>`，让 `Prompt.tools` 使用同一类型；序列化函数继续消费 slice。优先补 pointer sharing 与请求 JSON
  等价测试，不为此修改 ToolRegistry 或 tool execution ownership。
- unified-exec 当前 `snapshot_chunks()` 后再次聚合并 `to_string()`。可让 snapshot 直接返回一份连续 `Vec<u8>`，
  `String::from_utf8_lossy()` 的 `Cow<str>` 只借用到判定结束；只有既有错误对象确实要求 owned String 时再复制。
  不要顺手改 HeadTailBuffer cap、drain、omission marker 或 process lifecycle。
- benchmark 优先采用 `codex-core` 现有 mock Responses/TestCodex 支持构造两个 end-to-end case：增长的多轮工具
  history（同时覆盖 normalization 与 tool specs）和接近上限输出的 unified exec；Divan allocator profiler 可用时
  同时报告 allocation count/bytes。若一个小型专用 runner 比硬塞进通用 harness 更清楚，可以新建，但入口、错误、
  schema 和归档方式仍应服从现有 eval/just 风格。
- baseline scaffold 可作为一个独立中间 commit，便于在同一 benchmark 代码上测 clean baseline；实现和最终结果可
  再分一至两个清楚提交。提交数量不是验收目标，重点是最终分支历史可审查且 worktree clean。
- 测评结果只需一个小型 JSON 和必要 raw output，不画图、不建长期 dashboard；将来只有积累多个同口径结果时才
  考虑曲线。不要把性能 runner 扩张成新的 Terminal-Bench 或 trace 系统。
- 独立审查聚焦：三项语义等价、共享所有权没有可变别名、history/orphan 边界、sandbox denial/non-UTF8、大输出、
  baseline/candidate 同口径、资源门、主工作区隔离和表述口径。窄 finding 修复后只重跑受影响调试 case，重新冻结
  后再完整跑一次正式轮。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- [x] 规划者已阅读根 `AGENTS.md`、README、当前 WBS、方向 0/1 子 WBS、Plan 052/056/058、
      `doc/eval-data-layout.md`、`doc/development-environment.md` §3.5、`mydev/AGENTS.md` 和计划模板。
- [x] 已确认规划基线为 clean `main@60ada10dc6d44c39271f6ec699e599515af3c8df`，创建
      `.claude/worktrees/062-teacher-hotpath-optimizations` 与分支
      `worktree-062-teacher-hotpath-optimizations`；进入时 060/061 worktree 有不重叠的未提交内容。
- [x] 已核对三项当前实现与直接测试位置；计划不改变模型可见语义，不恢复真实 API/Docker campaign。
- [x] 已确认当前架构不要求主工作区直接写 ignored 资产：target、watchdog、benchmark raw 可留在 062 worktree，
      临时教师源码/scratch 可留在 `/tmp/rondo-plan062-*`。
- [x] benchmark scaffold 已由 `aa4c925`、`52e7302` 建立；解析器补丁后的 clean baseline 为 `d5535fc`，
      clean candidate 为 `22b8766`，两侧 harness SHA-256 均为
      `ef8364c8a225226fa1085355ae447f55b9a0aabb3fab6d2f8f264703c77fd5f2`。
- [x] `782baab` 已提交三项学习教师源码后筛选并自主实现的优化：history orphan 借用式索引、模型可见工具规格
      不可变共享、unified-exec 连续字节快照与合法 UTF-8 借用判定；直接回归覆盖语义等价边界。
- [x] `22b8766` 的 clean 正式轮已完成：benchmark smoke；定向 48/48；release exact 1/1；Python parser
      4/4；`just test -p codex-core` 3332/3332（8 skipped、2 slow）；正式 candidate benchmark 9/9 case。
- [x] body-free 聚合已保存为
      `eval/results/observations/plan062-direction1-teacher-hotpath-optimizations.json`；raw 只留在 062 worktree
      ignored namespace。

### 当前工作

- 实现已提交，等待独立审查。执行者不自行宣布最终 PASS。

### 本任务剩余步骤

1. Plan 062 审查者复核 live diff、语义等价回归、同哈希 baseline/candidate、资源边界和交付记录。
2. 若审查发现普通窄 finding，在同一授权边界内修复、重新冻结并完整重跑正式轮；原则性变化另行授权。
3. finding 关闭后由审查者给出 PASS/需整改；合并、推送和分支归档仍由用户另行决定。

### 阻塞项

- 当前无技术阻塞。

### 当前验收状态

- `implementation_committed / independent_review_pending`。
- 正式结果绑定 candidate `22b8766`；尚未经过 Plan 062 审查者的独立验收，不表述为最终 PASS。
- 未运行全 workspace、Bazel、Docker、Terminal-Bench、真实 API、真实本地模型、训练、云任务、CI 或 PR。

### 主工作区 ignored 资产

- 未写入主工作区 tracked 或 ignored 资产。Git 提交只短暂更新既有 062 worktree common index；未创建项目外
  持久数据。
- 062 worktree 保留受监控 `target/`、`.codex/build-watchdog/`、`.codex/plan062-hotpaths/raw/`、校验过的
  `.codex/rusty-v8/` 依赖工件和格式/测试缓存；未发现 `/tmp/rondo-plan062-*` scratch。

### 交接边界

- 执行者只负责实现、调试、clean 正式轮、任务内记录和提交 062 worktree；最终独立验收由本计划审查者完成。
- 当前交付以 `22b8766` 及其后续结果记录提交为基础；方向 1 是否继续安排其他工作只由届时 WBS 和用户决定，
  不在本计划追加新候选。
- 合并、推送、分支重命名/归档必须由用户在独立验收后另行批准。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Plan 062 只做三项教师源码热路径优化，不恢复方向 1 的开放式候选探索 | 三项均命中当前 core/exec 路径、语义风险低；此前行为候选边际收益已收口 | WBS、产品、测评 | 已采纳 |
| 002 | 保持 `v0.147.0` 基线身份，统一使用“学习教师源码后筛选并自主实现的优化”口径 | 保持 RONDO 自身设计所有权与稳定产品身份 | 表述、实现、文档 | 用户明确要求 |
| 003 | correctness 是硬门，微观性能结果只作同口径局部解释 | 三项主要减少扫描/复制/分配，预期不足以证明任务成功率变化 | 测试、结果 | 已采纳 |
| 004 | 新增一条专用轻量 benchmark，而不恢复 E-A 或扩展正式 Terminal-Bench | 现有 observation 可描述输出规模但不能隔离分配；专用 workload 更相称 | 测评、eval/bench | 已采纳 |
| 005 | 职责契合时复用现有 mock/Divan/just；强行复用扭曲 private API 时可新建窄 runner | 保持架构契合，同时不为复用而扩大产品 API 或建立第二套体系 | benchmark 架构 | 已采纳 |
| 006 | 调试按未打通处边修边跑；全部打通后冻结并从 clean commit 完整跑一轮 | 减少重型编译浪费，同时保证正式结果来自同一干净代码/config/workload | 执行、结果 | 用户明确要求 |
| 007 | 当前无主工作区直写需求；若执行时出现必须的 common-root ignored I/O，先单独授权 | 现有 target/watchdog/raw 均可位于 062 worktree，不能无必要扩大写边界 | 文件、Git | 已采纳 |
| 008 | 执行者只提交 062 worktree并等待本计划审查者验收；合并、推送和归档另批 | 用户保留最终集成决定权 | Git、交付 | 用户明确要求 |
| 009 | benchmark 只通过既有 `test_support` 暴露窄适配器，不扩大生产公共 API | 三个 private 热路径可被确定性测量，同时保持测评不侵入生产调用链 | benchmark、core | 已落实 |
| 010 | Divan 零分配时省略 allocation block，解析器按零记录并补回归；旧两侧结果作废后以同一新哈希重测 | 保持零分配结果可记录，同时遵守 baseline/candidate 同口径 | eval、结果 | 已落实 |
| 011 | 工具规格在 router 构造边界转成 `Arc<[ToolSpec]>` 并贯穿 `Prompt`；exec snapshot 直接形成连续 bytes，denial 判定借用 `Cow<str>` | 在当前 ownership 与错误类型边界内消除深拷贝，不改变请求或错误语义 | core | 已落实 |
| 012 | 只修复正式 crate 门禁暴露的既有窄 fixture：补齐已存在配置字段的 schema snapshot，并以本地 reset server 代替不稳定端口假设 | 让回归在授权网络边界内确定运行，不改变产品语义或基线身份 | 测试 fixture | 已落实 |
