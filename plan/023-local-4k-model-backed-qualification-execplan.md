# Plan 023：RONDO Local 4k model-backed 首次 qualification 与 capability 晋级

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。
> 本计划只描述 Turn A；跨任务路线、优先级、顺序和依赖以 `doc/WBS.md` 与
> `doc/WBS/local-approval-model.md` 为唯一来源。

## 1. 目标

### 最终目标

在不进入 L7 或 Local M3 的前提下，使用 Plan 018 已冻结的 exact llama.cpp `b10333` Linux CUDA runtime、
唯一 GGUF 和现有 4k 服务合同，完成第一次真实模型加载与一条真实 `E_final` 的结构化审批。只有完整实证与现场清理
均成功后，才新增版本化 model-backed qualification evidence，使 live capability 从
`linux_cuda_built_model_unvalidated` 晋级为 `gpu_model_serving_validated`，随后用**原正式 launcher**重新启动并由 doctor
在服务存活期间复验。

Turn A 的成功终点只是“这套 exact runtime + model + 4k 合同的本地模型服务真实可用”。cloud/local Guardian 配置切换、
L7 与 Local M3 均属于后续 Turn B，不得在本任务中提前认定。

### 完成/验收标准

- ignored 主仓 `rondo.local.toml` 只迁移 `[local_model]`，已有 `providers`、`paid_eval`、模型和价格配置的规范化内容
  保持不变；文件仍为主仓普通非 symlink、mode `0600`。
- 真实配置精确指向 Plan 018 的 `b10333` CUDA runtime 与唯一 GGUF，服务合同为 4k / `gpu_layers="auto"` /
  `fit="on"`，其余参数遵守现有本地审批合同。
- 受控 qualification 只能验证上述 exact 组合；正式 launcher 在证据完成前继续拒绝启动，且没有新增可复用的通用 bypass。
- 真实 smoke 证明模型成功加载、CUDA 启用且 GPU offload 为正数，并让一条既有真实 `E_final` 返回符合现有 schema 的
  `allow|deny`、非空理由和风险标签；CPU-only 静默退化视为失败。
- 记录可复核的 runtime/model/template/实际服务身份、fit 后实际上下文与 GPU 参数、峰值显存、真实首 token 延迟、总耗时和
  structured response 合规性。测量实现可以替换，但不得使用已知不代表首 token 的 b10333 `/metrics` predicted-token 口径。
- qualification 的模型加载、身份、CUDA/offload、必需指标、结构化响应或清理任一项失败时，不得晋级，capability 保持
  `linux_cuda_built_model_unvalidated`。
- 成功后新增版本化、严格校验的 model-backed evidence；Plan 018 的 CUDA base lock、审计快照和
  `model_backed_structured_output=not_run` 历史事实保持不变。live capability 只有在当前 exact 身份/合同与完整成功证据匹配时才
  投影 `gpu_model_serving_validated`，无效证据 fail-closed。
- 晋级后由无 qualification 特权的正式 launcher 再启动一次；服务运行期间 doctor 报告 ready、晋级后的 capability、匹配的
  模型/服务身份，并通过 structured decision probe。
- focused local-approval/config 测试全部通过；若新增或改变任何 lock schema，额外通过 `just eval-lock`；不运行 Rust workspace、
  Docker、真实云 API 或全量 eval。
- 本任务创建的 llama-server、监听端口、launcher receipt、qualification 私有原始日志和临时指标对象全部清理；只保留
  tracked allow-list evidence 与必要的精炼历史记录。
- 成功时 WBS 当前事实更新为“4k model-backed 已完成，下一步 L7/Local M3”；失败时保留原 capability 并在 plan/agent log
  记录不含敏感内容的精确阻塞码和发生阶段，不进入 Turn B。

## 2. 范围

### 允许修改

- `plan/023-local-4k-model-backed-qualification-execplan.md`
- `eval/rondo_eval/local_approval/` 中 qualification、model-backed evidence loader、capability 投影、CUDA source-build
  service identity 和安全生命周期所需的最小 Python 实现
- `eval/tests/test_local_approval.py`，以及确实受影响时的 `eval/tests/test_config_hardening.py`、
  `eval/tests/test_config_and_artifacts.py`
- `eval/locks/` 下**新增**的版本化 model-backed qualification evidence（建议固定为
  `eval/locks/local-approval-b10333-ministral-4k-v1.json`）
- 主工作区根目录 ignored `rondo.local.toml` 的 `[local_model]`、`[local_model.server]`、
  `[local_model.request]` 三个表；这是 linked worktree 共用本机配置的唯一例外
- 主仓 ignored `eval-data/local-approval/` 下本任务自己的 0700/0600 临时 qualification receipt、原始 server 输出和指标对象
- `doc/WBS.md`、`doc/WBS/local-approval-model.md`、`doc/WBS-COMPLETED.md` 中本任务实际影响的当前事实/完成证据
- `agent_log/` 下一个精炼 Turn A 执行日志

### 不允许修改

- `mydev/`、`multidev/` 以及任何 Guardian/Rust 产品逻辑；如果真实链必须修改 Rust，停止并拆成独立修复任务
- `eval/locks/llama-cpp-b10333-cuda-linux-x64.json`、`eval/locks/llama-cpp-b10333.json` 和 Plan 015—018 的冻结合同/历史事实
- `rondo.local.example.toml` 的 8k baseline；Turn A 只迁移真实 ignored 配置，不把 4k smoke 冒充新的长期示例 baseline
- `README.md`、既有 audit snapshot、真实结果账本、训练、L3/L4/L5/L6/L7、Local M3/M4 或 Multi 路线
- 唯一 GGUF、现有 CUDA runtime/source/toolkit 的内容；不得下载、替换、重建或“修复”这些大资产
- eval 依赖与 `eval/uv.lock`，除非实现遇到现有标准库无法完成的已证明阻断；发生时先停下请求范围变更
- 来源不明的进程、端口、cache、receipt、worktree、分支或用户/并行任务修改
- 系统/Windows 配置、GPU driver、全局 CUDA、系统服务、Docker 资产或项目外文件

### 不允许读取/查看

- `.env.local` 内容；只能静默检查其存在性、普通非 symlink、mode `0600`，以及所需变量是否存在且非空
- API key、token、认证值的明文、长度、前后缀或哈希
- 与本次已选真实 `E_final` 无关的 holdout/私有测评内容；qualification 不得把所选 evidence 原文打印、复制到普通日志或
  tracked 工件

## 3. 硬约束

以下 9 条只约束结果、安全边界和失败语义。除明确写死的身份与合同外，执行者可以采用更简洁或更强的实现；若偏离 §4 的
推荐方案，应在本计划“关键决策记录”简要说明方案、等价性和验证方式，不需要为纯内部重构重新请求授权。

1. **范围与授权边界**：只修改 §2 的 Python eval、focused tests、资格证据、本机 ignored 配置和必要文档，不碰
   `mydev/`、`multidev/`、L7、Local M3、8k、Docker、云 API、训练或 runtime/model 资产。真实 qualification 与晋级后的正式
   launcher 复验需要两个模型生命周期；在用户明确补充“至多两次模型加载及各自必要的本地推理”前，只能实现和跑 fake/focused
   tests，不得自行扩大原“一次”授权。
2. **exact runtime/model/4k 合同**：只接受 Plan 018 的
   `eval-data/tools/llama-b10333-cuda-linux-x64/llama-server` 和其冻结 base closure；唯一模型为普通非 symlink
   `eval-data/models/mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf`，大小 `5,198,387,456` bytes、SHA-256
   `7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a`；配置必须是 `context_size=4096`、
   `gpu_layers="auto"`、`fit="on"`，其余服务/请求参数继续服从现有合同。身份或合同不符必须在模型启动前拒绝。
3. **qualification 与正式路径隔离**：必须有一个显式、受限的首次 qualification 路径，并继续持有现有资源锁、watchdog 和
   lifecycle identity。正式 launcher 在 capability 未晋级时仍须在 `Popen` 前拒绝；不得留下 CLI/env/参数形式的通用 bypass。
   qualification 的模块、CLI/API 形态和内部编排由执行者决定。
4. **证据完成前禁止晋级**：不得先改 capability、改写 Plan 018 base lock 或放置可通过的占位证据再补跑模型。只有真实 smoke、
   必需指标和本次现场清理全部成功后，才能原子产生晋级证据；任何失败或半成品都不得被投影为
   `gpu_model_serving_validated`。
5. **真实完成事实**：必须实证 exact GGUF 成功加载、实际 CUDA 启用且 `offloaded layers > 0`、实际上下文为 4096，并让一条既有
   真实 `E_final` 经现有结构化决策校验返回 `allow|deny`、非空理由和风险标签。必须记录峰值显存、真实首 token 延迟、结构化判定
   总耗时、测量方法及 structured response 是否合规；TTFT 保持本次 `stream=false` 合同并真实观察首 token，禁止使用已知只在
   请求结束后累计的 b10333 `/metrics` predicted-token counter。具体观测和采样实现可以采用任何经测试的等强或更优方案。
6. **最小完整 evidence 与历史保留**：新增版本化、严格 schema 的 model-backed evidence，至少能证明 exact base runtime、
   model、4k 服务合同、真实 structured smoke、必需指标存在且清理成功；不得保存 E_final 内容、rationale、risk tag 原文或生成文本。
   capability 的当前身份匹配只绑定会影响服务资格的稳定身份/合同，不要求把历史 VRAM/TTFT 数值当作每次投影的运行时身份。
   Plan 018 base lock、审计快照和 model-free 历史不得覆盖；evidence 存在但 malformed/incomplete/mismatch 时必须 fail-closed。
7. **watchdog、互斥与清理**：两次真实生命周期都必须从任务 worktree 使用同 checkout 的
   `./scripts/with-build-lock.sh`，持有现有锁/cgroup/watchdog，并与重型 Cargo、Docker、其他模型服务互斥。未知进程、端口或 GPU
   占用只报告不清理。所有失败/中断都只清理本任务可验证身份的进程、receipt 和私有临时对象；最终端口、进程、receipt 或临时
   现场任一残留均不得晋级。安全关停的具体 orchestration 可以替换，只要同等防止误杀并可测试。
8. **focused 回归与失败语义**：以少量测试覆盖失败类别：production gate/晋级顺序、runtime/model/config 身份拒绝、
   服务/CUDA/指标/structured response 失败、evidence 缺失或无效、receipt/cleanup fail-closed，以及 CPU release 与 CUDA source
   build 的精确 identity 分支。避免为每个字段复制高度相似 mock；只跑 local-approval/config focused tests，lock schema 变化时
   额外跑 `just eval-lock`，不跑 Rust、Docker、全 workspace 或全量 eval。
9. **文档与审查交付**：敏感 evidence、原始 server 输出和私有指标不得进入普通日志或 Git。成功后精炼同步两份 WBS、
   WBS-COMPLETED 与一个 agent log；失败则保留原 capability 并记录非敏感精确 blocker。执行者只在任务分支提交，报告 focused
   tests、真实 allow-list 结果、doctor 复验和最终清理，保留 worktree 给独立 reviewer，不合并、不推送。

## 4. 软性建议

- 优先新增窄的 `qualification.py` CLI，以便与 production launcher 清楚隔离；若现有架构更适合受限 subcommand、专用 orchestration
  对象或其他入口，也可以采用，只要满足 §3.3 且没有通用 bypass。
- model-backed evidence 可命名为 `eval/locks/local-approval-b10333-ministral-4k-v1.json`。字段和分组沿用现有 strict dataclass/JSON
  惯例即可，不强制八组布局；建议把“晋级时必须完整记录的观测事实”和“以后投影时必须继续匹配的稳定身份”明确分开。
- 用已有 `serve_config_sha256` 绑定 argv/template，并新增只覆盖 local request 表与 static decision schema 的 request-contract
  digest；不要绑定整个 `rondo.local.toml`，否则无关 provider/价格变动会错误失效。
- E_final 优先选一条已通过现有生产校验的冻结归档，固定安全相对路径、source SHA 与已验证 meta。若现有 loader 能低成本从
  RunSpec/lock 独立取得 expected model/effort，继续复用；否则本任务不要求为此接入整套 Terminal-Bench provenance，执行者应说明
  如何避免把任意文件冒充真实归档。
- qualification receipt 可复用 schema-v2 launcher identity 与 client 的重验；除非确有缺字段，不主动升级 receipt schema。
- readiness 应轮询 loopback `/health`，随后只读取 `/props`、`/models` 和指标所需 endpoint；所有 loopback opener 都显式禁用
  ambient proxy/redirect。使用 absolute deadline，进程提前退出立即失败。
- TTFT 首选轮询 `/slots` 中与 active task/slot 绑定的 `n_decoded` 首次正值，因为这已由 b10333 源码验证；若使用更干净的真实首
  token 观测方法，需保持 non-streaming、不得增加第二条 evidence 请求，并在决策记录与测试中说明为何等强。
- 峰值显存优先绑定 exact server PID；若 WSL 只提供设备级计数，可在已证明独占 GPU、无其他 compute process 的窗口内记录
  baseline/peak/delta 与方法。采样能力不足或出现其他 GPU process 时应失败。
- server stderr 只提取 build/offload/fit/load 等 allow-list 事实；raw 输出留在 0600 私有临时对象并在清理后删除。
- 对 tracked evidence 使用 temp `O_EXCL` + fsync + no-clobber 原子链接/创建；拒绝覆盖已有 v1。若以后需要重验，新增 v2，
  不覆盖 v1 或 base lock。
- 正式复验关停首选：重验 receipt 的 server PID/start ticks/cmdline/listener 后 TERM exact server，让 launcher 的 `finally` 清理；
  执行者也可实现并测试同等安全的受控 orchestration，不要求逐字采用该流程。
- focused 测试优先继续放进 `test_local_approval.py` 的现有 `LauncherAndDoctorTests`，只有 qualification 规模明显变大时才新建
  一个对应测试文件；不要拆出重型测试体系。
- 本节中的文件名、CLI、字段分组、采样和关停方式均是推荐实现。更优策略可以采用，但不得弱化 §3 的 hard gates，并须在决策记录
  中说明偏离点、收益和等价验证。

## 5. 实施与验证顺序

### A. 基线与配置迁移

1. 在专用 worktree 核对 branch/HEAD/diff；在主仓只读核对监听端口、launcher receipt、llama-server、GPU 与重型任务现场，不清理
   未知对象。
2. 静默验证主仓 `rondo.local.toml` 为普通非 symlink、mode `0600`；解析 TOML 后记录 `providers` 与 `paid_eval` 规范化 digest。
3. 只对主仓 ignored 文件的三个 local-model 表做字段级迁移：填入 exact model path/SHA、CUDA binary 和本计划 4k 参数；迁移后
   重载严格 schema，并断言前述 provider/paid digests 不变、mode 不变。不得用 example 整体覆盖。
4. 在 evidence 不存在时先证明正式 launcher 仍在 `Popen` 前拒绝当前中间 capability。

### B. 最小实现

1. 集中校验 exact runtime/model/4k 合同，避免 production、qualification、loader 和测试各自复制漂移值。
2. 实现严格的 model-backed evidence 与单向 capability 投影，同时保持 Plan 018 base lock/parser 原样。
3. 实现受控 qualification 生命周期：预检、启动、ready/identity、GPU/TTFT 采样、真实 structured decision、清理、最后写证据。
4. 解决当前 CUDA source build `1 (0865990)` 与 CPU release `10333` 被统一硬编码造成的 identity 阻断；两种 backend 仍须 exact
   匹配，不能放宽成模糊 substring。
5. 让正式 launcher 与 doctor 从真实 strict evidence 得到 capability，保留现有 receipt/client 的 fail-closed 语义。

### C. 回归门禁

以少量参数化/分类测试覆盖 §3.8：production gate 与晋级顺序；输入身份/合同；runtime/service/CUDA/指标/结构化响应失败；
evidence missing/invalid/complete；receipt/lifecycle/cleanup；CPU 与 CUDA build identity。测试应证明错误在正确阶段 fail-closed，
避免为每个 JSON 字段堆叠一条近似 mock。

推荐门禁命令如下；执行者可按实际改动缩小或补充同目录 focused tests，但不得扩大为 Rust/full-eval：

```bash
common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
env \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
  UV_CACHE_DIR="$common_root/eval-data/uv-cache" \
  UV_PROJECT_ENVIRONMENT="$common_root/eval/.venv" \
  uv run --directory eval --frozen --no-sync \
  python -B -m unittest -v \
    tests/test_local_approval.py \
    tests/test_config_hardening.py \
    tests/test_config_and_artifacts.py
```

若新增/改变 lock schema，再运行：

```bash
just eval-lock
```

`just eval-lock` 只验证 `eval/uv.lock` 的依赖锁一致性，不验证 `eval/locks/*.json`。新增 model-backed evidence 的 strict schema、
extra/missing field 和 identity mismatch 必须由上述 focused unit tests 单独覆盖并报告。

### D. 唯一真实 qualification 与正式复验

> 只有 §3.1 的模型生命周期次数授权补齐、focused tests 全绿、现场互斥/资源门禁通过后才能进入。

1. 选择一条既有、冻结且已验证 meta 的真实 `E_final`，固定安全相对路径与 SHA；只在内存读取内容，不在输出或 Git 记录原文。
2. 从任务 worktree 以同 checkout `./scripts/with-build-lock.sh` 运行受控 qualification，复用 common root 的 eval venv/cache；具体
   CLI 由实现决定。只执行这一条真实 evidence 请求，输出只报告 allow-list 状态与数值。
3. qualification 结束后先确认 server、端口、receipt 和私有临时对象已清理，再确认 evidence 原子生成；随后从 live loader 读取
   `gpu_model_serving_validated`，不得 mock 或手工覆盖 capability。
4. 再次从同一 worktree 和 wrapper 启动无 qualification 特权的正式 launcher；服务存活期间运行 doctor，确认 ready、capability、
   身份和 structured probe 均通过。
5. 使用可验证、只影响本任务进程且能让 launcher 完成 receipt 清理的关停方式。§4 的 receipt + exact PID TERM 流程是首选，但允许
   经测试的等强 orchestration。最后复核无本任务 server/port/live receipt/private temp；任一残留都按失败收口，不得保留晋级。

### E. 文档、审查与交付

1. 成功时精简更新两份 WBS 当前状态/下一步，向 WBS-COMPLETED 追加一次 Turn A 完成证据，并写一个精炼 agent log；明确没有做
   L7/Local M3/8k/Rust/Docker/cloud API。失败时只更新 plan 当前状态与 agent log；只有形成持续阻塞时才精简更新 WBS，绝不写
   WBS-COMPLETED 成功项。
2. 对工作包 2 的 `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS-COMPLETED.md`、Plan 022 做只读一致性复核；
   当前已一致则零修改。
3. 检查 `git diff --check`、tracked 大文件/模型、受保护目录、主仓 ignored 配置状态、主工作区与全部 worktree 状态；不得把
   `rondo.local.toml`、私有 metrics、raw 日志或 GGUF 加入 Git。
4. 执行者在任务分支提交供独立审查，但不得合并 `main`、推送或删除 worktree/分支。交付 reviewer 时给出 commit/diff、focused
   test 计数、真实 evidence allow-list、正式 doctor JSON、最终清理结果和全部未运行项；由 reviewer 独立验收后再决定合并交付。

## 6. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-14：规划者读取根规则、README、当前/方向 2 WBS、Plan 模板、Plan 015—018、Plan 018 日志/审计快照、
  local-approval launcher/client/doctor/identity/config/runtime bridge、现有 focused tests、b10333 frozen source 的 props/slots/metrics/
  timing/offload 实现，并完成一次独立只读代码审查。
- 2026-08-14：确认主工作区 clean `main@6cc9f11`，相对 `origin/main` ahead 1；该提交是已存在的 Plan 022 文档收口。
  从当前 local main 创建 `.claude/worktrees/023-local-4k-qualification` 和分支 `023-local-4k-qualification`；未合并、未推送。
- 2026-08-14：确认唯一 GGUF 与 exact CUDA runtime 位于主仓 shared ignored `eval-data/`；真实 `rondo.local.toml` 为普通
  mode 0600 文件，但 local model 仍是旧 CPU/context-zero 合同。linked worktree 的 loader 按 Git common dir 读取主仓这份配置，
  因而配置迁移必须直接发生在主工作区文件。
- 2026-08-14：确认 Plan 018 CUDA source build 的 build-info 是 `1 (0865990)`，现有 model-backed client/doctor 仍硬校验
  CPU release `10333`/8 位 commit；这是 Turn A 正式复验前必须修正的 eval/Python 阻断。
- 2026-08-14：确认当前仓库没有 model-backed qualification evidence loader；CUDA base lock/parser 与 `inspect_runtime()` 有意固定
  为 `linux_cuda_built_model_unvalidated/not_run`。Plan 022 工作包 2 的四处当前文档已由本地 main 收口，无待同步漂移。
- 2026-08-14：独立审查确认 b10333 `/metrics` predicted counter 不能代表 TTFT，并补齐 source-build identity、同 checkout
  watchdog、清理、WSL 显存采样和 `just eval-lock` 边界；随后按用户反馈把 Plan 从“规定内部实现”瘦身为 9 条结果型硬约束，
  将 CLI/文件名/字段布局、`/slots`、PID/TERM 和完整 RunSpec provenance 降为可替换的推荐方案。

- 2026-08-14：用户补齐授权（独占 GPU、默认两次模型生命周期、上限 4 次、可改主仓 ignored `rondo.local.toml`）。
  完成 §5 A—C：主仓 ignored 配置按字段迁移到 exact GGUF + 4k `auto`/`fit=on`（`providers`/`paid_eval`
  规范化 digest 与 0600 权限均未变）；新增 `model_backed.py`（合同常量、严格 evidence schema、单向 capability 投影）
  与 `qualification.py`（受限生命周期与窄 CLI）；修正 CUDA/CPU 服务身份；focused tests 112 项全绿。
  在真实 watchdog lease 下证明正式 launcher 对未晋级能力在 `Popen` 前拒绝。
- 2026-08-14：执行 §5 D。共消耗 4 次模型生命周期（授权上限）：前 3 次因本任务代码缺陷失败并已修复
  （wrapper 必须用绝对路径调用、b10333 缓冲 stdout 需在进程退出后再读 load 日志、GPU 独占检查误把自身服务当外来进程），
  每次失败均先修复并重跑 focused tests，未用重试掩盖。第 4 次真实加载成功：exact GGUF 装载、CUDA 启用、
  服务 `build_info` 为 `b1-0865990`、`/props` 上下文 4096、`total_slots` 1、model_path 与冻结 GGUF 一致。
- 2026-08-14：**所选真实 `E_final` 在 4k 合同下不可服务**。其 static payload 经服务端 tokenizer 实测 5,313 input tokens，
  超过 4096 上下文，llama.cpp 返回 exceed-context 错误，没有产生结构化判定。按 §3.4 未写入任何证据，
  能力保持 `linux_cuda_built_model_unvalidated`。本次现场四项清理全部成功（进程、端口、receipt、私有临时对象）。
- 2026-08-14：独立审查（`agent_log/2026-08-14-061059-plan023-independent-review.md`）判定不通过，提出 F1—F3。
  已完成 remediation：qualification 输入改由受跟踪 selector 预绑定唯一 path、`E_final`/meta SHA、review id
  与期望 Guardian 模型/effort，并复用生产 `_read_safe_evidence_file` 与 `_validate_guardian_meta`、
  与受跟踪 `eval/results/runs.jsonl` 交叉核对，payload 直接由冻结 bytes 构造（消除二次读取 TOCTOU）；
  VRAM 采样改为全窗口 fail-closed（首个采样异常、线程未退出、请求窗口内出现 foreign compute process 或零样本
  都不得晋级）；权威文档收敛为“已测这一条 5,313 tokens 不可服务”，删除未证实的全体结论。focused tests 115 项全绿。

### 当前工作

- Turn A 在 §5 D 的结构化判定步骤按合同失败收口，并已完成一次 review remediation；不进入 Turn B。

### 本任务剩余步骤

- 无。文档收口与任务分支提交已完成，等待独立复审。

### 阻塞项

- **所选真实 `E_final` 与 4k 合同不可同时满足**（§3.2 与 §3.5 在该样本上冲突）：实测 5,313 input tokens > 4096，
  结论来自服务端自身的 token 计数，不是估算。**全部 47 条真实归档是否都超出 4k 尚未验证**；
  字符长度与该 tokenizer 的 token 数不严格单调，不能据此推断，普查需单独授权且只做 tokenizer-only 计数。
- 模型生命周期已用满授权上限 4 次，本任务不再执行真实运行；上下文预算属于跨任务决定，按 §5.E 只记录事实，
  路线由 `doc/WBS.md` 与 `doc/WBS/local-approval-model.md` 承接。

### 当前验收状态

- 未晋级。能力仍为 `linux_cuda_built_model_unvalidated`，`model_backed_structured_output` 仍为 `not_run`，
  未生成 model-backed evidence。已完成：ignored 配置迁移、qualification 与证据设施、focused tests、
  正式 launcher 拒绝证明、真实模型首次成功加载与身份/上下文核验、现场完全清理。
  未完成：真实结构化判定、显存峰值/首 token/总耗时指标、capability 晋级、晋级后正式 launcher + doctor 复验。

### 交接边界

- 本任务成功后冻结此计划；下一步只链接 `doc/WBS.md` / `doc/WBS/local-approval-model.md` 的 L7/Local M3 条目，
  不在本计划继续维护 Turn B、8k 或训练路线。

## 7. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 保留 Plan 018 CUDA base lock 原样，新增独立 v1 model-backed evidence | base lock 是形成时点的 model-free 构建/设备事实；改写会抹掉历史且现有 parser 会拒绝 | lock、capability、历史 | 已采纳 |
| 002 | qualification 使用显式受限入口；独立窄 CLI 是推荐而非唯一实现 | 确保 unvalidated 正式路径继续 fail-closed，同时允许执行者采用更贴合现有架构的 orchestration | launcher、qualification、tests | 已采纳 |
| 003 | capability 是 exact runtime + model + 4k serve/request contract 的组合投影 | 仅 runtime build 或配置声明不能证明真实模型服务；未来 8k 仍需独立验收 | evidence loader、doctor | 已采纳 |
| 004 | TTFT 保持 non-streaming 并真实观察首 token，禁止 b10333 `/metrics` predicted-token 口径；`/slots n_decoded` 是已验证首选 | 锁定有效测量事实，不锁死执行者可能找到的更干净等强方案 | metrics、qualification | 已采纳 |
| 005 | CUDA service build identity 从 exact base lock 派生 `1/0865990`，CPU 仍保持 `10333` 口径 | source build 与 release bundle 的真实输出不同；当前硬编码会误拒绝真实 CUDA 服务 | client、doctor、tests | 已采纳 |
| 006 | ignored 配置只直接修改主工作区一份，不在 linked worktree 复制 | loader 通过 Git common dir 设计为所有 worktree 共用本机配置；复制会制造不生效的假配置 | config、执行交接 | 已采纳 |
| 007 | tracked evidence 只保存 identity、数值和 response digest，不保存 E_final/rationale/tag 原文 | 能证明合同与 schema，又不把 evidence/潜在敏感信息写入 Git 或普通日志 | evidence、日志 | 已采纳 |
| 008 | 工作包 2 四处文档当前一致时保持零修改 | 当前 local main 已完成 Plan 022 最终状态同步，重复改写会堆叠历史并制造噪声 | WBS、Plan 022 | 已采纳 |
| 009 | 真机阶段等待用户补充至多两次模型生命周期授权 | qualification 与正式 launcher 复验按字面需要两个独立启动，不能自行扩大“一次”授权 | 真实执行 | 已确认：用户授权默认两次、上限 4 次，实际已用满 4 次 |
| 010 | 硬约束收敛为 9 条结果/安全门，内部模块、schema 布局、采样与关停编排移入软建议 | 避免资格框架压过首次 4k 验证本身，同时保留 capability 晋级与 fail-closed 的不可妥协条件 | 整体实现合同 | 已采纳 |
| 011 | 合同常量、证据 schema 与 capability 投影集中在新的 `model_backed.py`，qualification 生命周期单独放 `qualification.py` | 投影需要被 launcher/doctor 复用，生命周期不需要；拆开可避免 launcher 与 qualification 的循环导入，并让 §5.B.1 的“单一漂移源”落在一个不依赖 launcher 的模块上 | 实现结构 | 偏离 §4 推荐的单 CLI 布局，等价性由 focused tests 覆盖 |
| 012 | 服务身份改为精确比较 `/props.build_info`（CUDA `b1-0865990`、CPU `b10333-08659901c`），不再用 build 号/commit 子串 | b10333 的 `build_info` 就是 `b<number>-<commit>`，精确串比子串更强，且一次修好 CUDA source build 被 CPU 口径误拒的阻断 | client、doctor、router probe、fake server | 已采纳 |
| 013 | CUDA 设备名取自已验证的冻结 device probe，不从 server 日志正则提取 | `inspect_runtime` 已硬性要求该 exact 设备串，日志措辞则随版本变动；日志只负责 offload 计数这一项无法从 API 取得的事实 | qualification 观测 | 已采纳 |
| 014 | load 事实在服务退出后再读私有日志 | b10333 的 INFO 日志走全缓冲 stdout，运行中读到的文件缺少 load 段；退出后缓冲落盘，offload 计数才完整 | qualification 生命周期 | 修复第 1—2 次生命周期失败 |
| 015 | GPU 独占检查在服务启动后排除本任务自身进程树 | WSL 的 `--query-compute-apps` 会列出本任务刚启动的 llama-server，原判据会把自己判成外来占用 | qualification 前置 | 修复第 3 次生命周期失败 |
| 016 | request-contract digest 覆盖采样与结构化 schema，但不含 `timeout_seconds` | 该值只是客户端等待时长，不改变模型、采样或被校验的 schema；纳入会让无关的超时调整静默作废 capability | evidence identity | 偏离 §4“覆盖整张 request 表”的推荐 |
| 017 | 结构化判定失败时，从私有日志抽取服务端自身的 token 计数作为非敏感 blocker facts | 让“装不下”这类合同冲突给出可行动的确切数字，且不新增第二条 evidence 请求、不落任何证据内容 | 失败语义 | 已采纳 |
| 018 | 新增受跟踪 selector `eval/locks/local-approval-qualification-evidence-v1.json` 预绑定唯一 `E_final`，而不是直接复用 `load_guardian_evidence_bundle()` | 该生产 loader 要求目录名等于 review id，`eval-data/runs/` 的归档用序号目录，直接调用会拒绝全部真实 bundle；窄 selector 仍复用其 `_read_safe_evidence_file` 与 `_validate_guardian_meta`，并新增 path/双 SHA/review id 预绑定与受跟踪 run ledger 交叉核对 | evidence source gate | 修复审查 F1 |
| 019 | 期望 Guardian 模型/effort 取自受跟踪 `eval/results/runs.jsonl` 的该 run 记录 | 提供独立于被验文件的第二来源；伪造归档需要同时改动受 Git 跟踪的账本才能通过 | evidence source gate | 修复审查 F1 |
| 020 | VRAM 采样窗口整体 fail-closed，并在采样线程内持续监控 foreign compute process | 设备级归因只有在“每次采样都成功且全窗口独占”时才成立；已经采到正 delta 不能补偿后续缺口 | 指标与晋级 | 修复审查 F3 |
