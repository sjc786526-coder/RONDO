# Plan 030 最终独立验收

日期：2026-08-15

最终审查对象：`081b39a fix(eval): suppress formal local model logs`

前序整改：`3dcff1a fix(eval): stabilize 12k qualification delivery`

## 结论

- **验收：通过。** 前两轮审查发现的 checkout 身份、日志级别、动态日志 label 与正式 stdio 四项缺口均已窄修闭合；未发现新的功能或正确性阻断。
- **任务目标：完成。** 当前 12K model-backed qualification evidence 能在 worktree/main 两种 checkout 拓扑下稳定晋级，正式 launcher 与 doctor 已由真实模型生命周期复证；当前提交可作为后续 L7 / Local M3 的稳定入口，但不冒充 L7 或 Local M3 已完成。
- 本轮没有新增审计、签名、provenance、日志扫描或可信发布设施。

## 最后一处整改复核

- `eval/rondo_eval/local_approval/launcher.py:1227-1232` 的正式 `run_server()` 明确把 server stdout 与 stderr 都定向到 `subprocess.DEVNULL`，冻结 b10333 的 TRACE、WARN、ERROR 自由文本不再进入 launcher 终端或上层普通日志。
- qualification 路径未被改写：仍用 `os.open(..., 0o600)` 创建私有 `server.log`，stdout 写该 descriptor、stderr 合流到 `STDOUT`，生命周期结束后按既有清理合同删除；verbosity 4 的 offload 观测保持有效。
- 既有 launcher/doctor 消费测试现在同时断言正式 stdout/stderr 均为 `DEVNULL`；qualification 成功测试断言 stdout 是非 `DEVNULL` 私有 descriptor、stderr 为 `STDOUT`。没有新增重复测试套件，focused 总数保持 140。
- `3a06bd1..081b39a` 未修改启动 argv、serve fingerprint 算法、request contract 或 evidence 文件。当前 evidence SHA-256 与整改前逐字节相同，均为 `2e3a2fd0fb7b212001f5f98140db51356c0ed9ea513792042baccb0f69cb417b`。

## 身份、资格与门禁

- 使用当前代码和 ignored 配置独立重算：Plan 030 worktree 与未来 main 的 `serve_config_sha256` 均为 `7cb5a45a7d7aa1810cc14da28ea7f09d0a3356765264c7a419b4b4ca038a477d`。
- strict loader 以当前 runtime identity 投影为 `gpu_model_serving_validated / structured_output_validated`；tracked evidence 继续绑定 12,288、512 输出、static payload v3、现有 selector、exact runtime/model/template、最终服务参数、33/35 offload、完整指标与四项 cleanup。
- 独立复跑 focused tests：**140/140，通过**。
- 独立复跑 `just eval-lock`：**85 packages，通过**。
- 本轮没有重新加载模型。stdio sink 不改变模型、请求、argv、身份或 evidence；生命周期 7 的真实 qualification 与生命周期 8 的正式 launcher + doctor 复证继续有效，不需要为日志去向重复消耗模型生命周期。

## 现场与交付

- 审查时主工作区为 `main@ffd3cc6`，与 `origin/main` 一致且 clean；工作树在写本报告前为 `081b39a` 且 clean。
- `rondo.local.toml` 为普通文件、mode 0600；`eval-data/local-approval/` 无对象，进程表未见本任务 llama-server、qualification 或 launcher。
- 本轮未运行 Cargo、Docker、云 API、全量 eval 或全量测试，未读取 `.env.local`；未合并、未推送。

## 替用户作出的决策

1. 接受 `subprocess.DEVNULL` 作为正式 server 自由文本的最小 sink；运行状态继续由进程退出码、receipt、live identity 与 doctor 提供，不建设正式日志过滤/轮转设施。
2. 接受不重新加载模型、不重写 evidence；此次修复仅改变父进程 stdio 连接，不改变已资格化合同或真实复证结论。
3. Plan 030 到此冻结并通过验收；下一工作包仍按 WBS 进入 L7，不能提前宣布 Local M3 完成。
4. 按仓库约束仅提交本工作树的验收报告；合并与推送等待用户明确批准。
