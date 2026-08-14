# Plan 022：RONDO Multi 产品基线建立

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述当前任务；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 最终目标

按 `doc/WBS.md` 工作包 2 与 `doc/WBS/multi-agent-trusted-evidence.md` 的 M-0 合同，在当前
RONDO Local 基线上建立可独立构建、可独立识别的 RONDO Multi 产品源码基线：把共享构建锁/资源看门狗迁到
仓库根，从本任务基线的 `mydev/` 精确复制 Git 跟踪文件到 `multidev/`，锁死 Local 审批扩展默认关闭的行为，
并让 `rondo-multi` 身份贯通源码与构建路径、binary freeze、manifest 和结果归档。

本任务只建立产品基线和必要的共享设施适配；不实现任务图、证据图、调度、协作工具或任何其他 Multi 功能，
不决定 WBS 的 D1/D2。

### 完成/验收标准

- [ ] `multidev/` 来自本任务基线 `mydev/` 的 Git 跟踪文件；普通文件、可执行位和符号链接完整，且没有复制
      `mydev/codex-rs/core/` 下的 `.git`、`.agents`、`.codex`、`project`、`absolute-turn`、
      `request-permissions-environment` 等未跟踪残留。
- [ ] `with-build-lock.sh` 与 `build-watchdog-lib.sh` 位于根 `scripts/`；现行代码、测试、just 入口和安全文档
      全部使用新路径，共享 helper 回归仍由 Local/Multi 测试入口覆盖，旧脚本路径不存在且不留 shim；脚本逻辑、
      阈值、退出语义和权限不变。
- [ ] Multi 的空配置行为测试证明 `[auto_review]` 的 `model`、`model_provider`、`reasoning_effort`、
      `evidence_dir` 均为 `None`；测试经过真实配置加载路径，而不是只断言手写常量。
- [ ] Multi 的基线/无 API 结果合同显式记录 `product = "rondo-multi"` 和上述四项未配置状态；缺字段的历史
      `side=rondo` 仍按 `rondo-local` 解释，`side=codex` 不携带或推断产品身份。
- [ ] eval 入口能显式选择 `rondo-local` 或 `rondo-multi`；Multi 使用 `multidev/codex-rs`、独立 Cargo target、
      `eval-data/bin/rondo-multi/` 与带产品身份的 manifest/归档，不能回落到 `mydev/` 或历史 `bin/rondo/`。
- [ ] `multidev/` 的配置和本任务新增测试不引用 GGUF 路径、本地审批模型 launcher/runtime 或真实模型资产；
      继承的 Local 审批接口保持默认关闭，不删除、不回退，也不计入 Multi 基线能力。
- [ ] 复制/路径/产品身份的 focused Python/Rust/shell 回归、迁移后的 `just eval-test`、`just eval-lock` 和
      一次 Multi `codex-cli` 轻量带锁构建通过；不重跑 Rust 全 workspace。
- [ ] `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS-COMPLETED.md`、
      `doc/development-environment.md` 与精炼 `agent_log/` 只在各自职责内同步最终事实；`README.md` 无需重复历史。
- [ ] `git diff --check` 通过；没有密钥、ignored 本机资产、意外生成物或历史结果改动。

## 2. 范围

### 允许修改

- 新建 `multidev/`，内容为本任务基线 `mydev/` 的 Git 跟踪文件及完成本计划验收所需的窄测试调整。
- `mydev/justfile` 中共享看门狗的新路径；必要时可在 Local 与 Multi 同源的配置测试中加入默认关闭回归，
  但不得改变 Local 产品行为。
- 根 `scripts/with-build-lock.sh`、`scripts/build-watchdog-lib.sh`（从 `mydev/scripts/` 移动，不重写逻辑），以及
  `mydev/.github/scripts/test_build_watchdog_lib.py` 对共享 helper 新位置所需的迁移/入口适配和根 `scripts/` 下相应
  共享测试目的路径。
- 根 `justfile`、`eval/rondo_eval/` 与 `eval/tests/` 中共享看门狗路径和双产品身份所需的最小改动。
- `AGENTS.md`、`CLAUDE.md`、`doc/development-environment.md` 中现行看门狗路径。
- `plan/022-*.md`（本文件）、一份精炼 `agent_log/`，以及完成时受影响的 WBS/WBS-COMPLETED 条目。

### 不允许修改

- `codex-source-code/`、`reference-agent-harness/`、`codex-doc/`。
- v1—v22 历史 lock、result、ledger、receipt、aggregate、binary bundle 或公共 `runs.jsonl` 记录。
- `agent_log/`、`doc/audit-snapshots/`、`doc/research/` 和既有 plan 中冻结的旧路径或历史结论。
- `mydev/` 的产品语义、依赖版本、Cargo/Bazel 锁文件；本任务不借 bootstrap 回退或重构 Local 审批实现。
- Multi 功能行为、D1/D2、付费 campaign 合同、统计判据或新的大型测试/测评框架。

### 不允许读取/查看

- `.env.local` 内容。
- 真实密钥、私有评测原件、holdout 正文/solution/verifier/单题结果。
- `rondo.local.toml` 内容；本任务不依赖本机模型或 provider 配置。

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提高局部指标而违反。

1. **隔离执行**：所有受跟踪编辑、构建和测试只在
   `.claude/worktrees/023-rondo-multi-bootstrap`（分支 `worktree-023-rondo-multi-bootstrap`）进行。
   主工作区进入任务时为干净 `main@d84632fb74dbaad0b4b43c047d292dc46450bc77`；不得在主工作区直接实现。
2. **精确复制**：先更新 `mydev/justfile` 的根看门狗路径，再从工作树当前内容复制 `mydev/` 的 Git 跟踪文件。
   复制必须由 Git 文件清单驱动并保留 mode/symlink；禁止直接递归复制整个目录后把未知残留带入 Multi。
3. **可复算完整性**：实现应提供或记录复制前后的相对路径、文件类型/模式与内容摘要比较；仅允许计划中明确的
   Multi 专属验收改动形成差异。不得用“文件数接近”代替完整性证明。
4. **看门狗只迁移不改语义**：两个脚本使用 `git mv` 迁到根 `scripts/`，保持字节内容和各自原 mode
   （wrapper `100755`、helper `100644`）；共享 helper 测试应迁到共享位置或由两产品入口显式调用根 helper，
   不能在复制后继续动态寻找产品内已不存在的脚本。直接修改所有现行引用，不保留软链、wrapper 或兼容 shim。
   `eval/locks/*.json` 等冻结 provenance 与历史文档不得改写。
5. **路径门仍须 fail-closed**：迁移后 `script_dir` 必须能加载同目录 helper，`project_root` 仍解析到共享 RONDO
   仓库根，eval 的 canonical wrapper/进程 argv 校验必须精确接受根脚本并拒绝旧路径或近邻路径。
6. **产品与比较侧正交**：`product` 只取 `rondo-local` / `rondo-multi`；`side` 继续只取 `rondo` / `codex`。
   `side=codex` 不得获得产品身份；任何 Multi 请求都必须显式选择 `rondo-multi`，不得依赖 Local 默认值。
7. **身份全链一致**：选择 `rondo-multi` 后，源码根、Cargo manifest/target、binary artifact 目录、manifest、
   shared model catalog 来源、adapter/RunSpec、campaign/运行记录和私有归档摘要必须一致；任一层是 Local、缺失、
   矛盾或路径漂移均 fail-closed。
8. **历史兼容只读**：历史无 `product` 的 RONDO manifest/result 按 `rondo-local` 读取，历史 Codex 侧视为不适用；
   不回填、不原地升级、不改变旧 bundle 字节。新增 schema/字段必须有新旧读取回归与错误组合回归。
9. **默认关闭是真实行为门**：验收必须经过实际配置加载/运行投影，断言四个字段均未配置；结果工件记录的是
   “配置未设置”，不得把 catalog/provider 派生出的有效模型误写成显式 `[auto_review]` 配置，也不得通过修改
   `approvals_reviewer` 来伪造关闭态或改变既有公平运行合同。
10. **不携带本地模型依赖**：不得把 `eval-data/models/`、GGUF、llama.cpp launcher/runtime、CUDA/CPU 本机路径
    或 `rondo.local.toml` 值写入 `multidev/`、测试 fixture、manifest 或结果。
11. **无真实外部执行**：本任务禁止 Docker、真实 API、付费 TB、真实本地模型加载/推理、模型/大资产下载、
    上游升级以及创建正式 campaign identity、run ID、结果行或预算账本。结果形状验收只使用 synthetic/in-memory
    producer 或临时 fixture；不得写入 `eval/results/runs.jsonl`、正式 `eval-data/runs/*` 或保留 ignored 工件。
    普通缺失依赖下载仍服从执行前一次授权。
12. **资源门禁**：所有 Rust 构建/测试必须走迁移后的根 `scripts/with-build-lock.sh` 或已接入它的 Multi `just`
    入口，不得直接运行 Cargo；执行前确认无其他 Cargo/Docker/真实模型任务、只有一个产品 target 处于热状态，
    并由看门狗读取 Windows `C:` 实际余量。计数器不可得或命中停止线时 fail-closed，不绕过锁、cgroup、阈值
    或 rustc throttle。
13. **测试适量**：先跑受影响的 config、binary freeze、runtime bridge、result/archive 等 focused 测试，再跑一次
    `just eval-test`；Rust 只跑默认关闭回归所属 package 和一次 `codex-cli` 轻量带锁构建，不跑全 workspace。
    skip、未运行、fake 与纯测试不得表述为真实 binary freeze、Docker 或能力验收。
14. **秘密与 ignored 资产**：不得打开 `.env.local` 或 `rondo.local.toml`。worktree 缺少 ignored 的 `eval/.venv`
    或 `eval-data/` 时，可以在 worktree 内新建安全的 ignored 环境，或显式复用主仓库已有环境来运行 worktree 源码；
    不得因此在主工作区修改受跟踪文件，也不得把 symlink、缓存、target、metrics 或本机路径提交。
15. **审查交接**：执行者完成自查后在本 worktree 分支提交完整实现并停止，不合并 `main`、不推送远端、
    不删除 worktree。由独立审查者核对 diff、门禁和现场状态后决定是否进入合并交付。

## 4. 软性建议

以下内容用于根据现有代码给出的执行建议，但不是固定约束，也不代表代码变化之后的精准效果预测。AI 可以依据
代码、实际测试和运行结果采用更小、更清晰的等价方案。

- 复制可使用 `git ls-files -z mydev/` 生成清单，再以保留 mode/symlink 的归档流映射到 `multidev/`；不要把
  6,013 份文件逐项手工处理。
- 在现有 `Product` / `product_for_side()` 上扩展，不再发明 variant/side 的同义枚举；可用窄的产品布局映射集中
  管理 `mydev|multidev`、`rondo|rondo-multi` 与 target 名称，避免散落字符串分支。
- 对 binary manifest 使用版本化或显式兼容的解析：新工件写明产品，旧工件只按既定路径/side 规则推断 Local；
  保持严格 key 校验，不为了兼容而接受未知字段。
- 让 campaign identity、RONDO manifest 与结果记录三方交叉校验产品；结果顶层和归档内 `run-summary.json`
  使用同一个投影函数，避免成功/失败发布路径分叉。
- 默认关闭的结果形状可采用一个小型、版本化的 `auto_review_config` 块记录四个 `null`，但应复用现有配置加载结果，
  不建立新的配置系统或把“未配置”混同为最终有效 Guardian 模型。
- 复制前把可同时适用于 Local/Multi 的默认关闭回归加入共享源文件，可减少两棵树无意义分叉；若实际架构更适合
  Multi 专属测试，则把该差异列入复制完整性 allowlist。
- 迁移路径的回归优先覆盖现有 watchdog helper 测试，并扩展 `test_runtime_bridge.py`、`test_binary_freeze.py`、
  `test_terminal_bench_results.py`、`test_terminal_bench_baseline.py`，不另建重复测试框架。
- Multi 轻量构建优先选择受根 wrapper 监督的 `cargo build --locked -p codex-cli --bin codex`；若现场资源证明
  它不再“轻量”，先记录资源事实并与用户确认替代门，不得擅自把 `cargo check` 表述为已产出可构建二进制。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

首个实现提交 `d2c16073` 与首轮修复提交 `c5eb380` 均被独立验收拒绝合并。基础实施事实仍见
`agent_log/2026-08-14-004500-plan022-rondo-multi-product-baseline.md`；第二轮复验报告
`agent_log/2026-08-14-011251-plan022-fix-independent-reacceptance.md` 指出的 B1—B3、M1—M3 与文档问题已逐项修复：

1. 共享看门狗已 `git mv` 到根 `scripts/`（mode 与字节不变），现行引用点全部改为根路径且不留 shim；
   共享 helper 回归改由两条产品线的 `test-github-scripts` 入口显式调用根 helper。
2. `multidev/` 由 Git 清单驱动复制，6,011 条与 `mydev/` 的 blob、mode、工作树 sha256 逐条相同，
   无清单外文件，六个未跟踪残留目录均未进入。
3. 默认关闭行为门落在两棵树同源的 `config_loader_tests.rs`，经 `ConfigBuilder` 真实加载路径断言。
4. 新 RONDO/Codex freeze 产物已与生产 loader 收口；campaign request/manifest/RunSpec、successor、no-API
   bundle、publication/replay/aggregate 均交叉绑定产品，历史缺字段工件保持只读兼容。
5. v7 campaign publication 在落盘前强制两侧绑定 campaign product；正常与失败 publication 都生成与 tracked
   row 等值的版本化私有摘要，journal recovery 与 durable index reader 重新核对摘要。
6. terminal aggregate 不再因两份 aggregate 自洽而早退，终态恢复会从 state、budget、runs index、record digest
   和冻结 identity 重建并逐字节核对；campaign consumer 另与冻结 selected profile 比较。
7. replay 的 product/binary 合同与当前 shadow Local side 映射已收紧，历史无产品记录保持只读兼容。

### 当前工作

第二轮复验修复与复审准入门禁已完成；提交当前任务分支后停止，等待再次独立复审。

### 本任务剩余步骤

无实施步骤；只剩再次独立复审及用户对 §6 决策 011 窄例外的确认，不在本轮执行者权限内。

### 阻塞项

完整 `git diff --check` 与 `multidev/` 精确复制之间的既有冲突仍按用户要求保留为窄例外，等待用户明确接受；
手写文件必须保持 `diff --check` 干净。

### 当前验收状态

对照 §1 完成/验收标准：

- 第二轮复验的 B1/B2/B3、M1/M2/M3 与对应文档修复已落地；focused 受影响集合 319/319，完整 eval 无 API
  套件 607/607（0 fail、0 skip），`just eval-lock` 解析 85 packages，两侧 watchdog helper 各 9/9。
- 本轮未修改 Rust 产品源码，按复审条件未重复 Cargo 构建。首个实现批次已有的根看门狗 Multi
  `codex-core` 80/80 与 `codex-cli 0.147.0` 轻量构建证据保留，但不冒充本轮新运行。
- `git diff --check`：手写改动部分干净。`multidev/` 例外 —— 6,011 个文件全为新增行，其中 419 个上游
  文件自带行尾空白（TUI 动画帧、prompt markdown、apply-patch 空白 fixture），已逐一 `cmp` 确认与
  `mydev/` 原件字节相同；修改它们会违反更强的「精确复制」硬约束，因此保留原样。
- 未运行/不适用：Docker、no-API 双侧真实执行、真实 API、真实本地模型、全 workspace Rust 测试。
  `eval-data/bin/rondo-multi/` 仍为空，Multi 尚无冻结 runtime bundle。
- 已知代价（决策 008）：看门狗改根后，历史 Local/Codex bundle 的 `binary_freeze verify*` 因其
  build-command 记录的是旧 wrapper 路径而不再通过。

### 交接边界

本计划到此冻结为任务合同与历史记录。工作包 3 的三线并行、Multi D1/D2 和首个功能增量只链接
`doc/WBS.md` 与 `doc/WBS/multi-agent-trusted-evidence.md`，不在本计划续写。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | Multi 从当前 `mydev/` Git 跟踪树直接复制，不回退到纯上游或历史提交 | WBS 已裁定；可继承当前测试修复并避免回退 Local/P0 重构 | `multidev/` | 已采纳 |
| 002 | “干净基线”以默认关闭的行为门定义，不以源码中是否出现 Guardian 目录定义 | Guardian 是上游自带能力，源码纯度门不可执行 | config/测试/基线记录 | 已采纳 |
| 003 | 共享看门狗直接迁根且不留 shim | eval 会校验 canonical 进程 argv，shim 不能省去适配且会制造身份歧义 | `scripts/`、just、eval、安全文档 | 已采纳 |
| 004 | 产品身份与比较侧保持正交；Multi 所有新入口显式选 product | 防止 `side=rondo` 继续隐式等同 Local，同时保护 Codex 侧语义 | binary/manifest/campaign/result | 已采纳 |
| 005 | 旧无 product 工件只读兼容，新 Multi 工件显式身份并严格拒绝矛盾 | 历史只加不改，同时让 Multi 不会落入 Local 路径 | manifest/result parser | 已采纳 |
| 006 | 本工作包只做无 API/fake 与轻量构建验收，不产正式 campaign 或能力结论 | M-0 是产品基线；真实退化验收属于后续重大增量并需单独授权 | 测试与交付 | 已采纳 |
| 007 | 执行者只提交 worktree 分支，独立审查前不合并/推送 | 用户指定由独立审查者验收，保留清晰审查边界 | Git 交付 | 已采纳 |
| 008 | 接受「看门狗改根后历史 bundle 不再可 re-verify」这一代价，不做双路径兼容 | 硬约束 5 要求精确接受根脚本并拒绝旧路径；冻结 bundle 字节与 `eval/locks/*.json` 未改，影响面止于 `binary_freeze verify*` | binary freeze | 已采纳 |
| 009 | 仅 build-command 的 `--product` 在非 Local 时出现；新 RONDO manifest（Local/Multi）始终显式写 `product`，Codex 与历史 manifest 省略该键 | Local build-command 保持 seven-key 历史形状；权威数据布局同时要求新 RONDO manifest 显式身份 | binary freeze / manifest | 已采纳 |
| 010 | eval 为 Multi 不注入 `[auto_review]` 三项覆盖，Local 的既有公平合同不变 | M-0 要求基线在关闭态取得；改 Local 会动既有公平运行合同（硬约束 9） | adapter / result | 已采纳 |
| 011 | 完整 `git diff --check` 的唯一例外限定为与 `mydev/` 字节相同的 `multidev/` 复制内容，手写差异必须通过；例外仍待用户明确接受 | 清理上游尾空格会破坏更强的精确复制合同，不能为绿灯改写复制内容 | 复制验收 | 待用户确认 |
| 012 | 新 TB publication 用显式 schema 绑定 campaign 产品与私有摘要；终态 aggregate 每次从 durable sources 重建 | 可选字段和成对 aggregate 自洽均不足以证明产品与结果来源，必须在落盘/恢复边界 fail-closed | result / campaign recovery | 已采纳 |
