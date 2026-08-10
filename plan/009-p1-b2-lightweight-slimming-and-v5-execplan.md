# P1 B2 轻量瘦身与 v5 真实链路 ExecPlan

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

## 1. 目标

### 最终目标

停止为 no-API 基础设施继续叠加审计状态机。修复当前唯一已知的 marker 假成功，删除已经完成使命或重复表达
同一事实的代码、schema 和测试，把 B2 恢复为一个可重复调试、一次命令串行运行两侧的轻量验收入口；随后在
现有安全边界内跑通 RONDO→Codex 的真实 no-API Docker 链路。

本计划只收口 P1/B2。它不重写全部 eval，不推进 B3、M1、L2，也不追求跨机器可信、不可抵赖审计或理论上的
绝对 exactly-once。

### 完成/验收标准

- marker 只在 code-mode `exec_command` 结构化结果满足 `exit_code == 0`，且 stdout 去除末尾换行后**精确等于**
  固定 marker 时通过；失败文本即使回显完整命令也必须拒绝。
- no-API 普通调试与 B2 验收不再使用付费式永久占槽、retirement 表、多版 ledger/schema 或崩溃恢复状态机；
  失败后修复代码可以重新运行，不需要创建 v6/v7 identity。
- paid B3 的预算、不可复用 run、append-only 结果和 publication 恢复继续保留并保持 hard-disabled；不得因精简
  no-API 而弱化未来付费边界。
- 删除一次性三诊断 migration 的生产代码与专用测试；已发布的三条 `infra_failed` 结果、预算账本和历史日志
  保持不变。
- v4 只作为历史 ledger/日志保留；当前运行入口只消费当前冻结输入，不再维护受跟踪 retirement registry。
- Harbor preflight 简化为 tracked `uv.lock` 哈希、`harbor==0.20.0`、冻结 console entry/interpreter 和少量关键
  package identity；不得继续哈希数千个传递依赖文件。
- Docker 有效态只保留一个 canonical runtime/cleanup evidence 定义。bridge/supervisor 负责产生和运行时校验，
  B2 receipt 复用同一序列化/解析器；`docker_smoke.py` 和 pair 层不得各自再维护字段清单。
- 以 `a98914c` 为生产/测试基线，最终仓库级净变化至少满足：
  - 生产 Python **净删除不少于 1,500 行**；
  - 测试 **净删除不少于 1,000 行**，测试方法总数不高于 260；
  - `pair.py + docker_smoke.py` 合计不高于 2,400 行；
  - 不得通过搬文件、生成代码、压缩可读性或删除必要安全检查凑行数。若无法达到，应暂停说明，而不是加新层。
- 只保留围绕稳定外部行为的测试：marker 真成功/假回显、两侧公平、secret/预算边界、Docker 资源 fail-closed、
  cleanup、当前 receipt。删除固定常量、旧 schema、retirement、migration 和重复字段投影测试。
- 轻量代码阶段只跑相关模块；在准备真实 Docker 前只跑一次全量 `just eval-test` 和一次 `just eval-lock`。
- 提供唯一 canonical `just`/CLI 入口，在一个进程内按 RONDO→Codex 严格串行运行；首侧失败立即停止，第二侧
  不运行。一次授权批次最多两个 no-API Docker run，不自动重试。
- 双侧真实 Docker 均 completed，严格 marker、UID 1000 Git probe、custom seccomp、non-root、cap-drop、镜像
  digest、资源阈值和 cleanup 在生产路径生效；真实 API 请求必须为 0、费用为 0。
- 日志按 `AGENTS.md` 只记录有意义的实质修改和验收事实；历史日志不删除，也不计入本次代码瘦身成果。

## 2. 范围

### 允许修改

- `eval/rondo_eval/terminal_bench/` 中 no-API fake、adapter、当前冻结输入、轻量 B2 编排和付费边界的解耦代码。
- `eval/rondo_eval/runtime_bridge.py`、`eval/rondo_eval/docker_supervisor.py` 中重复 runtime/cleanup evidence 的
  canonical 化；宿主资源监督逻辑本身只允许等价整理，不允许放宽。
- `eval/rondo_eval/migrations/plan008_claimed_diagnostics.py` 及其专用测试和仅为该迁移存在的包入口。
- `eval/locks/p1-terminal-bench-pair-v1.json`：删除 retirement、数千文件闭包和 no-API 审计状态字段，保留当前
  bundle、task/image、公平配置、seccomp 和必要 Harbor 轻量身份。
- 与上述生产行为直接对应的 `eval/tests/` 测试；必须以合并/删除为主。
- `justfile`：增加或收敛唯一 B2 no-API 串行入口，不增加并行入口。
- `plan/009-p1-b2-lightweight-slimming-and-v5-execplan.md` 的当前状态/决策记录。
- 实施完成时精炼更新 `doc/WBS.md`、`doc/WBS/eval-benchmark.md`、Plan 008 当前状态；只写最新事实。
- 与本批实质修改直接相关的精炼执行日志。

### 不允许修改

- `mydev/` 产品源码、冻结 Codex/RONDO 二进制、bwrap 资产、Terminal-Bench task/source/image 内容。
- `ArtifactWriter`、API budget proxy、paid publication/M1 的核心恢复语义；本批只把 no-API 从它们中解耦。
- L1/L2、本地模型、Guardian 协议、训练/canary、上游基线。
- 已发布结果行、预算 ledger、v3/v4 历史 ledger、raw trial、watchdog 历史证据和既有历史日志。
- 为减行数而删除 Docker 内存/磁盘/VHDX监督、watchdog、镜像 digest、custom seccomp、non-root、
  `cap_drop=ALL`、secret 不进容器、预算上限或公平配对。
- 新增数据库、签名、中心服务、跨 clone 协调、通用资产审计框架或新的 schema 迁移系统。

### 不允许读取/查看

- `.env.local` 内容；只能按既有规则静默检查存在性、非 symlink、`0600` 和所需变量非空。本计划 no-API 阶段
  不需要读取其中任何值。
- 项目外个人文件、其他仓库、来源不明的 Docker 对象内容。
- 任何真实 API key、模型权重或私有外部数据。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **减法优先**：每个修改都必须属于 marker 修复、删除历史包袱、合并重复事实或跑通真实 B2。发现其他低风险
   问题只记录到本计划“阻塞项”，不得顺手新增字段、validator、账本状态或测试。
2. **四类阻断**：只有会造成假成功、泄密/未授权费用、宿主或 Docker 资源失控、付费 run 不可恢复的问题可以
   阻断交付；普通诊断不完整、日志措辞、极端掉电窗口和跨物理 clone 问题不阻断 B2。
3. **no-API 不是付费测评**：no-API 可以安全重跑，不占 API 预算，不进入正式 `runs.jsonl`，不需要永久
   identity retirement。只保留“当前一次 B2 验收”的原子 receipt；新运行可以替换旧的当前 receipt。
4. **paid 保持严格**：真实 API 的预算、run claim、append-only publication 和崩溃恢复不得因本批删除。
5. **一个事实一个所有者**：Docker runtime/cleanup 字段只在一个 typed contract 中定义和校验；其他层只能消费
   该对象或其 canonical hash，禁止复制字段集合与阈值。
6. **轻量 Harbor 身份**：个人同 UID 环境不对抗主动篡改。`uv sync --frozen` + tracked lock + Harbor 版本/
   entrypoint/key package 足够；不得恢复全依赖文件闭包。
7. **测试做减法**：新增测试不超过 5 项；每个新增项必须能在旧实现上失败。删除旧机制时同步删除其测试，不保留
   “永远不会再运行”的兼容测试。
8. **提交与日志不代替瘦身**：提交按可恢复的实质修改组织，日志保持精炼；不得把拆提交、删历史日志或移动代码
   计入轻量化成果。轻量化只按生产代码、状态机/schema 和测试耦合的实际净减少验收。
9. **执行前 clean commit**：真实 Docker 前必须形成 clean harness commit，v5 当前 receipt 不存在，相关轻量门禁
   通过；Docker 运行期间不得再修改代码。
10. **Docker 严格串行**：通过项目规范 watchdog 和 canonical lock，只运行固定 `fix-git`、固定 digest、固定
    RONDO→Codex 顺序；与 Cargo/模型互斥。前后记录 `docker system df`、VHDX 和 Windows `C:` 盘实际
    剩余空间；40/60GB、80GiB 阈值保持不变，WSL 虚拟余量不作为容量证据。
11. **不拉取、不构建**：若 pinned image、runtime bundle 或 Harbor 冻结环境不存在，停止并报告，不自动 pull、
    build、sync 大型资产或重新构建 Rust。
12. **失败即停**：RONDO 失败则不运行 Codex，不自动创建新 identity，不自动重试。只允许修直接阻塞真实链路的
    原因；是否重新执行由用户后续指示。
13. **证据适量**：最终 B2 receipt 只保留验收必需的非敏感事实和 canonical hashes，不保留 raw argv、stdout、
    stderr、宿主绝对路径或完整依赖清单；失败信息以一个安全错误码和直接原因即可。
14. **不冒充阶段完成**：pure/fake 通过不等于 Docker 通过；B2 通过不等于 B3/M1 或 Plan 008 全部完成。

## 4. 软性建议

- 优先把现有 per-side `docker_smoke` 改成可复用函数，再用一个极薄的 pair orchestrator 串行调用两侧；不要再建
  通用 workflow engine。
- no-API current receipt 建议只包含：harness commit、lock SHA、两侧 bundle SHA、两侧 completed 状态、严格
  marker/Git probe、Docker contract hash、cleanup verified、真实请求数为 0。运行时详细 metrics 由 canonical
  Docker receipt 持有，不在 pair 层逐字段复写。
- paid 代码如果与 no-API 混在 `pair.py`，只做足以删除 no-API 状态机的窄拆分；不要为了目录美观移动大量代码。
- Harbor preflight 建议使用 `eval/uv.lock` SHA、distribution version、console script normalized SHA 和 interpreter
  realpath；最多再选 1～3 个真正决定入口行为的 package 文件，不遍历 site-packages。
- 先删除 migration/retirement/closure，再合并 evidence，最后修 marker 和收敛入口；每一步都应让总代码净减少。
- 子智能体只用于只读盘点或一次最终独立复核；同一文件不并行编辑，避免冲突和重复建议。
- 如果某个旧测试只断言固定常量、JSON key 集或命令整串，优先由一个端到端行为测试替代，而不是逐项更新。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 当前执行者 worktree 从 `aa73ecf551e60a56807307896bab5fbbacd02e5f` clean commit 进入真实执行阶段；
  `main == origin/main ==
  2cc9140022f69803afff7bc373e3beeee0579be9`，尚未合并、未推送。
- v4 RONDO 真实 Docker 失败已保留，Codex 未运行；v5 ledger/receipt 尚不存在。
- scoped `safe.directory`、UID 1000 前置 Git probe、cleanup 明确 phase、失败事实与 65/70 分类已进入代码。
- 轻量基线为 286/286，`just eval-lock` 为 85 packages；这些不代表 v5 Docker 验收。
- marker 已改为只接受精确两键的结构化 `exec_command` 结果：`exit_code` 必须为整数 `0`，`output`
  只能在去除末尾 CR/LF 后精确等于固定 marker；JS 先投影这两个字段，Python 再从冻结 code-mode 的
  两项 `input_text` wire shape 中读取第二项。失败回显、错误 item 数量和额外字段均拒绝。
- no-API permanent ledger、retirement、safe-summary 恢复和一次性三诊断 migration 已从生产路径删除；
  paid ledger、预算和 publication 恢复保持 hard-disabled 且未改弱。
- Harbor preflight 已收敛为 tracked `uv.lock` SHA、`harbor==0.20.0`、console/interpreter 与三个关键模块；
  受跟踪 lock SHA-256 为 `02433f28d91810d9dd9b2cf1639ce86554e5045709e7aef545d3102cb3900e9a`。
- `DockerExecutionResult.receipt()` 成为 B2 image/VHDX/runtime/metrics/seccomp/cleanup 的唯一序列化所有者；
  no-API 层只消费该 receipt，不再复制字段清单。
- canonical `just eval-b2-no-api` 在一个受 watchdog 监督的进程中严格执行 RONDO→Codex；首侧失败立即
  返回且不运行第二侧，两侧成功才原子替换 `eval-data/b2/current.json`。recipe 不覆盖
  `RONDO_PROJECT_ROOT`，由 watchdog 从 Git common dir 推导项目根，兼容 linked worktree。
- 以 `a98914c` 为基线，生产 Python 从 20,208 行降至 18,483 行（净删除 1,725），测试从 11,552 行
  降至 10,203 行（净删除 1,349）；测试方法 260 个，`pair.py + docker_smoke.py` 合计 2,143 行。
- 相关模块 99/99 通过；最终 `just eval-test` 260/260、`just eval-lock` 85 packages 与
  `git diff --check` 通过。

### 当前工作

- 用户已授权下一阶段真实 B2：固定 host-volume 为此前真实 v4 已验证的 `/mnt/c`。
- 受跟踪 pinned image digest 已存在于 daemon；执行前没有本项目 managed container/network/volume。
- 首次命令使用 fresh metrics `plan009-b2-aa73ecf`，在 Docker 前以 `binary manifest is unavailable` 返回 65：
  manifest 路径错误地落到 linked worktree。watchdog `wrapper_status=complete`、`stop=none`、
  `cleanup=none`，没有创建容器或 current receipt。
- 唯一直接修复是从 `git --git-common-dir` 的父目录取得两个 bundle；相关 dry-run 通过后，以新的 fresh metrics
  `plan009-b2-aa73ecf-r2` 重验。r2 同样在 Docker 前返回 70：相对 wrapper argv 不满足既有 watchdog
  liveness identity。只把 wrapper 改为当前 `$PWD` 下的绝对路径，短生命周期 lease 诊断通过后使用 fresh
  `plan009-b2-aa73ecf-r3` 重验。r3 首次进入 Docker，真实 RONDO 在 `install.verify_file_owner` 失败；
  daemon/资源/seccomp/cleanup 均验证成功，Codex 未运行。直接原因是 Compose cp 保留 frozen 文件
  `1000:1000`/`0555`，实现却错误要求文件为 `0:0`。目录继续要求 `0:0`，文件改为消费实际
  `1000:1000`/`0555` 后，以 fresh `plan009-b2-aa73ecf-r4` 重验。r4 的真实 marker/tool round-trip 已通过，
  但 Harbor 直接执行冻结 task 中 mode `0600` 的 `/tests/test.sh`，verifier permission denied。只在 ignored
  staging copy 将该固定脚本设为 `0555`，以 fresh `plan009-b2-aa73ecf-r5` 重验。r5 在
  clean commit `b47a7b4` 上完成 RONDO→Codex：两侧均 completed、fake 请求各 2 次、
  tool round-trip 成功、cleanup verified empty，官方 API 0 次、费用 0 USD。

### 后续计划

1. B2 以 current receipt 作为当前轻量验收事实，不继续扩展 no-API 审计或状态机。
2. B3/M1 只能在新的真实 API 批次、轮数、模型和 USD 授权后启用。

### 阻塞项

- B2 无当前阻塞。B3/M1 仍由 paid hard-disable 与单独授权门阻断。

### 当前验收状态

- 本计划轻量代码阶段：完成；真实 Docker 阶段：完成。
- B1：保持完成。
- B2：瘦身、marker 修复与双侧真实 no-API Docker 验收完成。
- B3/M1：保持 hard-disabled/未运行，不在本计划内。
- L2 model-backed：未验收，不在本计划内。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | no-API 改为可重复的轻量当前验收，不使用 paid exactly-once/retirement | 无 API 费用，不值得为调试失败永久消耗 identity | B2 编排、pair | 已采纳 |
| 002 | paid budget/publication 恢复与 no-API 分开，保持 hard-disabled | 付费 run 确实需要不可复用和恢复，不能随 no-API 一起删 | B3 | 已采纳 |
| 003 | 删除已完成的一次性 migration 和 v4 retirement 代码，历史数据原样保留 | 代码使命已完成，继续维护只有阅读和测试成本 | migration、lock、测试 | 已采纳 |
| 004 | Harbor 从数千文件闭包降为 lock/version/entrypoint/key package | 个人同 UID 项目不做本地资产审计 | B1/B2 preflight | 已采纳 |
| 005 | Docker runtime/cleanup evidence 只有一个 typed owner | 避免同一字段在多层重复定义和漂移 | bridge、supervisor、smoke、receipt | 已采纳 |
| 006 | 以生产代码净删除、状态/schema 减少和测试解耦作为轻量验收 | 防止“瘦身”再次变成新增抽象和新状态机；提交和历史日志不计入成果 | 全任务 | 已采纳 |
| 007 | B2 双侧通过后立即冻结，不处理低风险理论增强 | 当前目标是跑通最小真实链路，不是构建审计系统 | B2 验收 | 已采纳 |
| 008 | no-API 只保留一个可替换 current receipt，pair ledger 仅服务 paid | no-API 可安全重跑，不需要不可复用状态或 retirement | B2、paid 边界 | 已落地 |
| 009 | 本次真实 B2 只使用 `/mnt/c` 与 fresh metrics `plan009-b2-aa73ecf`，一次命令、无重试 | 复用此前已验证 Docker Desktop 宿主盘事实，并保证本批可定位、可停止 | B2 真实执行 | 已采纳 |
