# Plan 015 独立审查完善

- 保持 Bartowski `Q4_K_M` 的 repo、revision、文件、5,198,387,456-byte 大小和 SHA-256 不变，将其明确定位为首个
  部署/未微调 smoke baseline，不作为质量优于官方的证明或未来训练源。
- GPU 验收改为两阶段：4k、F16 KV、上游 auto offload/fit 的稳定加载/单请求 smoke，取得显存峰值后再进入 8k、全层
  offload、fit off 的固定基线；8k 是包含模板/特殊 token 和最多 512 输出 token 的总窗口。
- 补记项目当前仅有 CPU `b10333` runtime，正式 launcher 的 GPU capability 拒绝门，以及 Linux CUDA 构建/依赖闭包、
  launcher 最小参数合同和唯一 chat-template 口径的后续前置。
- 补充官方/Bartowski 内嵌模板同源旧版本、渲染验收和规范化 messages/schema 数据边界，以及未来 BF16 训练资产和成对
  重新量化合同。本轮只改文档，未下载权重、未运行模型/GPU/Docker、未修改运行时代码。
- 提交前独立复核：Hub 提取的两份内嵌模板哈希同为 `749c9389…`，当前官方模板为不同的 `74eeb55f…`；官方 commit 时间与
  b10333 release 资产表吻合审查结论。b10333 源码确认原生 GPU auto/fit、2048/512 默认 batch/ubatch 及六个建议参数，
  本地 lock/launcher 确认 CPU capability 拒绝门和参数缺口。基于复核，保留 8k 为目标 TOML，4k 只作第一阶段策略。
- 状态保持 `download_ready_blocked_on_user_approval`。
