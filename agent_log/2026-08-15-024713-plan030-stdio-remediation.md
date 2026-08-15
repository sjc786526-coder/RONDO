# Plan 030 正式 launcher stdio 窄修

日期：2026-08-15

依据 `agent_log/2026-08-15-024406-plan030-remediation-recheck.md` 的最后一项发现完成无模型整改。

- 正式 `run_server()` 启动冻结 b10333 时，将 stdout/stderr 均定向到 `subprocess.DEVNULL`，不再让 structured parse
  WARN/ERROR 路径的未解析模型正文进入 launcher 终端或上层普通日志。
- qualification 仍把 verbosity 4 输出写入 mode 0600 私有临时文件，并在生命周期结束后清理；其 offload 观测不变。
- 扩展既有正式 launcher/doctor 消费测试，逐项断言正式 stdout/stderr 为 `DEVNULL`，同时断言 qualification 仍使用
  私有 descriptor + `STDOUT` 合流。未新增日志扫描、过滤、轮转或审计设施。
- 该变更不影响 argv、`serve_config_sha256=7cb5a45a…`、request contract 或 tracked evidence，未重新加载模型。
- focused tests 140/140、`just eval-lock` 85 packages 通过；未运行 Cargo、Docker、云 API、全量 eval 或全量测试。
