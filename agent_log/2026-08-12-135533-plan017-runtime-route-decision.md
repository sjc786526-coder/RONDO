# Plan 017 llama.cpp Linux GPU 运行路线决策

- 只读核对 llama.cpp `b10333` 后 18 个 official release、最新 `b10375` source/workflow，以及 NVIDIA CUDA on WSL、
  Microsoft WSL networking/WSLg 和主要官方替代运行方式资料。
- 独立映射 RONDO `7aee662c4218e7bc5385939e20105af2fd5ac298` 的 Plan 016 config/launcher/template/receipt 合同与
  runtime lock、doctor、client、focused tests 迁移面。
- 唯一建议为保留 `b10333`/`08659901c43b51de735740f1cf61bb82fbe0c4e4`，下一任务在项目内构建并冻结
  Linux CUDA runtime。`b10375` 无 Linux CUDA 资产，升级不减少 Toolkit/构建成本，且引入 `--load-mode` 默认值漂移。
- 独立终审后复核并明确 Windows CUDA 三包成本、model-free device probe 仍使用 GPU，以及 Plan 018 的 CPU/CUDA exact path
  到 lock 有限映射与 tracked/ignored 配置切换时点；这些修正不改变唯一路线。
- 本批只新增 Plan 017、日期冻结决策档案、当前 WBS 一句事实和本日志；未修改生产代码、runtime lock、Plan 015/016 或
  frozen GGUF/template 合同。
- 未下载大型运行时/权重，未安装依赖/CUDA，未运行构建、Docker、模型、GPU 或 CI/PR；所有 binary/GPU/model-backed
  结论仍待后续授权验收。Plan 015 保持 `download_ready_blocked_on_user_approval`。
