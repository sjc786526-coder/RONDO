# llama.cpp Linux GPU 运行路线决策（2026-08-12）

## 1. 决策

**唯一建议：保留 llama.cpp `b10333` / commit
`08659901c43b51de735740f1cf61bb82fbe0c4e4`，按 Plan 016 的交接在项目内构建并冻结 Linux CUDA runtime。**

不升级到 `b10375`，也不把 Vulkan、Windows CUDA server、CUDA Docker 或 Ollama 设为 RONDO 当前本地审批主路线。
理由不是形式上的版本公平，而是：截至冻结时点，`b10333` 之后的官方 release 仍没有 Linux x86_64 CUDA 预编译资产；
升级不能省掉 CUDA Toolkit 和源码构建，且对当前模型、API 与参数合同没有已证明的收益。RONDO 已为 `b10333` 完成
model-free launcher、模板、receipt 和两阶段参数合同，继续这条 Linux 进程路线只剩一次性工具链/构建/闭包冻结以及小范围
runtime lock/capability/doctor 接线，日常运行不再引入跨操作系统或容器控制面。

本次只做调查和决策：未下载大型运行时或权重，未安装依赖/CUDA，未构建或启动 llama.cpp，未运行模型、GPU 或 Docker。
Plan 015 的 GGUF 仍为原 repo/revision/file/size/SHA，状态仍为 `download_ready_blocked_on_user_approval`。

本文证据口径：

- **官方事实**：冻结 tag/commit 上的 llama.cpp release/source/workflow，或 NVIDIA/Microsoft/Ollama 官方文档。
- **仓库事实**：RONDO `7aee662c4218e7bc5385939e20105af2fd5ac298` 的实现和 lock。
- **工程判断**：基于上述事实的部署/维护成本选择。
- **待实测**：必须在另一任务中实际安装、构建、运行二进制、GPU 或 exact GGUF 才能得到的结论。

冻结时间：`2026-08-12T13:55:33Z`。

## 2. 是否已有官方 Linux CUDA 预编译包

没有。GitHub Releases API 显示 `b10333` 后共有 18 个 release：`b10336` 至 `b10375`。逐个筛选资产名，所有
Linux/Ubuntu CUDA x86_64 资产集合均为空；CUDA release 资产仍是 Windows x64/arm64。最新调查上限为：

| 字段 | 冻结值 |
|---|---|
| tag | `b10375` |
| commit | `ba360efe1f574ebae727aad64112d18ecedca85a`（tag 直接指向 commit） |
| published | `2026-08-12T12:18:24Z` |
| 相对 b10333 | ahead 42 / behind 0 |
| Linux CUDA release asset | **不存在** |
| Linux Vulkan 对照资产 | `llama-b10375-bin-ubuntu-vulkan-x64.tar.gz`，32,612,910 bytes，SHA-256 `cbf7354e70f9bcda5a389e1f02e2293414d47fe525b271c3a8063327754e3ef9` |
| Linux CPU 对照资产 | `llama-b10375-bin-ubuntu-x64.tar.gz`，16,601,046 bytes，SHA-256 `b6a7ed005240eccd61e1af42debd75b876c639c1416bfa90985fd02618919a88` |

官方确有 Ubuntu CUDA CI：`nvidia/cuda:12.6.2-devel-ubuntu24.04`、Ada `89-real`、`GGML_NATIVE=OFF`、
`GGML_CUDA=ON`。但该 workflow 只构建/测试，没有 pack/upload release artifact，也不在 release workflow 的依赖中。
它证明源码能走 Linux CUDA CI，不是用户可下载的 Linux CUDA runtime。

`b10375` 名称中带 CUDA 的 release asset 具体只有 Windows 组合：
`llama-b10375-bin-win-cuda-12.4-x64.zip`、`llama-b10375-bin-win-cuda-13.3-x64.zip`、
`llama-b10375-bin-win-cuda-13.4-arm64.zip`，以及对应的 `cudart-llama-bin-win-cuda-*.zip`；不存在
`linux`/`ubuntu` CUDA zip/tarball。官方 Linux x86_64 资产只有 CPU、Vulkan、ROCm、SYCL/OpenVINO 等其他后端，不能把
它们解释为 NVIDIA CUDA 包。

可复核只读查询：

```bash
gh api 'repos/ggml-org/llama.cpp/releases?per_page=100' --jq \
  '[.[] | select((.tag_name|ltrimstr("b")|tonumber) > 10333) |
    {tag_name,published_at,
     linux_cuda_assets:[.assets[].name |
       select(test("(linux|ubuntu).*cuda|cuda.*(linux|ubuntu)";"i"))]}]'
gh api repos/ggml-org/llama.cpp/releases/tags/b10375 --jq \
  '{tag_name,published_at,target_commitish,assets:[.assets[]|{name,size,digest}]}'
gh api repos/ggml-org/llama.cpp/git/ref/tags/b10375
```

因此本任务没有可冻结的新版 Linux CUDA asset name/size/CUDA runtime 要求。“升级后直接解压运行、无需 Toolkit”这条路线
当前不存在；不能把 Ubuntu CUDA CI 或 Windows CUDA zip 当作 Linux release 包。

若未来官方真正发布 Linux CUDA 包，预编译本身只意味着不需要本机 `nvcc`/编译器；还必须先查 archive 和 ELF 依赖闭包。
若包完整携带匹配的 cudart/cuBLAS 等 CUDA user-mode libraries，则 WSL 可只依赖兼容的 Windows NVIDIA driver 与映射的
`libcuda.so`，无需安装 CUDA Toolkit；若这些库未随包提供，仍要安装匹配的 runtime/toolkit-only 组件。无论哪种情况都不应在
WSL 安装 Linux display driver。该条件路线是未来判断标准，不是当前已有资产或验收结果。

## 3. 新版功能与现有 Plan 016 合同

静态源码复核表明 `b10375` 仍支持：

- `src/models/mistral3.cpp` 的 Mistral3/Ministral3 架构；该文件相对 `b10333` 未变。
- GGUF `Q4_K_M`；相应量化说明与 CUDA Q4_K 实现相对 `b10333` 未变。
- `llama-server` 的 `/v1/responses`；官方兼容测试相对 `b10333` 未变。
- 外部 Jinja template，并仍要求 `--jinja` 先于 `--chat-template-file`。
- Plan 016 的完整公共参数：`--offline`、`--no-models-autoload`、`--no-ui`、loopback host、模型/alias、
  `--no-mmproj`、`--split-mode none --main-gpu 0`、batch/ubatch、parallel、flash attention、F16 K/V、
  context、`--gpu-layers auto|all|N`、`--fit on|off`。

这说明升级不会立刻破坏 argv，但不构成二进制、GPU 或 exact GGUF 验收。并且 `b10333 -> b10375` 有一个与部署相关的
默认值漂移：`--load-mode` 从 `mmap` 变为 `auto`（设备支持时仍 mmap，否则改变策略）。RONDO 当前命令/receipt 没有显式
冻结 load mode。若未来因其他收益升级，必须决定显式固定 `--load-mode mmap` 还是接受 `auto`，并纳入 identity 与测试；不能
只替换几个 SHA。

42 个后续 commit 主要涉及其他模型、后端、UI、ROCm 和 agent tools；本轮没有找到 Mistral3、Q4_K_M、Responses 或上述
launcher 参数的目标修复。故新版既不提供 Linux CUDA 包，也没有为当前需求带来足以抵消迁移/重验成本的明确收益。

## 4. NVIDIA/WSL 依赖边界

NVIDIA 官方 CUDA on WSL 文档明确区分运行与构建：

- 支持 WSL 的 Windows NVIDIA driver 会在 WSL 映射 `libcuda.so`；**不得在 WSL 安装 Linux display driver**。
- 已在别处编译、目标 GPU 兼容的 Linux CUDA 应用可以在 WSL 直接运行；这种情况不需要 `nvcc`。
- 在 WSL 编译新的 CUDA 应用需要 Linux x86 CUDA Toolkit。应使用 WSL-Ubuntu/toolkit-only 安装路径；不要安装会尝试带入
  Linux driver 的 `cuda`、`cuda-12-x` 或 `cuda-drivers` meta-package。

当前只读宿主快照是 Ubuntu 24.04.4 / WSL2，`nvcc` 不存在，`/usr/lib/wsl/lib/libcuda.so.1` 可见。它只说明 WSL driver
stub 存在，不证明任一 CUDA runtime、GPU offload 或模型可用。

本次复核确认 `b10333` 官方 Ubuntu CUDA CI 使用 CUDA 12.6.2，因而它是下一任务的有力候选；Plan 016 只冻结了
RTX 4060/Ada `89-real` 构建骨架和“必须另选 exact Toolkit”的边界。下一任务仍须基于 Windows driver 实际版本重新冻结
exact Toolkit。NVIDIA 的一般兼容表给出 CUDA 12.x minor compatibility
最低 driver family 525；CUDA 12.6 GA 对应 Windows driver 560.76。实际选择不能只取一般下限，还要核对 b10333 构建所用
Toolkit、目标功能与当时 driver，并在 WSL 实测。

## 5. 主要路线比较

| 路线 | 一次性准备 | RONDO 适配/日常维护 | 结论 |
|---|---|---|---|
| **b10333 Linux CUDA 源码构建** | 安装一次 exact toolkit；构建、平铺封装并锁 ELF/RPATH/依赖 | 原样复用 Plan 016 Linux argv、模板、receipt v2、watchdog；以后直接启动受锁 binary | **推荐**。首次准备较重，但控制面最少、重建和回滚最直接 |
| b10375 Linux CUDA 源码构建 | 与 b10333 同样需要 Toolkit/构建 | 还要迁移 pin/lock/doctor/tests，并处理 load-mode 漂移；无当前需求的明确修复 | 不推荐；追新没有减少实际工作 |
| 官方 Linux Vulkan 包 | 免 CUDA Toolkit/源码构建；仍需可用 Vulkan loader/ICD。b10333 包为 32,521,550 bytes（SHA-256 `f14e312fbee33ce60d2eed7036de5debe31c1d7f4d8f0e37920eb0a2de0854a5`） | 进程形态接近现有 launcher，但 WSL 上可能经过 Mesa D3D12/Dozen，需先证明选中 RTX 4060 而非 iGPU/llvmpipe | 不作为主路线；可在未来低成本探索任务中单独实测 |
| Windows CUDA server + WSL | b10333 CUDA 12.4 x64 需 CPU base、CUDA backend、cudart/cuBLAS 三个包，共 660,523,082 bytes（约 630 MiB compressed）；免 WSL Toolkit | 默认 NAT 下 WSL 需访问 Windows host IP；mirrored mode 才能双向 localhost。Windows PID/path/firewall/生命周期不符合当前 `/proc` receipt | 不推荐；跨 OS 控制面和故障恢复成本高 |
| 官方 CUDA Docker | 免宿主 nvcc，但需 Docker + NVIDIA Container Toolkit、daemon 配置与镜像 digest | receipt 不能直接证明容器内 PID/cmdline；模型服务与 canary 长期争用 Docker 互斥窗口；官方称 GPU image 除构建外未由 CI 测试 | 不推荐；容器控制面和 canary 冲突大于一次源码构建 |
| Ollama Linux | 官方包可直接安装并自动使用 NVIDIA GPU；支持导入 GGUF、Responses 和 structured output | 模板使用 Go template，不是冻结 Jinja；Responses/`response_format` 和 Plan 016 的 fit/KV/batch/no-mmproj/argv/receipt 合同不等价 | 不推荐当前迁移；“安装简单”会换来更大的协议和基线合同改造 |

Vulkan 的谨慎结论不是说它必然不可用。llama.cpp 官方要求先用 `vulkaninfo` 无错误确认设备；Microsoft WSLg 文档保证的主要是
Mesa D3D12 图形加速，而不是 NVIDIA CUDA 等价的 compute Vulkan 路径。是否枚举 RTX 4060、显存统计和性能是否足够均属待实测，
因此不能用理论上的“免编译”替代当前较确定的 CUDA 主路线。

Windows 路线也不是简单让 WSL 连接 `127.0.0.1`。Microsoft 文档说明默认 NAT 下 Linux 到 Windows 要使用 host IP；只有
Windows 11 22H2+ 的 mirrored networking 才支持双向 localhost，并可能涉及 `.wslconfig` 和 Hyper-V firewall。RONDO 当前
固定 loopback、Linux process identity 和项目内路径，改造会明显超过 Linux binary 升级。

官方 CUDA Docker 目前提供 `server-cuda`/`server-cuda13` 等 tag 规则，但本轮未获得把 exact image digest 绑定到 `b10375`
commit 的证据。即使有镜像，也仍需宿主 driver/NVIDIA Container Toolkit，不能写成零依赖。

## 6. RONDO 现有工作的复用与迁移成本

保留 `b10333` 的直接价值是完整复用已验收的 Plan 016 合同：

- `rondo.local.example.toml` 的 strict 4k/8k 参数 schema 不变。
- `_serve_arguments()` 的公共命令、`--split-mode none --main-gpu 0`、Jinja 参数顺序不变。
- frozen official template 及其 lock/路径/SHA 检查不变。
- receipt schema v2、`serve_config_sha256`、PID/start ticks、实际 `/proc/<pid>/cmdline`、listener、model 和 endpoint 身份不变。
- client 的当前 llama.cpp Responses request/response 投影不需要换成另一套 API。

下一实现任务仍不是“只编译一下”。当前 CPU lock、launcher 和 doctor 把 `b10333` CPU asset/capability 写死；CUDA runtime 必须以
新 ignored 路径和独立 lock 并存，不能覆盖 CPU 回滚资产。实现至少需要：

1. 新增 `eval/locks/llama-cpp-b10333-cuda-linux-x64.json`，冻结 source、toolchain、完整 configure/build argv、runtime 文件、
   symlink、RPATH/RUNPATH、`llama-server --version` 和全部 host dependency。
2. 把 runtime capability 从硬编码 CPU 投影改为对受控 lock 字段的严格验证/投影；构建后无模型只能是
   `linux_cuda_built_model_unvalidated`，不能启动正式模型服务。
3. 扩展依赖闭包探测。现有实现只对 server 和 `libggml-cpu-*` 运行 `ldd`；CUDA 动态 backend 及其 cudart/cuBLAS、WSL
   `libcuda.so` 依赖必须被真实 DT_NEEDED/加载事实覆盖。
4. 让 doctor 的无模型状态成为 backend-neutral，避免 CUDA runtime 仍显示 `cpu_only_ready`；保留 model missing 与
   model-backed not-run 的区分。
5. 复核 `--version`、`--help`、model-free router `/health`/`/props`、官方 template parser 和环境清洗后的动态依赖；更新
   pin/closure/capability focused tests。配置 schema、template lock 和 receipt v2 预计无需重做。

runtime 选择合同也必须在 Plan 018 显式落地：launcher 只允许按 configured binary 的两个 exact project-relative path 做有限映射，
CPU 路径选择现有 `llama-cpp-b10333.json`，CUDA 路径选择新 lock，任何其他路径或 lock 身份均拒绝。CUDA runtime lock 与
model-free checks 完成前，受跟踪 example binary 继续指向 CPU 路径；完成后才在同一实现提交中切到 CUDA 路径。用户实际 ignored
`rondo.local.toml` 在后续获批的 4k acceptance 阶段才更新，不由 Plan 018 静默修改。receipt v2 无需改 schema，binary/path/lock
变化会自然使旧 receipt 失效；正式 launcher 仍拒绝未晋级的 CUDA capability。

若未来升级到仍保持 Linux ELF/同一 CLI/Responses 的版本，迁移属于小到中等：主要修改 runtime lock、launcher/client/doctor
pin/capability/闭包、example path 和 focused tests；identity schema v2 本身可复用。若换 Windows、Docker 或 Ollama，则必须
重新设计进程/容器身份、生命周期或协议/模板合同，成本显著更高。

## 7. 下一任务精确入口

下一任务建议命名：**Plan 018：b10333 Linux CUDA runtime 构建、闭包冻结与 model-free 验收**。执行边界：

1. 进入时先复核 Windows NVIDIA driver、WSL kernel、`libcuda.so`、canary 全窗口互斥、Docker/Cargo/model process 和宿主容量；
   安装/构建及 CUDA device probe/GPU 设备访问需要新的明确授权。这里的 model-free 只表示不加载 GGUF、不推理，不表示
   GPU/driver-free。
2. 冻结 exact CUDA Toolkit（优先从 b10333 官方 Ubuntu CUDA CI 的 12.6.2 候选开始核对），使用 WSL/toolkit-only 安装，
   禁止 Linux display driver。
3. 以 Plan 016 `Linux CUDA b10333 build-ready 交接` 的 exact commit、`89-real`、server-only、RPATH 和资源锁骨架构建到
   项目 ignored 路径 `eval-data/tools/llama-b10333-cuda-linux-x64/`。
4. 实现 CPU/CUDA exact binary path 到对应 lock 的有限映射、独立 CUDA lock、动态 backend/host dependency closure、
   capability/doctor 投影和 focused tests；保留旧 CPU runtime。model-free 验收完成后才切换 tracked example binary，实际
   ignored 配置留待 4k acceptance 阶段。
5. 只做 model-free `--version`、`--help`、`--list-devices`、template parser/router/closure 验收。无 exact GGUF 时停在
   `linux_cuda_built_model_unvalidated`；不得晋级 `gpu_model_serving_validated`。
6. Plan 015 另获 GGUF 下载授权且静态校验后，再在单独 GPU/model-backed 阶段运行 4k smoke；通过后才晋级 capability，
   随后单独验收 8k baseline。

回滚方式：新 runtime/lock 与 b10333 CPU asset 并存，迁移提交可整体 revert，example binary 恢复旧路径即可回到现有
model-free 状态。旧 CPU runtime 不是 GPU 服务回滚；在 CUDA 4k 验收前不得表述为已有可工作的 GPU fallback。

## 8. 仍未验收

- Windows driver exact 版本与 CUDA 12.6.2/WSL 的实际兼容。
- Toolkit 安装、b10333 构建、产物 SHA、ELF/RPATH/动态依赖闭包与 CUDA device probe。
- frozen Bartowski GGUF 的下载、真实 SHA、Mistral3/Q4_K_M load、正数/全层 offload、fit、F16 KV、flash、4k/8k 显存和性能。
- `/v1/responses`、外部官方 Jinja、结构化审批在 CUDA exact model 上的真实行为。
- Vulkan 的实际 ICD/设备选择/显存/性能；Windows NAT/mirrored/firewall 路线；Docker GPU/镜像 digest；Ollama 对该 exact
  GGUF/模板/协议的实际行为。

静态源码支持、release 资产清单、model-free 既有测试和本文工程判断都不能替代上述验收。

## 9. 权威资料

- llama.cpp b10333 release：<https://github.com/ggml-org/llama.cpp/releases/tag/b10333>
- llama.cpp b10375 release：<https://github.com/ggml-org/llama.cpp/releases/tag/b10375>
- b10333 与 b10375 compare：<https://github.com/ggml-org/llama.cpp/compare/b10333...b10375>
- b10375 release workflow：<https://github.com/ggml-org/llama.cpp/blob/ba360efe1f574ebae727aad64112d18ecedca85a/.github/workflows/release.yml>
- b10333 Ubuntu CUDA CI：<https://github.com/ggml-org/llama.cpp/blob/08659901c43b51de735740f1cf61bb82fbe0c4e4/.github/workflows/build-cuda-ubuntu.yml>
- b10375 Ubuntu CUDA CI：<https://github.com/ggml-org/llama.cpp/blob/ba360efe1f574ebae727aad64112d18ecedca85a/.github/workflows/build-cuda-ubuntu.yml>
- b10375 CUDA build docs：<https://github.com/ggml-org/llama.cpp/blob/ba360efe1f574ebae727aad64112d18ecedca85a/docs/build.md#cuda>
- b10375 Mistral3：<https://github.com/ggml-org/llama.cpp/blob/ba360efe1f574ebae727aad64112d18ecedca85a/src/models/mistral3.cpp>
- b10375 参数入口：<https://github.com/ggml-org/llama.cpp/blob/ba360efe1f574ebae727aad64112d18ecedca85a/common/arg.cpp>
- b10333 load-mode 定义：<https://github.com/ggml-org/llama.cpp/blob/08659901c43b51de735740f1cf61bb82fbe0c4e4/common/common.h>
- b10375 load-mode 定义：<https://github.com/ggml-org/llama.cpp/blob/ba360efe1f574ebae727aad64112d18ecedca85a/common/common.h>
- b10375 server/Responses：<https://github.com/ggml-org/llama.cpp/blob/ba360efe1f574ebae727aad64112d18ecedca85a/tools/server/README.md>
- b10375 Responses 测试：<https://github.com/ggml-org/llama.cpp/blob/ba360efe1f574ebae727aad64112d18ecedca85a/tools/server/tests/unit/test_compat_oai_responses.py>
- llama.cpp Docker：<https://github.com/ggml-org/llama.cpp/blob/ba360efe1f574ebae727aad64112d18ecedca85a/docs/docker.md>
- NVIDIA CUDA on WSL：<https://docs.nvidia.com/cuda/wsl-user-guide/index.html>
- NVIDIA CUDA compatibility：<https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html>
- CUDA 12.6 release notes：<https://docs.nvidia.com/cuda/archive/12.6.0/cuda-toolkit-release-notes/index.html>
- Microsoft WSL networking：<https://learn.microsoft.com/windows/wsl/networking>
- Microsoft WSLg：<https://github.com/microsoft/wslg>
- Ollama Linux：<https://docs.ollama.com/linux>
- Ollama OpenAI compatibility：<https://docs.ollama.com/api/openai-compatibility>
- Ollama structured outputs：<https://docs.ollama.com/capabilities/structured-outputs>
- Ollama Modelfile：<https://docs.ollama.com/modelfile>
