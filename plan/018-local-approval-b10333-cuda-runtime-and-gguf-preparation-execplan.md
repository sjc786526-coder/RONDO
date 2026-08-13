# Plan 018：唯一 GGUF 下载与 b10333 Linux CUDA runtime model-free 验收

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

## 1. 目标

### 最终目标

在用户已经明确授权的范围内，串行完成 Plan 015 冻结的唯一 GGUF 下载与静态校验，并以项目局部 CUDA Toolkit
构建 exact llama.cpp `b10333` Linux CUDA runtime；补齐独立 runtime lock、CPU/CUDA binary-to-lock 有限映射、
动态依赖闭包、doctor/capability 和 launcher 拒绝合同，只执行不加载 GGUF、不推理的 CUDA device probe，最终状态精确为
`linux_cuda_built_model_unvalidated`。

### 完成/验收标准

- 唯一 GGUF 位于冻结目标路径，是非符号链接普通文件，精确为 `5,198,387,456` bytes，完整 SHA-256 为
  `7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a`；Git 不跟踪该权重或意外大文件。
- CUDA Toolkit 使用项目局部 ignored 路径，冻结 exact `12.6.2` 来源、下载文件大小与 SHA-256；不安装 Linux display
  driver，不修改 Windows driver、系统包、全局 `/usr/local/cuda` 或宿主配置。
- llama.cpp source 精确为 tag `b10333`、commit `08659901c43b51de735740f1cf61bb82fbe0c4e4` 的 clean tree；
  configure/build argv、编译器、CMake、Make/Ninja、glibc、架构 `89-real` 与实际 CMake cache 均冻结。
- 构建产物位于 `eval-data/tools/llama-b10333-cuda-linux-x64/`；`llama-server --version`、`--help` 成功，
  model-free `--list-devices` 识别 RTX 4060 Laptop GPU。
- ELF/RPATH/RUNPATH 及递归 DT_NEEDED 闭包完整；项目库、CUDA user-mode libraries 与 WSL `libcuda.so` 无 missing
  dependency，且调用者无需提供 `LD_LIBRARY_PATH`。
- 新 `eval/locks/llama-cpp-b10333-cuda-linux-x64.json` 能严格验证 source/toolchain/build/runtime/依赖身份；现有
  CPU runtime/lock 保持可用，两个 exact binary path 只映射到各自 exact lock，其他路径 fail-closed。
- doctor/capability 对 CUDA runtime 准确返回 `linux_cuda_built_model_unvalidated`，structured model-backed 状态保持
  `not_run`；production launcher 继续拒绝未完成 exact-model 验收的正式服务。
- 相关 focused/model-free tests、lock/JSON/TOML 一致性、`git diff --check`、权重与意外大文件扫描通过；不把
  device probe 写成 GGUF、模型服务、4k/8k 或结构化审批验收。

## 2. 范围

### 允许修改

- `plan/018-local-approval-b10333-cuda-runtime-and-gguf-preparation-execplan.md`
- Plan 015 的当前状态与 GGUF 下载完成事实
- `eval/locks/` 下新增的独立 CUDA runtime lock
- `eval/rondo_eval/local_approval/` 中 runtime lock、closure、doctor/capability、launcher 有限映射所需的最小实现
- `eval/tests/` 下与上述合同直接相关的 focused/model-free tests
- `rondo.local.example.toml` 中完成后切换到 exact CUDA binary 的受跟踪示例路径
- `doc/WBS.md`、`doc/WBS/local-approval-model.md` 中受影响的精简当前事实
- `doc/audit-snapshots/` 下本任务必要的 CUDA/GGUF 日期冻结快照与 `agent_log/` 下本批精炼日志
- ignored `eval-data/models/`、`eval-data/sources/`、`eval-data/toolkits/`、`eval-data/build/`、
  `eval-data/tools/` 中本任务明确创建的唯一权重、源码、Toolkit、构建目录和 CUDA runtime

### 不允许修改

- README 的模型选择、Plan 015 冻结的 repo/revision/file/size/SHA、Plan 016 的 launcher 参数/官方模板/receipt v2 设计
- 现有 CPU runtime 内容与 `eval/locks/llama-cpp-b10333.json` 的已验身份
- `mydev/` 产品源码、L2a、B7、训练、数据合成、paid/canary 结果或其他研究方向
- 来源不明的 cache、权重、Docker 资产、worktree、分支或用户/并行任务修改
- 系统 CUDA、Linux/Windows display driver、`/usr/local/cuda`、全局工具链、系统服务或项目外配置

### 不允许读取/查看

- `.env.local` 内容
- HF token 明文、长度、前后缀或哈希
- holdout 内容、私有测评数据和与本任务无关的个人文件

## 3. 硬约束

1. 两个资源任务严格串行：先完成并校验唯一 GGUF，下载进程完全结束后才开始 Toolkit/source/build；不得同时下载和构建。
2. GGUF 只允许 repo `bartowski/mistralai_Ministral-3-8B-Instruct-2512-GGUF`、revision
   `ad82bf81321f4b22de70014ecd5135730115f6a8`、文件
   `mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf`。不得下载任何其他 GGUF、safetensors、adapter、tokenizer
   或 mmproj。下载前必须重新通过 exact dry-run、Windows `C:` 余量和无 Docker/build/model 进程门禁。
3. 不加载 GGUF、不启动 model-backed server、不执行推理、不生成 token，不运行 4k/8k smoke；下载后只做普通文件、
   非 symlink、精确字节数和完整 SHA-256 静态验证。
4. CUDA 优先使用 b10333 官方 Ubuntu CUDA workflow 对应的 exact `12.6.2`；只允许官方 Toolkit source 和项目局部
   toolkit-only 安装。若项目局部安装不可行、需要 sudo/apt/系统修改，立即停止并报告。
5. 构建 exact b10333/commit `08659901…`，目标架构固定 `89-real`。所有 configure/build 必须经过
   `mydev/scripts/with-build-lock.sh` 的机器全局锁、cgroup 和资源看门狗；Windows `C:`、项目占用、内存、swap 或计数器
   不可用时 fail-closed。`CARGO_TARGET_DIR` 仅为满足共享看门狗合同，必须留在受监控的 RONDO 项目根内。
6. 构建前后不得存在 Docker、Cargo/Rust、CMake/Make/Ninja 或真实本地模型加载/推理并发；本任务不运行 Docker、Cargo、
   Bazel 或无关重型任务。
7. `GGML_CUDA_CUB_3DOT2` 不盲目继承。若启用，必须把 CCCL `v3.2.0` 解析为 exact 40 位 commit 并在项目内冻结来源，
   configure 不得发生未冻结网络抓取；若不启用，以真实 strict configure/build 成功证据记录相对官方 workflow 的差异。
8. 默认不使用 `-Wl,--allow-shlib-undefined`。只有 strict link 实际失败、错误与根因已保存且该 flag 被证明必要时才能加入
   冻结命令；不得用它隐藏未知 missing dependency。
9. runtime 必须通过 RPATH/RUNPATH 自包含定位项目内 CUDA user-mode libraries；不得要求调用者设置
   `LD_LIBRARY_PATH`。WSL `libcuda.so` 属宿主 driver 映射，必须按真实加载闭包冻结 canonical path/identity，但不得复制或改写。
10. 保留 CPU runtime/lock。配置 binary 只允许两个项目内 exact 路径并各自绑定对应 lock；新 CUDA runtime 在 model-backed
    4k 验收前只能投影 `linux_cuda_built_model_unvalidated`，launcher 必须继续拒绝正式服务。
11. model-free `--list-devices` 会访问 GPU/driver，只能证明 CUDA runtime/device 枚举；不得表述为模型加载、offload、显存、
    性能、Responses、模板或 structured output 验收。
12. 大型源码、Toolkit、installer、build、runtime 与 GGUF 必须保持 git-ignored；不得提交二进制、凭据、机器私有配置或
    意外大文件。

## 4. 软性建议

- Toolkit 采用官方 runfile 的 `--toolkit --toolkitpath=<project-local>` 无 sudo 安装路径；先冻结 installer URL/size/SHA，
  再运行其 toolkit-only 模式并检查未触碰系统路径。
- 首次 configure 省略 `GGML_CUDA_CUB_3DOT2` 与 permissive linker flag；只有真实证据要求时才加入最小、冻结的例外。
- runtime bundle 只平铺 server 运行所需项目库与 CUDA user-mode 库，使用 `$ORIGIN` 相对 RUNPATH；build/source/toolkit
  作为可重建资产另存 ignored 目录，不塞入运行闭包。
- 复用当前 CPU lock validator 和 focused test 结构，新增 backend-specific schema 字段而不建立通用制品管理框架。
- 下载和长构建期间保留简短阶段更新；资源看门狗输出写入项目 ignored metrics，不把大日志或本机绝对临时状态入库。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-13：读取根规则、README、当前/方向 2 WBS、数据布局、Plan 模板、Plan 015/016/017、两份相关审计快照及
  runtime/build-lock 入口；确认用户已明确授权唯一 GGUF、项目局部 CUDA Toolkit、exact b10333 source/build 和 device probe。
- 2026-08-13：确认主工作区为 clean `main`/`ad594eb1cb346ba7e9fc9333fd0c9d36d4a358fa`，全部既有 worktree
  干净；先将落后远端的既有 74 个提交推送并核实 `origin/main` 精确为该 SHA。
- 2026-08-13：创建独立 worktree `.claude/worktrees/0813-plan018-cuda-runtime`，分支
  `0813-plan018-cuda-runtime`。
- 2026-08-13：GGUF 下载前 exact revision 单文件 dry-run、Windows `C:` 余量、Docker/构建/模型进程门禁通过；
  以单 worker、单 Xet range 下载唯一冻结文件。下载后实测为普通非 symlink 文件、`5,198,387,456` bytes，完整 SHA-256
  精确为 `7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a`；未加载模型，Git 未跟踪权重。
- 2026-08-13：从 NVIDIA 官方 CUDA 12.6.2 archive 下载 `cuda_12.6.2_560.35.03_linux.run`；实测
  `4,446,677,374` bytes、MD5 `dcba85e2d49d7e6d93d8626f708276a4`、SHA-256
  `3729a89cb58f7ca6a46719cff110d6292aec7577585a8d71340f0dbac54fb237`。仅以 `--toolkit` 安装至项目
  `eval-data/toolkits/cuda-12.6.2/`；没有 sudo/apt、Linux display driver、`/usr/local/cuda` 或全局 `nvcc` 变更。
- 2026-08-13：llama.cpp source 为 clean tag `b10333`、commit `08659901c43b51de735740f1cf61bb82fbe0c4e4`、
  tree `9ae780f13650ac3d45e4e345f208163ad744dd6d`。configure/build 均经项目 build lock/watchdog，Ada
  `89-real` strict link 成功；没有启用 CUB 3DOT2/CCCL 或 permissive linker flag，`llama-server` 构建状态为 0。
- 2026-08-13：CUDA runtime 已平铺到冻结路径；所有 9 个 ELF regular file 与 14 个 symlink、DT_NEEDED、RUNPATH、
  project Toolkit user-mode libraries、WSL `libcuda.so.1` 和系统依赖闭包均冻结且无 missing dependency。清除
  `LD_LIBRARY_PATH` 后 `--version`/`--help` 成功；宿主 `--list-devices` 识别 RTX 4060 Laptop GPU（8187 MiB）。
- 2026-08-13：新增独立 CUDA lock、CPU/CUDA exact path selector、ELF/toolchain closure、backend-neutral doctor/client
  receipt 接线与回归测试。使用受跟踪示例配置并保持 model path 为空的受控 model-free 复现中，doctor/router 返回
  `linux_cuda_built_model_unvalidated`；正式 launcher 对此中间能力仍在 Popen 前拒绝。GGUF 从未加载，model-backed
  structured output 保持 `not_run`。
- 2026-08-13：focused local-approval tests 58/58、config hardening 8/8、config/artifacts 30/30 通过；独立代码与
  文档收尾审查的 actionable findings 已闭合，`git diff --check`、JSON/Python 静态检查与 ignored 大资产检查通过。

### 当前工作

- Plan 018 已完成：唯一 GGUF 静态完整性与 CUDA runtime model-free 能力均已验收，Git 提交、合并、推送及真实远端
  SHA 核验已经闭合。

### 交接边界

- 本计划终止于 GGUF 静态完整性和 CUDA model-free 验收；不维护真实配置、4k/8k 或 L3/L4 的后续顺序。
  当前路线只见 `doc/WBS/local-approval-model.md`。

### 阻塞项

- 无。

### 当前验收状态

- runtime capability 为 `linux_cuda_built_model_unvalidated`：唯一 GGUF 静态验收和 CUDA model-free 验收完成；模型从未
  加载，4k/8k 均未运行。
- 当前机器实际配置尚未迁移：直接使用真实 ignored `rondo.local.toml` 运行 doctor 返回 `configuration_error`（exit 64），
  具体原因为 `local_model context_size is outside its allowed range`。这不改变已验 runtime capability，也不构成服务就绪。

## 6. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 两个资源任务固定为 GGUF 下载/校验在前，CUDA Toolkit/source/build 在后 | 用户要求串行，且先闭合唯一已冻结资产可降低恢复歧义 | 下载、构建、Plan 状态 | 已采纳 |
| 002 | CUDA runtime 与现有 CPU runtime/lock 并存，binary path 只做两项有限映射 | 保留 model-free 回滚入口，避免 backend 身份由可伪造配置声明决定 | runtime lock、launcher、doctor、tests | 已采纳 |
| 003 | `linux_cuda_built_model_unvalidated` 是本任务唯一成功终态 | device probe 不加载模型，不能晋级生产服务能力 | capability、doctor、交付措辞 | 已采纳 |
| 004 | 默认省略 CUB 3DOT2/CCCL 和 permissive linker flag，除非真实构建证据要求 | 两项分别引入未冻结网络依赖或放宽链接检查，官方 CI 又没有测试证据 | configure/build/source freeze | 已采纳 |
| 005 | 接受 shallow source build 的 `--version` build number `1`，但要求 7 位 commit、binary hash 与完整 source/build lock 同时匹配 | b10333 release bundle 显示 10333，exact tag source build 的真实输出是 `version: 1 (0865990)` | version/router probe、lock、tests | 已采纳 |
| 006 | model-free loopback probe 显式禁用环境代理 | 当前宿主代理会把 127.0.0.1 请求送往代理并产生 502；本机 health/props 必须直连 | router probe、doctor | 已采纳 |
