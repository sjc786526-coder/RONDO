# Plan 018：GGUF 静态验收与 b10333 CUDA model-free runtime

- 串行下载唯一冻结 GGUF，并以普通文件、精确 `5,198,387,456` bytes、完整 SHA-256 完成静态校验；未加载模型。
- 从 NVIDIA 官方 archive 获取 CUDA 12.6.2 runfile，只做项目局部 toolkit-only 安装；获取 clean exact b10333 source。
- configure/build 均经过项目 build lock/watchdog，以 Ada `89-real` strict link 成功；真实证据不需要 CCCL/CUB 3DOT2
  或 permissive linker flag。
- 新增独立 CUDA lock 与 CPU/CUDA exact binary-to-lock 映射，验证 toolchain、全部 runtime bytes、DT_NEEDED、RUNPATH、
  project Toolkit/WSL/system 依赖；client receipt 使用所选 lock 身份。
- 受跟踪示例配置、空 model path 的 model-free doctor 精确投影 `linux_cuda_built_model_unvalidated`，loopback probe
  禁用 ambient proxy；正式 launcher 仍拒绝该中间能力。真实 ignored 配置尚未迁移，直接 doctor 因
  `local_model context_size is outside its allowed range` 返回 `configuration_error`。focused local-approval tests 58/58 通过。
- model-free `--list-devices` 识别 RTX 4060 Laptop；没有运行 GGUF、4k/8k、推理或 structured model-backed probe。
