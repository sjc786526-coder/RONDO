# Plan 016：本地审批 model-free launcher 合同、模板冻结与 CUDA 构建前交接

> 本计划是任务的稳定约束文档。
> 除“当前状态”和“关键决策记录”外，其他部分在执行期间默认不得修改。
> 如果必须改变目标、范围、硬约束或完成标准，应暂停执行并请求用户确认。

## 1. 目标

### 最终目标

在不下载模型权重、不安装或构建 CUDA/llama.cpp、不启动模型/GPU/Docker，也不运行 Cargo、Bazel 或 just 的前提下，
冻结 Ministral 当前官方 chat template，补齐 llama.cpp `b10333` 两阶段 4k smoke/8k baseline 的最小配置和命令合同，
让 launcher receipt 可验证地绑定实际服务参数，并形成下一阶段 Linux CUDA runtime 与 exact GGUF model-backed smoke 的
build-ready 交接。

### 完成/验收标准

- 官方 `chat_template.jinja` 以精确 repo/revision/文件名、字节数和 SHA-256 冻结为受跟踪小型资产与锁；launcher 只接受
  工作区允许目录内的普通非符号链接文件，并逐字节验证 SHA-256，不回退 GGUF 内嵌模板。
- 严格配置可表达 `context_size`、原生 `gpu_layers = auto|all|非负整数`、`fit`、batch/ubatch、F16 K/V、no-mmproj、
  template file/SHA、Jinja、flash attention 和 `parallel = 1`；未知/缺失/错误类型/越界/不支持值 fail-closed，bool 不作整数，
  `ubatch_size <= batch_size`。
- 完整关键命令测试分别证明 4k smoke 使用原生 auto offload + fit on，8k baseline 使用 all offload + fit off；两者保留
  loopback、offline、no autoload/no UI、tools disabled、无自动重试和相同模板条件。
- launcher identity schema 显式升级并绑定预期服务配置/命令；修改任一关键服务参数后旧 receipt 被拒绝，同时保留
  PID/start ticks、监听端口、runtime/model SHA/path/id 和 `/proc/<pid>/cmdline` 校验。
- focused、model-free Python unittest、TOML/JSON/template hash 检查、`git diff --check` 与意外大文件/权重扫描通过；不得把
  fake/parser/命令生成证据表述成模型、CUDA 或 GPU 验收。
- Plan 015 的唯一 GGUF 身份与 `download_ready_blocked_on_user_approval` 状态保持不变；形成精确 CUDA build-ready 恢复入口，
  并明确整体部署仍需“唯一 GGUF + Linux CUDA runtime + model-backed 4k smoke”三项汇合。

## 2. 范围

### 允许修改

- `eval/rondo_eval/config.py`
- `eval/rondo_eval/local_approval/{client,launcher,identity}.py`
- `eval/tests/` 下与本任务直接相关的 focused unittest
- `eval/templates/` 下唯一官方模板小型资产，及 `eval/locks/` 下对应模板锁
- `rondo.local.example.toml`
- 本计划、`doc/WBS/local-approval-model.md`、必要的 `doc/WBS-COMPLETED.md` 与本批 `agent_log/`
- 如实现需要，局部新增一个仅负责模板锁/校验的轻量 Python 模块；不得形成通用模型资产框架

### 不允许修改

- Plan 015 冻结的 GGUF repo/revision/file/size/SHA 和下载审批状态
- `eval/locks/llama-cpp-b10333.json` 的 CPU runtime/capability 结论
- `mydev/`、canary/L2a/paid-eval worktree、campaign、结果、调度或共享 eval 环境
- 真实 `rondo.local.toml`、`.env.local`、模型权重、CUDA runtime、系统/宿主配置或远端资源

### 不允许读取/查看

- `.env.local` 内容及任何 token/API key 明文、长度、前后缀或哈希
- canary/paid-eval 私有结果内容和与本任务无关的个人文件

## 3. 硬约束

以下约束具有强制性。不得为了简化实现、通过测试或提前推进而违反。

1. 只获取官方 repo `mistralai/Ministral-3-8B-Instruct-2512` revision
   `5b26027e7b19eeb4b7352e1fed3926375dd2cb4d` 的 `chat_template.jinja`；预期 SHA-256 为
   `74eeb55fd3341286ec3fd44e902b7120721acc81cd394e96b431f85e93a1ea56`，本任务新增外部文件合计不超过 5 MiB。
2. llama.cpp 参数必须以 `b10333`/commit `08659901c43b51de735740f1cf61bb82fbe0c4e4` 的 `common.h`、`arg.cpp`
   与 server 文档逐项复核；不接受档案参数列表本身作为唯一证据。
3. 不提供任意 CLI 参数透传，不为多模型/多 GPU 泛化。RTX 4060 单卡固定 `--split-mode none --main-gpu 0`，除非源码复核
   证明固定参数不忠实；配置只暴露本轮两阶段真正变化的最小字段。
4. 不下载 GGUF/safetensors/bin/adapter/mmproj/tokenizer 等模型资产；不安装依赖/CUDA/Ninja，不构建或启动 llama.cpp，
   不运行模型/GPU/Docker/Cargo/Bazel/just/CMake/Make/nvcc/Rust 编译。
5. 模板路径必须 fail-closed：限制在受跟踪工作区的专用模板目录，拒绝缺失、符号链接、目录逃逸、非普通文件、大小或哈希不符；
   正式命令始终显式传模板和 Jinja，不允许静默使用 GGUF 内嵌模板。
6. identity 不得包含密钥；命令也不得包含 API key。配置变化后旧 launcher identity 必须机械拒绝，不能只依赖“当前进程命令未变”。
7. 只运行授权的 focused/model-free Python 与轻量一致性检查；现有 `.venv` 不可用时不安装依赖，记录阻塞。
8. 保留 offline、禁止远端模型自动加载、禁止 Web UI、loopback-only、tools disabled、non-streaming、zero-retry、watchdog 与
   既有 service/model/process identity 边界。
9. CUDA 交接只形成待执行合同；构建完成但无 exact-model 证据时 capability 仍不得进入
   `gpu_model_serving_validated`。

## 4. 软性建议

- 用冻结模板 JSON lock 作为 repo/revision/file/size/SHA 的单一机器可读事实源，配置仍显式写 path/SHA，避免 launcher
  隐式选择资产。
- identity 采用由同一命令参数生成器导出的规范化服务配置指纹，并额外绑定配置中的 binary 与模板内容摘要；实际完整命令仍由
  `command_sha256` 和 `/proc/<pid>/cmdline` 复核，避免并行维护第二套大配置 schema。
- 在现有 `test_local_approval.py` 内扩展集中测试，只有模板锁的独立校验确有复用价值时才新增 focused test 文件。
- CUDA 交接只冻结 exact source commit 和已由官方证实的 build option；工具链版本、CUDA Toolkit 版本与宿主闭包仍标为
  下一阶段开始时待冻结，不从当前缺失环境猜测。

## 5. 当前状态

> 本节允许在执行过程中持续更新。只记录恢复任务所必需的信息，不记录普通工具调用流水账。

### 已完成

- 2026-08-12：完整读取根规则、README、当前/方向 2 WBS、Plan 015、模型审计快照、开发环境、配置示例、相关源码与测试。
- 2026-08-12：确认主工作区 `main...origin/main` 干净且均为 `fea01f86905459edb4e697f7ba2702802a5c1a5d`；识别并保护
  全部既有 worktree，其中 `0811-plan014-post-audit` 有并行未提交修改，本任务不进入或触碰。
- 2026-08-12：创建独立 worktree `.claude/worktrees/0812-plan016-local-launcher` 与分支
  `0812-plan016-local-launcher`。
- 2026-08-12：以 b10333/`08659901…` 的 `common.h`、`arg.cpp`、server README 逐项确认参数：原生
  `--gpu-layers auto|all|N`、fit、batch/ubatch、F16 K/V、no-mmproj、Jinja/template、flash、parallel；单卡必须显式
  `--split-mode none --main-gpu 0`，server parallel 默认不是 1。
- 2026-08-12：通过 HF CLI 1.27.0 只获取官方 revision `5b26027…` 的唯一 `chat_template.jinja`；受跟踪文件精确
  11,912 bytes、SHA-256 `74eeb55f…`，新增外部文件连同临时 HF metadata 共 12,204 bytes，未获取其他模型资产。
- 2026-08-12：现有 CPU runtime 的 `llama-template-analysis --template-file` model-free parser 检查成功；命令没有模型参数，
  未启动 server/GPU，只证明 b10333 Jinja parser 能分析该模板。
- 2026-08-12：配置/launcher/receipt v2 与 focused 回归已实现；4k/8k 完整命令、模板 fail-closed、旧 identity 拒绝、
  CPU-only/model-missing/watchdog/loopback/密钥边界均由 fake/model-free 测试覆盖。
- 2026-08-12：focused unittest 首轮通过：`test_local_approval.py` 45 项、`test_config_hardening.py` 8 项、
  `test_config_and_artifacts.py` 27 项；均从本 worktree 复用主仓现有绝对解释器
  `/home/sjc/desktop/RONDO/eval/.venv/bin/python`，`git diff --check` 通过。
- 2026-08-12：独立终审复核最新 diff 并独立复跑同一组 80 项 focused 测试；binary 配置绑定、RPATH 转义和测试命令证据
  已收口，无剩余阻塞 finding。
- 2026-08-12：实现提交 `c4a7fc1af55f97d67a4b59e80e718291211cdcad`，以 `53abd670c361dd67fd85984a2ebb50a4d7f815d2`
  合并并推送 `origin/main`；远端 exact SHA 已复核。完成分支在交付收口后保留为 `zz-done/0812-plan016-local-launcher`。

### 当前工作

- 本轮实现与 Git 交付已完成；不进入 CUDA、权重或 GPU 执行。

### 交接边界（后由 Plan 018 完成）

- 本计划终止于 model-free launcher、模板、参数和 receipt v2 合同。其 Linux CUDA build-ready 交接后来由
  Plan 018 完成；model-backed 验收不属于本计划，当前路线只见 `doc/WBS/local-approval-model.md`。

#### Linux CUDA b10333 build-ready 历史交接（本轮未执行，后由 Plan 018 完成）

- 源码必须是 `ggml-org/llama.cpp` tag `b10333` peeled commit
  `08659901c43b51de735740f1cf61bb82fbe0c4e4` 的 clean tree。建议 ignored 路径：
  `eval-data/sources/llama.cpp-b10333-08659901/`、`eval-data/build/llama.cpp-b10333-cuda-linux-x64/`、
  `eval-data/tools/llama-b10333-cuda-linux-x64/`；新增独立受跟踪 lock
  `eval/locks/llama-cpp-b10333-cuda-linux-x64.json`，不得覆盖当前 CPU lock/runtime。
- 已知当前宿主有 CMake 3.28.3、GCC/G++ 13.3、GNU Make 4.3；`nvcc`/CUDA Toolkit 缺失，Ninja 缺失但不是必需。
  下一阶段必须重新核对并冻结 CUDA Toolkit exact major/minor/patch、toolkit-only 安装来源/包 SHA、Windows driver 与 Toolkit
  兼容、WSL `libcuda.so`、nvcc/CMake/GCC/G++/Make/glibc 的 canonical path/version/SHA；禁止在 WSL 安装 Linux display driver。
- 官方必要入口是 `-DGGML_CUDA=ON`，CMake 最低 3.18；RTX 4060/Ada 使用 CUDA architecture 89（CUDA 至少 11.8）。
  RONDO 建议配置骨架如下，版本占位必须先冻结后才能执行：

  ```bash
  cmake -S <EXACT_SOURCE> -B <PROJECT_LOCAL_BUILD> -G "Unix Makefiles" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER=/usr/bin/gcc \
    -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
    -DCMAKE_CUDA_COMPILER=<FROZEN_CUDA_ROOT>/bin/nvcc \
    -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++ \
    -DCMAKE_CUDA_ARCHITECTURES=89-real \
    -DCMAKE_INSTALL_RPATH="<FROZEN_CUDA_ROOT>/lib64;\$ORIGIN" \
    -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
    -DBUILD_SHARED_LIBS=ON \
    -DGGML_BACKEND_DL=OFF -DGGML_NATIVE=OFF -DGGML_CPU=ON -DGGML_OPENMP=ON \
    -DGGML_CUDA=ON -DGGML_CUDA_FA=ON -DGGML_CUDA_FA_ALL_QUANTS=OFF \
    -DGGML_CUDA_GRAPHS=ON -DGGML_CUDA_NCCL=OFF \
    -DGGML_CUDA_FORCE_MMQ=OFF -DGGML_CUDA_FORCE_CUBLAS=OFF \
    -DGGML_CUDA_COMPRESSION_MODE=size \
    -DGGML_RPC=OFF -DGGML_CCACHE=OFF \
    -DLLAMA_BUILD_COMMON=ON -DLLAMA_BUILD_APP=OFF \
    -DLLAMA_BUILD_TOOLS=ON -DLLAMA_BUILD_SERVER=ON -DLLAMA_OPENSSL=OFF \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
    -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF
  cmake --build <PROJECT_LOCAL_BUILD> --config Release --target llama-server --parallel 6
  ```

- CUDA lock 至少冻结 source tag/commit/tree/clean、完整 configure/build argv、有效 CMake cache 摘要、toolchain；runtime bundle
  每个普通文件的 size/mode/SHA、每个 symlink target、`llama-server --version`；再用冻结的 `/usr/bin/ldd` 对 server 与项目库
  递归记录所有非 bundle host dependency canonical path/SHA（以真实 DT_NEEDED 为准，包含实际出现的 CUDA/WSL/系统库）。
- 构建后无模型的中间 capability 只能是 `linux_cuda_built_model_unvalidated`，structured output 仍是 `not_run`；下一阶段获 GPU
  授权后即使 model-free `--list-devices` 成功，也只能记录 device probe，production launcher 继续拒绝。
- 晋级 `gpu_model_serving_validated` 的最低门是 exact GGUF + 本轮模板/identity + 完整 4k 合同的 model-backed smoke：证明 CUDA
  backend 和正数 offload、记录 fit 后参数/峰值显存、完成真实 loopback Responses 结构化审批、无 OOM/下载/残留。8k 全层
  offload/fit off 仍是后一项独立 baseline 验收，不随 4k 自动通过。
- CUDA 安装、构建、GGUF 下载和 GPU smoke 分别按其授权门执行；每次都须由 canary 调度者保证全窗口互斥，不能凭瞬时 Docker
  为空继续。构建走项目资源看门狗/互斥锁，并重验 Windows `C:` 实际余量、项目占用、无 Docker/Cargo/模型并发。

### 阻塞项

- 权重下载仍由 Plan 015 阻塞于用户单独审批；不阻塞本轮 model-free 工作。
- Linux CUDA 工具链缺失且本轮禁止安装/构建；只输出 build-ready 交接。

### 当前验收状态

- `model_free_complete_git_delivered`：实现、focused/parser 门禁、独立终审和 Git 交付均已完成；
  权重、CUDA、GPU、Docker、Cargo/Bazel/just 均未运行。

## 6. 关键决策记录

> 本节允许追加或更新。只记录会影响架构、范围、实现方向或后续维护的重要决策。

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 本轮为 Plan 016，Plan 015 继续独立持有 GGUF 下载审批分支 | 下载审批状态不能因 launcher 前置工作变化 | 计划、WBS、交付措辞 | 已采纳 |
| 002 | 两阶段不用 profile 系统，示例 TOML 直接给 8k baseline，并在注释/文档给出 4k smoke 的三项切换 | 只有 context/gpu-layers/fit 在两阶段变化，profile 会增加无必要抽象 | 配置与文档 | 已采纳 |
| 003 | 单卡 `split_mode=none`、`main_gpu=0` 固定为 launcher 参数 | b10333 默认 split 是 layer；本轮硬件与验收均为单卡，不暴露未来多 GPU 配置面 | launcher 命令与 identity | 已采纳 |
| 004 | receipt 升级 v2，以同一参数构造器生成 `serve_config_sha256`，同时保留实际 `command_sha256` | 当前 command SHA 证明进程未变；配置指纹再证明客户端当前配置可重建同一服务参数，且不绑定无关 paid 配置/注释 | identity/client/tests | 已采纳 |
| 005 | 模板作为 `eval/templates/local-approval/` 小资产并由 exact JSON lock + 编译期冻结常量双重约束 | tracked asset 必须随 worktree 代码走，不能错绑 common root；配置不能自选模板或回退 GGUF metadata | template/launcher/tests | 已采纳 |
| 006 | 本阶段 K/V 只允许 F16、no-mmproj/Jinja 必须开启、parallel 必须为 1；其余整数采用 b10333 int32 边界 | 只开放两阶段当前需要的参数，不形成通用 llama.cpp passthrough | config/client/launcher | 已采纳 |
