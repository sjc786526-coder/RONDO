# 本地审批模型工程冻结

- 调查 Mistral 官方 FP8/BF16/GGUF 和 Bartowski、Unsloth、LM Studio、mradermacher、ggml-org 主要社区 GGUF，
  以精确 commit、文件元数据和公开转换链比较，未下载任何权重。
- 当前会话的 HF MCP 工具可见但实际请求持续返回 `-32603`/连接失败；用户级 `hf` CLI 1.27.0 的登录状态、文件清单、
  LFS 元数据与 exact-revision dry-run 正常。
- 冻结 Bartowski revision `ad82bf81321f4b22de70014ecd5135730115f6a8` 的
  `mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf`：5,198,387,456 bytes，SHA-256
  `7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a`。
- 完成 8GB/F16 KV、mmproj 纯文本边界、llama.cpp b10333 源码级兼容、未来训练前后量化可比性、下载/哈希/配置和
  canary I/O 风险档案。资源复查发现 P2 B7 canary 正在运行，未把瞬时空闲当作稳定窗口。
- 独立终审复核最终工件元数据、资源计算、现有配置合同与审批门，无阻塞 finding；提交前收紧了不完整 TOML 片段和
  `context_size = 0` 默认 fit 的表述。
- 状态为 `download_ready_blocked_on_user_approval`；未加载模型、未使用 GPU、未改变 Docker/canary，也未运行重型测试。
