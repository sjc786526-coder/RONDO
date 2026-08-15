# Plan 030 独立验收审查

日期：2026-08-15

审查对象：`dbe4055 feat(eval): qualify RONDO Local model-backed serving at 12k`

基线：`ffd3cc683f6297816edf98b30beb273a2ed376a5`

## 结论

- **验收：不通过。** 当前提交存在一个会让资格证据在合并到 `main` 后立即失效的交付阻断，以及两条由本任务新增日志逻辑造成的内容泄漏路径。
- **任务目标：失败（指当前提交形态）。** 真实 12K 加载、真实结构化判定、指标采集、资格晋级和 worktree 内正式 launcher + doctor 复验均有可信证据；失败不是 12K 硬件路线不可行，而是“资格可随提交进入正式生产入口”尚未实现。
- 当前不得合并或推送。只需在 Plan 030 内做窄整改和复证，不需要回到宏观路线判断，也不需要新增审计、签名、provenance 或可信发布设施。

## 阻断问题

### 1. `serve_config_sha256` 绑定了 worktree 绝对路径，合并后资格必然失配

`eval/rondo_eval/local_approval/launcher.py:1038` 返回冻结模板的 resolved 绝对路径，`:1095-1096` 把该路径写入启动 argv，`:1119` 又把完整 argv 写入 `serve_config_sha256`。因此 tracked evidence 中的启动指纹不只是绑定模板内容和服务参数，还绑定了生成证据时的 checkout 位置。

使用 `dbe4055` 的同一代码、同一 ignored 配置和同一模板字节分别重算得到：

- qualification worktree：`be95ab3e5d03a59e44bf22fd92acee6872fb75dd988fbe1e1cbcbe9497ae3f1a`
- 主工作区：`afe68046fd743d0431943ead177004a9ac5366683bd1d6411f3c8d93fb834f63`

`eval/locks/local-approval-b10333-ministral-12k-v1.json:24` 固定的是前者。合并后，主工作区会把同一合同投影为后者，strict evidence loader 因 identity mismatch 不晋级，正式 launcher 在 `Popen` 前拒绝，doctor 也不能使用该资格。这直接违反“正式 launcher 和 doctor 可使用该资格”及“为后续 L7/Local M3 提供稳定入口”。

现有测试夹具多处使用 `RepoPaths(root, root)`，没有覆盖 Git common root 与 linked-worktree root 不同的真实交付拓扑；139/139 通过不能发现此问题。

## 需要同时窄修的问题

### 2. 正式 launcher 的 trace 会输出本地 API key 后四位

`launcher.py:1080-1086` 把 `--verbosity 4` 同时用于 qualification 与正式 launcher；正式 `run_server()` 的 `Popen` 继承 stdout/stderr。冻结 b10333 源码 `tools/server/server-http.cpp:171-180` 在 trace 级对单个 API key 输出 `api_keys: ****<last4>`。当前本机和 tracked example 都正式支持 `RONDO_LOCAL_MODEL_API_KEY`，因此正式 launcher 存在把凭据片段写到终端或上层日志的确定路径。

qualification 的 0600 私有日志重定向不会保护正式 launcher。该问题不要求新增日志审计设施，只需把为 offload 观测而启用的 trace 限定在 qualification 私有采集路径，正式 launcher 保持不输出 trace 凭据片段。

### 3. “不含内容”的行形状摘要会回显任意短文本

`eval/rondo_eval/local_approval/qualification.py:751-770` 把任意符合 `_LINE_LABEL` 的行首原文作为 label 输出。独立定点复现：

```text
_log_line_shapes(["private evidence text", "user secret: hidden"])
=> ["private evidence text x1", "user secret x1"]
```

因此它不满足 docstring、Plan 和测试名称所声称的“carrying none of their content”；失败时这些 facts 会由 qualification CLI 输出到普通日志。现有测试只检查 JSON/引号形状和冒号后的 secret，恰好漏掉了无分隔符文本及冒号前敏感文本。

这里也只需删除动态原文 label，改用固定类别/固定白名单计数并补两个定点回归；不需要通用敏感信息扫描器。

## 非阻断记录问题

- 首次模型加载前实际门禁是 138/138；第 139 项是失败诊断整改后新增的回归。Plan 当前状态记录正确，但执行日志和 `doc/WBS-COMPLETED.md` 误写为首次加载前已 139/139。
- 12K 档位共 42 条适配样本，本次已验证其中 1 条，因此未逐条验证的是其余 **41** 条，不是 42 条。Plan、执行日志及两份 WBS 的相关边界措辞应统一更正。

以上仅是事实修正，不影响真实 qualification 的现场指标，也不是单独的阻断。

## 已确认正确的部分

- 正式合同固定为 context 12,288、输出 512、`gpu_layers=auto`、`fit=on`、batch 512、ubatch 256、flash on、K/V f16；当前 ignored 配置与 tracked example 一致。
- runtime/model/template、static payload v3、request contract、selector 与真实样本摘要均有严格绑定；旧 4K、字段/身份漂移、有效上下文缩小、结构化输出异常和清理不完整均 fail-closed。
- evidence 只在真实 decision、TTFT/总耗时、VRAM、正数 offload、effective context 与四项 cleanup 完成后原子写入；未发现先晋级或手工造证据路径。
- tracked evidence 记录了 `n_ctx=12288`、offload 33/35、VRAM baseline/peak/delta、TTFT、总耗时、schema compliance 与四项 cleanup；数值和执行日志一致。
- 独立复跑 focused tests：139/139 通过；独立复跑 `just eval-lock`：85 packages，通过。它们证明已有测试保持绿色，但不能抵消上述未覆盖的 checkout-path 阻断。
- 审查时主工作区仍为 `ffd3cc6` 且 clean，worktree 在写入本报告前为 `dbe4055` 且 clean；`rondo.local.toml` 为普通非 symlink、mode 0600，`eval-data/local-approval/` 无对象，进程表未见本任务 llama-server/qualification/launcher。当前审查 sandbox 无权读取 netlink/NVML，故没有冒充重新确认 8080/GPU；沿用执行者交付前的现场清理证据。

本轮没有重新加载模型，没有运行 Cargo、Docker、云 API、全量 eval 或全量测试，也没有读取 `.env.local`。

## 替用户作出的整改决策

1. **不接受旧 evidence，不合并、不推送。** 先在现有 Plan 030 worktree 内完成下述窄修；这不是 L7 或新工作包。
2. **稳定身份按内容/仓库相对资源身份绑定。** 实际启动命令仍可使用已校验的绝对路径，但 `serve_config_sha256` 不得把 checkout 绝对前缀当成服务语义；模型/模板使用已有 relative identity + digest/size 绑定，其他功能性 argv 继续严格绑定。改变指纹规范时同步提升其内部 schema，并补 `common_root != worktree_root` 的回归，证明 worktree 与 main 对同一合同算出相同 identity，真实参数漂移仍算出不同 identity。
3. **日志 verbosity 分离。** qualification 可在 0600 私有、运行后删除的日志中使用 verbosity 4 取得 b10333 offload 事实；正式 launcher 使用不打印 trace key 片段的级别。诊断 verbosity 是观测手段，不冒充模型/上下文/采样语义；如需记录可单独作为 qualification fact，不要求正式服务把 trace 暴露给终端。
4. **行形状只保留固定类别。** 不保留由任意日志正文动态生成的 label；新增纯文本行、`secret: value` 一类直接回归即可，不扩建通用日志审计或敏感扫描体系。
5. **修复会改变资格 identity，必须重新生成证据。** 旧文件不能手工改 hash 或继续沿用。无模型门禁通过后，只需再运行一次真实 qualification；成功后再用一次无资格特权的正式 launcher + doctor 复验。无需重做前四轮参数探索，也不改变 selector、12,288、512、模型、runtime、tokenizer、模板或 static payload v3。
6. **继续冻结 F16 最终参数。** 不启用低精度 KV、不追加参数探索；generic b10333 KV parser 白名单不影响本次 capability，因为 model-backed identity 仍严格要求 f16/f16，可保留。
7. **复证成功后再收敛文档。** 更正 138→139 的真实时序和“其余 41 条”，并用新的稳定 serve identity/指标更新 Plan、WBS、WBS-COMPLETED 与执行日志。无需进入 L7、跑 47 条批量、全量测试、Cargo 或 Docker。

完成这些整改、重新资格化并从正式 launcher/doctor 复验后，再提交给 Codex 复审。
