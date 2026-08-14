# Plan 023 review remediation：F1—F3 修复与 4k blocker 事实校正

日期：2026-08-14 ｜ 分支：`023-local-4k-qualification` ｜ 未合并、未推送
输入：`agent_log/2026-08-14-061059-plan023-independent-review.md`

本轮不启动模型（前一轮 4 次授权已用满），不选择 8k/压缩/synthetic 路线，只修复审查阻断项并把权威文档
收敛到已经真实证明的事实。三项 finding 复核后**全部成立**。

## F1：真实 `E_final` source gate 可绕过 —— 已修复

复核确认：原实现只按路径前缀取文件、由待验文件自身算 SHA、只对 meta 做少量字段检查，
且 `_select_evidence_source()` 与 `_static_payload()` 各读一次文件，存在 TOCTOU。

先尝试直接复用生产 `load_guardian_evidence_bundle()`，**实测被拒**：它要求证据目录名等于 `review_id`，
而 `eval-data/runs/` 的归档用序号目录（`0003`），meta 里的 review_id 是 UUID，因此该 loader 会拒绝全部真实归档。
其余生产校验（meta 字段全集、baseline/commit、decision/terminal 组合、token usage）对真实归档**完全通过**。

因此按审查允许的第二方案改成窄的受跟踪 selector：

- 新增 `eval/locks/local-approval-qualification-evidence-v1.json`，预绑定唯一 relative path、
  `E_final` SHA + 大小、meta SHA + 大小、review id、run id 与期望 Guardian 模型/effort。
- 复用生产 `_read_safe_evidence_file()`（拒绝 symlink 祖先、非普通文件、读中大小变化）与
  `_validate_guardian_meta()`（review id 由受跟踪 selector 提供，不由被验文件自证）。
- 与受跟踪 `eval/results/runs.jsonl` 的该 run 记录交叉核对 artifacts、outcome、
  `effective_guardian_model`、`guardian_effort`，得到独立于被验文件的第二来源。
- `E_final`/meta 各安全读取一次，读取前后比对 `(dev, ino, size, mtime_ns)`，
  payload 直接由冻结 bytes 构造，不再二次打开路径。

结果：伪造 `E_final` 即使配一份形式完全正确的 meta 也会因 digest 不符被拒；要绕过必须同时改动两个受 Git 跟踪的文件。
`evidence_source` 证据字段同步增加 `meta_sha256` 与 `review_id`。

## F2：4k 结论超出证据 —— 已收敛

复核确认：真实证明的只有“该条被选样本 5,313 input tokens > 4096，服务按合同拒绝”。
原先在 WBS、方向 WBS、Plan 与执行日志中写成“现存最小”“47 条全部装不下”“4k 整体证伪”“唯一 blocker”，
依据只是各归档 static payload 的**字符长度**，而字符数与该 GGUF tokenizer 的 token 数不严格单调，推不出结论。

四处权威文档与原执行日志已改为：“一条冻结的真实 `E_final` 实测 5,313 input tokens，不能在 4096 合同下服务；
全体 47 条的可行性尚未做 exact-token 验证”，并写明普查需单独授权、只做 tokenizer-only 计数、
只持久化 path digest 与计数。Plan 决策 009 由“待用户确认”同步为“已确认，4 次已用满”。

说明：上一轮探索阶段确实对 47 条算过 canonical static payload 的字符长度（未打印、未持久化任何内容），
但该口径不足以支撑上述结论，因此不再作为事实依据保留。本轮未再读取其余 46 条。

## F3：VRAM sampler 未 fail-closed —— 已修复

复核确认：`observe()` 吞掉全部采样异常；`stop()` 只 join 5 秒便丢弃线程句柄，不确认退出、不传播错误；
独占性只在启动前与 ready 后各查一次，请求窗口内出现 foreign compute process 不会被发现。

改为整窗口 fail-closed：

- 采样线程每 200ms 同时取 `memory.used` 与 compute process 列表；首个采样异常记 `gpu_sampling_failed`，
  首个非自身进程树的 compute process 记 `gpu_not_exclusive`，并立即停止采样。
- `stop()` 确认线程真正退出，超时记 `gpu_sampling_thread_stuck`。
- 新增 `finalize()`：在读取 peak 前重放上述错误，且样本数为 0 也失败；请求返回后再采一次，
  把独占窗口闭合到真实请求的另一侧。已经采到正 delta 不再能补偿后续缺口。
- 采样线程改为在 `Popen` 之后启动并绑定服务 PID，因此服务自身不会被误判为外来占用。

## 验收结果

- focused tests：`test_local_approval` + `test_config_hardening` + `test_config_and_artifacts` 共 **115 项通过**
  （新增伪造归档、meta/source 漂移、symlink 祖先、受跟踪 selector 与 run ledger 一致性、采样中途失败、
  join 超时、动态 foreign PID）。
- `just eval-lock` 通过（只验 `eval/uv.lock`，不替代 evidence schema 测试）。
- 只读复核：受跟踪 selector 指向的真实归档通过全部新 gate；另一条真实归档被 `evidence_source_not_selected` 拒绝。
- 未启动模型，未新增模型生命周期；能力仍为 `linux_cuda_built_model_unvalidated`，无 model-backed 证据。
- 未做：Turn B、L7、Local M3、8k、Rust、Docker、云 API、训练、全量 eval、exact-token 普查。
