# Plan 017：本地审批 llama.cpp 运行路线调查与重新冻结决策

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

## 1. 目标

### 最终目标

在不下载大型运行时或模型资产、不安装工具链、不构建、不启动模型/GPU/Docker，也不修改运行时代码的前提下，基于
llama.cpp、NVIDIA 与 WSL 的权威资料和 RONDO 当前合同，决定继续自行构建 `b10333` Linux CUDA、升级到一个精确新版，
或采用另一条更省事且可稳定接入 RONDO 的官方运行路线，并给出下一任务可直接执行的精确入口。

### 完成/验收标准

- 核实 `b10333` 之后官方 release 是否提供 WSL/Linux x86_64 可用的 CUDA 预编译资产；若有，冻结 exact tag、commit、
  asset name/size、CUDA 运行时组成、驱动要求与 WSL 边界。
- 以冻结源码/官方文档确认推荐候选对 Mistral3、Q4_K_M、Responses API、外部 Jinja 模板及 Plan 016 两阶段参数的支持；
  未运行的二进制、GPU、GGUF 结论明确标为待实测。
- 比较 b10333 源码构建 CUDA、新版官方 Linux CUDA、官方 Linux Vulkan、Windows CUDA server + WSL、官方 CUDA Docker
  等主要路线的安装、维护、RONDO 集成、8GB 适用性和故障恢复成本，形成唯一建议而非候选清单。
- 给出 runtime lock、launcher、doctor、identity、配置和 focused tests 的迁移范围；不在本任务实际升级或修改生产代码。
- 形成日期冻结决策档案，运行轻量链接/文档/Git 一致性检查，提交、合并本地 `main` 并推送 `origin/main`；不用 CI/PR。
- Plan 015 的唯一 GGUF 与 `download_ready_blocked_on_user_approval` 状态不变。

## 2. 范围

### 允许修改

- `plan/017-local-approval-runtime-route-decision-execplan.md`
- `doc/audit-snapshots/` 下本任务日期冻结决策档案
- `doc/WBS/local-approval-model.md` 中一段简洁当前事实
- `agent_log/` 下本任务精炼日志

### 不允许修改

- `mydev/`、`eval/`、运行时 lock、launcher、doctor、identity、测试和 `rondo.local.example.toml`
- Plan 015 冻结的 GGUF 身份、下载命令和审批状态；Plan 016 已验收的模板/launcher 合同
- canary worktree、campaign、结果、调度、paid profile、共享 eval 状态或既有并行修改
- 系统/宿主配置及任何远端资源

### 不允许读取/查看

- `.env.local` 内容及任何 token/API key 明文、长度、前后缀或哈希
- 私有测评数据和与本任务无关的个人文件

## 3. 硬约束

1. 本任务只调查和决策，不实际升级、安装 CUDA/驱动/编译器/依赖，不下载大型运行时或模型权重，不构建或启动
   llama.cpp，不运行模型/GPU/Docker/Cargo/Bazel/just/CMake/Make。
2. 只读网络调查优先使用 llama.cpp release/source/workflow、NVIDIA CUDA on WSL 与 Microsoft WSL 等官方资料；社区说法
   不得替代关键兼容或依赖事实。
3. exact release 必须冻结为 tag、peeled 40 位 commit 和精确资产元数据；release 页面出现资产不等于当前 WSL 已实际可用。
4. 不为追新而升级；只有某路线明确减少安装、构建和长期维护成本且 RONDO 集成边界可控，才可推荐迁移。
5. 官方事实、仓库源码事实、工程判断和待 GPU/model-backed 实测分开书写；不把静态参数存在、资产清单或文档声明写成
   本机运行通过。
6. 不重新选择基础模型或 GGUF；HF CLI 只用于必要的小型只读元数据核对，禁止任何权重下载或远端写操作。
7. Git 中不得出现二进制、模型权重、依赖包、凭据或意外大文件。

## 4. 软性建议

- 先从 GitHub release API 找出首个/合适的 Linux CUDA 资产，再围绕少量候选做源码与 workflow 复核，避免穷举每个版本。
- 推荐路线以日常“下载、解压、锁闭包、启动、升级/回滚”的总成本为主，性能只判断是否足够支撑 RTX 4060 8GB 的
  4k smoke/8k baseline，不做无模型 benchmark 推测。
- 若预编译 CUDA 包已自带所需 CUDA user-mode 库，区分“无需 CUDA Toolkit”与“仍需要兼容的 Windows NVIDIA driver”。
- 迁移建议保持最小：复用 Plan 016 参数、模板、receipt 和 fail-closed 边界，只替换版本绑定与真实 runtime closure。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-12：读取根规则、README、当前/方向 2 WBS、Plan 015/016、模型冻结档案、开发环境、runtime lock、
  launcher/doctor/identity/config 与 focused tests 的版本绑定。
- 2026-08-12：确认主工作区 `main...origin/main` 干净且均为
  `7aee662c4218e7bc5385939e20105af2fd5ac298`；保护 `0811-plan014-post-audit` 的并行未提交修改。
- 2026-08-12：创建独立 worktree `.claude/worktrees/0812-plan017-runtime-route`，分支
  `0812-plan017-runtime-route`。
- 2026-08-12：以 GitHub release API 核对 `b10333` 后 18 个 release；截至冻结上限 `b10375`/commit
  `ba360efe1f574ebae727aad64112d18ecedca85a`，官方仍未发布 Linux/Ubuntu x86_64 CUDA 预编译资产。
- 2026-08-12：复核 b10375 的 Mistral3、Q4_K_M、Responses、Jinja 和 Plan 016 全部参数入口；静态合同仍在，但
  `--load-mode` 默认值从 `mmap` 漂移为 `auto`，没有发现能抵消迁移成本的当前需求修复。
- 2026-08-12：依据 NVIDIA/WSL、Microsoft 与各运行方式官方资料完成 Linux CUDA source、Vulkan、Windows CUDA、
  CUDA Docker 和 Ollama 的日常控制面比较，并逐项映射 RONDO 当前 launcher/lock/doctor/identity/test 复用与改造面。
- 2026-08-12：冻结唯一建议为保留 exact b10333、在下一任务完成项目内 Linux CUDA source build；形成日期决策档案和
  Plan 018 精确入口。所有 binary/GPU/model-backed 结论保持未验收。
- 2026-08-12：独立终审无阻塞 finding；现场复核并完善 Windows CUDA 三包成本、device probe 的 GPU 边界、CPU/CUDA
  lock 选择与配置切换时点、CUDA 12.6.2 归因和可复现链接。`git diff --check`、lock/Plan 015 精确身份和意外大文件检查通过。
- 2026-08-12：研究文档提交 `f3c00ece26cf4cf9b9f48302c3ad38372a7effb4`，首次以 merge
  `e99a570d505c0e26b8fd9c3d9c3af458ee83b829` 合并本地 `main` 并推送远端；本 closure 只记录交付状态。
- 2026-08-12：以 b10333 exact commit 复核官方 Ubuntu CUDA workflow（blob `2528b18573a78a9a8e99783acc7b9f0b81688ec7`）
  和 CUDA CMake（blob `d3953eee962e7cdc8cd39e6e8c062bced167e200`）。确认 CUDA job 只有 configure/build、没有测试命令；
  workflow 还使用 permissive linker flag 与 `GGML_CUDA_CUB_3DOT2=ON`，后者会 FetchContent CCCL `v3.2.0`。Plan 018
  交接已增加选择/冻结门，不改变保留 b10333 的路线。
- 2026-08-12：勘误提交 `93811e807abeae4217136067c374fbdc7d304396`，首次以 merge
  `feb4777a8d062d48df828003f535500467016f4c` 合并本地 `main` 并推送远端；本 closure 只同步最终状态。

### 当前工作

- CUDA workflow 勘误、轻量检查与 Git 交付已完成；不进入 Plan 018、权重下载或 GPU/model-backed 执行。

### 交接边界（后由 Plan 018 完成）

- 本计划只完成 runtime 路线决策与 build-ready 边界。Plan 018 后来按该决策完成 exact CUDA runtime 与
  model-free 验收；model-backed 不属于本计划，当前路线只见 `doc/WBS/local-approval-model.md`。

### 阻塞项

- 无。二进制、GPU 与模型实测不属于本调查。

### 当前验收状态

- `errata_complete_git_delivered`。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 不预先锁定新版或 CUDA/Vulkan/Windows/Docker 路线 | 用户关注总维护成本；是否升级必须由 live release 与当前 RONDO 合同共同决定 | 调查与最终建议 | 已采纳 |
| 002 | Plan 015 的 GGUF 下载状态保持 `download_ready_blocked_on_user_approval` | 运行时路线调查不改变权重身份或单独下载审批门 | Plan 015 与交付措辞 | 已采纳 |
| 003 | 唯一运行路线继续冻结为 b10333 Linux CUDA 项目内源码构建 | b10375 仍无官方 Linux CUDA 包，升级不能省掉 Toolkit/构建；现有 Plan 016 合同已按 b10333 收口 | Plan 018 与 L2 runtime | 已采纳 |
| 004 | 不以 Vulkan、Windows server、CUDA Docker 或 Ollama 替代当前主路线 | 各路线分别缺少 WSL NVIDIA Vulkan 的稳定设备证据，或引入跨 OS、容器/canary、协议/模板/identity 新控制面 | 备选路线与维护边界 | 已采纳 |
| 005 | 保留 CPU runtime/lock；CUDA runtime 使用新 ignored 路径和独立 lock，并复用 receipt v2/模板/config 合同 | CPU 资产是 model-free 回滚入口；CUDA backend/host closure 与 capability 需要独立真实证据，但无需重做已验收配置和身份 schema | 下一实现任务 | 已采纳 |
| 006 | Plan 018 不直接复制官方 CI 的 CUB/linker 两项参数，先关闭可复现依赖与严格链接决策门 | 官方 CUDA job 未运行测试；CUB 开关会按 tag FetchContent CCCL，permissive linker flag 会放宽 undefined-symbol 检查。二者都缺少本机真实构建证据 | Plan 018 configure/build 与 source freeze | 已采纳 |
