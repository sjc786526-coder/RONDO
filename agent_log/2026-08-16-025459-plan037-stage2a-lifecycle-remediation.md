# Plan 037 阶段二A：deployment fallback 生命周期窄修

时间：2026-08-16 02:54 PDT

- 审查问题属实：`61e03c9` 的 runbook 在本地 b10333 structural smoke 前删除 Pod，导致 LoRA 只在真实加载时暴露
  不兼容后无法复用同一 Pod volume 的 BF16 cache 改走 paired-GGUF。
- 生命周期现为：formal 与 deployment 本地逐文件验真 → stop 同一 Pod 保留 volume → route-specific 本地 smoke →
  smoke 通过后 delete Pod → 完整 130×2。adapter converter 或冻结 b10333 `--lora` 加载有实证不兼容时，在
  `$10/$12` 线内继续或恢复同一 Pod，以 `paired-gguf-01` 独立 remote/local/pair 目录转换和 smoke，不重训、不按
  validation 质量选路线；失败的 `adapter-on-off-01` 诊断不覆盖。
- 手册明确一次付费授权后普通依赖、OOM、SSH、下载、转换、checkpoint 与模型加载问题由执行者自主窄修；只有预算、
  远端对象/数据范围、第二个有效 recipe 或冻结 base/template/b10333/product route 越界才重新询问。
- 用户确认个人 HF included 100 GB 未使用，并常设授权任何确认零增量费用的 HF 功能作计划变化备援；本次仍未创建或
  上传 HF 对象，HF compute 仍因 RunPod-only 边界禁止。
- 回归测试机械固定 `local deployment verify < Pod stop < structural smoke < Pod delete < formal 130×2`，并覆盖
  conversion-time fallback、同 Pod start、SSH 刷新、独立 route 目录以及 fallback 不调用训练入口。
- 验证：直接相关 unittest 92/92 通过；29 个 runbook Bash fence、entrypoint `bash -n` 与 `git diff --check` 通过。
  训练/转换源码与 ignored bundle 未变化，因此既有 470 条 train bundle 和 202 项 conversion bundle 哈希保持不变。
- 未创建/启动/停止/删除任何 RunPod/HF 对象，未上传、未下载模型、未加载模型、未训练、未转换、未产生费用；仍停在
  RunPod 付费授权门前。
