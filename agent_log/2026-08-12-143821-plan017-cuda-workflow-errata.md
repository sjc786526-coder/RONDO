# Plan 017 b10333 Ubuntu CUDA workflow 勘误

- 只读复核 `b10333` tag 直接指向 commit `08659901c43b51de735740f1cf61bb82fbe0c4e4`；官方 workflow blob 为
  `2528b18573a78a9a8e99783acc7b9f0b81688ec7`，CUDA CMake blob 为 `d3953eee962e7cdc8cd39e6e8c062bced167e200`。
- CUDA job 在准备后只执行 CMake configure/build，没有 `ctest` 或其他测试命令。除 CUDA 12.6.2、`89-real`、
  `GGML_NATIVE=OFF`、`GGML_CUDA=ON` 外，还使用 `--allow-shlib-undefined` 与 `GGML_CUDA_CUB_3DOT2=ON`。
- exact CMake 证明 CUB 开关通过 FetchContent 浅克隆 NVIDIA CCCL `v3.2.0` 并链接 `CCCL::CCCL`；这是 Plan 016 构建骨架
  没有覆盖的构建期网络/源码依赖。
- Plan 018 必须在真实 configure 前选择：采用 CUB 时冻结 CCCL exact commit/source 并消除未冻结临时抓取；省略时保留成功
  构建及官方 CI 差异证据。permissive linker flag 默认不采用，只能在严格链接失败且根因明确时加入。
- 本批只修改 Plan 017、运行路线审计档案和本日志；不改最终路线、Plan 015/016、生产代码、launcher、模板或 runtime lock。
  未安装依赖/CUDA，未构建，未运行 GPU、Docker、模型、Cargo/Bazel/just，也未下载权重。
