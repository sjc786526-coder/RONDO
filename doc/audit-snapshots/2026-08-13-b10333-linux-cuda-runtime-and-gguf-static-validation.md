# b10333 Linux CUDA runtime 与唯一 GGUF 静态验收快照

日期：2026-08-13（America/Los_Angeles）

执行计划：`plan/018-local-approval-b10333-cuda-runtime-and-gguf-preparation-execplan.md`

能力终态：`linux_cuda_built_model_unvalidated`

## 唯一 GGUF

- Hugging Face repo：`bartowski/mistralai_Ministral-3-8B-Instruct-2512-GGUF`
- revision：`ad82bf81321f4b22de70014ecd5135730115f6a8`
- 文件：`mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf`
- 本地路径：`/home/sjc/desktop/RONDO/eval-data/models/mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf`
- 实测：普通非 symlink 文件，`5,198,387,456` bytes，SHA-256
  `7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a`

下载前重新执行 exact revision/single-file dry-run；Windows `C:`、Docker、构建与模型进程门禁通过。实际下载使用
单 worker、单 Xet range；没有请求其他 GGUF、safetensors、adapter、tokenizer 或 mmproj。下载后只做 stat 和完整
SHA-256，未读取 GGUF 元数据、未加载模型、未推理。

## CUDA Toolkit 与宿主设备

- 官方来源：[CUDA Toolkit 12.6 Update 2 archive](https://developer.nvidia.com/cuda-12-6-2-download-archive)
- installer：`cuda_12.6.2_560.35.03_linux.run`
- URL：`https://developer.download.nvidia.com/compute/cuda/12.6.2/local_installers/cuda_12.6.2_560.35.03_linux.run`
- 实测 installer：`4,446,677,374` bytes；MD5 `dcba85e2d49d7e6d93d8626f708276a4`；SHA-256
  `3729a89cb58f7ca6a46719cff110d6292aec7577585a8d71340f0dbac54fb237`
- 安装：仅 `--toolkit --toolkitpath=/home/sjc/desktop/RONDO/eval-data/toolkits/cuda-12.6.2`；无 sudo/apt、
  Linux display driver、Windows driver 或 `/usr/local/cuda` 修改，全局 `nvcc` 仍不存在。
- Toolkit SDK：12.6.2；`version.json` SHA-256 `81d2854e…1a1b59`；nvcc 12.6.77，SHA-256
  `4101d601…bae5b`；cuBLAS 12.6.3.3，cudart 12.6.77。
- WSL2 kernel：`6.6.87.2-microsoft-standard-WSL2`；Windows NVIDIA driver `595.79`。
- GPU：`NVIDIA GeForce RTX 4060 Laptop GPU`，compute capability 8.9；WSL `libcuda.so.1` 为
  `/usr/lib/wsl/lib/libcuda.so.1`，`183,752` bytes，SHA-256 `57e0db4f…6e0b8`。

## llama.cpp source 与构建

- repo：`https://github.com/ggml-org/llama.cpp.git`
- tag/commit/tree：`b10333` / `08659901c43b51de735740f1cf61bb82fbe0c4e4` /
  `9ae780f13650ac3d45e4e345f208163ad744dd6d`
- source 状态：detached exact commit、clean、无 submodule。
- 官方 Ubuntu CUDA workflow 基线为 CUDA 12.6.2；本机 configure 使用 GNU 13.3.0、CMake 3.28.3、Make 4.3、
  glibc 2.39、`GGML_CUDA=ON`、Ada `CMAKE_CUDA_ARCHITECTURES=89-real`、shared libraries、server target。
- 两次 CMake 调用均经过 `mydev/scripts/with-build-lock.sh` 与 cgroup watchdog。configure metrics：
  `20260813-004111-1000-11588`；build metrics：`20260813-004145-1000-14013`；最终 `status=0`、
  `stop_reason=none`，峰值 sampled memory `3,293,282,304` bytes，swap 0。
- strict configure/link 在 `GGML_CUDA_CUB_3DOT2=OFF` 且不使用 `-Wl,--allow-shlib-undefined` 时成功；因此没有
  CCCL 网络依赖，也没有引入 permissive linker 例外。
- source-build 的真实 `--version` 为 `version: 1 (0865990)`；build number 1 来自 shallow tag source build，
  exact b10333 身份由完整 commit/tree、configure/cache、runtime binary SHA 与 lock 共同约束，未伪写为 release bundle 10333。

## runtime、ELF 与 model-free probe

- runtime：`/home/sjc/desktop/RONDO/eval-data/tools/llama-b10333-cuda-linux-x64/`
- manifest：9 个 regular file、14 个 symlink；`llama-server` SHA-256
  `97a6b083ea34fea7e4e4440a0ddb734e1a2f6b775f4b31ef68ba5f998a9eeabd`。
- 每个 ELF target 的 RUNPATH 均为
  `/home/sjc/desktop/RONDO/eval-data/toolkits/cuda-12.6.2/lib64:$ORIGIN`。完整 DT_NEEDED/ldd 闭包无
  `not found`：project runtime libraries 解析到 runtime，cudart/cuBLAS/cuBLASLt 解析到项目 Toolkit，
  `libcuda.so.1` 解析到 WSL driver，其他依赖解析到冻结的系统 canonical path。
- 清除调用者 `LD_LIBRARY_PATH` 后，`llama-server --version` 和 `--help` 均为退出码 0；宿主
  `--list-devices` 为退出码 0，输出 `CUDA0: NVIDIA GeForce RTX 4060 Laptop GPU (8187 MiB, 7096 MiB free)`。
- 新 lock：`eval/locks/llama-cpp-b10333-cuda-linux-x64.json`；锁身份
  `abe7f763a18e7c801ca8d024a5d4d2a9036847c80eb32e1661baab6c1e2c03da`。它与现有 CPU lock 分离，冻结
  source、Toolkit、工具链、build argv/cache、runtime、DT_NEEDED/RUNPATH、全部外部依赖和 device probe。
- 使用受跟踪示例配置并保持 model path 为空的受控 model-free 复现中，doctor/router 输出
  `status=runtime=runtime_capability=linux_cuda_built_model_unvalidated`、`model=missing`、`service=not_started`、
  `model_backed_validation=not_run`。正式 launcher 的 production gate 仍只接受 `gpu_model_serving_validated`，单测确认
  此中间能力不会调用 Popen。

当前机器的真实 ignored `rondo.local.toml` 尚未迁移到新合同；直接运行 doctor 返回 `configuration_error`（exit 64），设置
投影的具体错误为 `local_model context_size is outside its allowed range`，且在 runtime/device/model 检查前停止。因此
`linux_cuda_built_model_unvalidated` 是已经验收的 runtime capability，不表示当前机器配置或正式模型服务已经就绪。

## 边界与剩余工作

GGUF 始终未加载，未运行推理、token generation、4k smoke 或 8k baseline，也未修改真实 ignored
`rondo.local.toml`。本快照只证明唯一权重的静态完整性、Linux CUDA build/runtime/device 的 model-free 闭包；
当前配置迁移与 model-backed 验收路线见 `doc/WBS/local-approval-model.md`。
