# Plan 023 Turn A：Local 4k model-backed qualification（未晋级收口）

日期：2026-08-14 ｜ 分支：`023-local-4k-qualification` ｜ 未合并、未推送

## 结论

真实模型首次成功加载并通过身份核验，但**所选真实 `E_final` 在 4k 上下文下不可服务**，
结构化判定未产生，按合同不晋级。能力保持 `linux_cuda_built_model_unvalidated`，
`model_backed_structured_output` 保持 `not_run`，未写入任何 model-backed 证据。

决定性数字来自服务端自身的 token 计数：所选真实 `E_final` 的 static payload = **5,313 input tokens**，
上下文 = 4096，llama.cpp 返回 exceed-context 错误。

**范围限定**：这一条只证明该样本不可服务。47 条真实归档整体是否都超出 4k **未做 exact-token 验证**，
字符长度与该 tokenizer 的 token 数不严格单调，不能据此推断；普查需单独授权。

## 实质性改动

- **主仓 ignored `rondo.local.toml`**（唯一允许直接改主工作区的文件）：只按字段迁移
  `[local_model]`、`[local_model.server]`、`[local_model.request]` 到 exact GGUF 与
  4k `auto`/`fit=on` 合同。`providers`、`paid_eval`、模型与价格配置的规范化 digest 迁移前后相同，
  文件仍为普通非 symlink、mode 0600。doctor 由 `configuration_error` 变为 `configuration: valid`。
- **新增 `eval/rondo_eval/local_approval/model_backed.py`**：exact runtime/GGUF/4k 合同常量的唯一来源、
  版本化 model-backed evidence 的严格 schema 与原子 no-clobber 写入、单向 capability 投影
  （缺失 / malformed / 身份不匹配一律保持未晋级），以及只覆盖采样与静态决策 schema 的 request-contract digest。
- **新增 `eval/rondo_eval/local_approval/qualification.py`**：受限首跑入口。串行完成合同校验、
  watchdog lease、现场前置（GPU 独占、端口空闲）、真实 `E_final` 选取（路径 + SHA + 生产 meta 校验）、
  启动、readiness、身份核验、显存峰值采样、`/slots` 首 token 观测、单条真实判定、关停清理，
  **最后**才原子生成证据。正式 launcher 不新增任何 bypass。
- **服务身份修正**：`/props.build_info` 改为按后端精确比较——CUDA source build `b1-0865990`、
  CPU release bundle `b10333-08659901c`。原先统一硬编码 `10333` 会误拒真实 CUDA 服务；
  router probe 的同一处口径也一并修正（否则晋级后会误判）。
- **测试**：`eval/tests/test_local_approval.py` 新增 10 项按失败类别组织的用例（晋级顺序、合同身份、
  现场前置、服务/GPU/结构化响应失败、证据缺失/无效/不匹配、清理 fail-closed、CPU 与 CUDA 身份分支、
  非敏感 blocker facts）。focused 门禁 112 项全绿。

## 疑难问题（均已修复并重跑 focused tests）

1. `scripts/with-build-lock.sh` 必须以**绝对路径**调用：runtime bridge 用 watcher 进程的 exact cmdline
   校验看门狗身份，`./scripts/...` 的相对写法拿不到 lease。此前的 launcher 拒绝证明也因此无效，已用真实
   lease 重做——确认拒绝发生在 `Popen` 之前。
2. b10333 的 INFO 日志走**全缓冲 stdout**，运行中读私有日志只能拿到 15 行未缓冲的 stderr，
   拿不到 `offloaded N/M layers to GPU`。改为服务退出后再读，缓冲落盘后事实完整。
3. WSL 的 `nvidia-smi --query-compute-apps` 在模型加载后会列出**本任务自己**的 llama-server，
   原独占判据把自己当外来占用。改为按进程树排除自身后再判定。

上述三项都消耗了模型生命周期，但都是先定位、先修复、再重跑，不是靠重试掩盖。
生命周期合计 4 次，等于授权上限。

## 验收结果

- focused tests：`test_local_approval` + `test_config_hardening` + `test_config_and_artifacts` 共 112 项通过。
  未跑 Rust、Docker、全 workspace、全量 eval；lock schema 未变，未跑 `just eval-lock`。
- 真实运行：模型加载成功、CUDA 启用、服务身份与 4096 上下文核验通过；结构化判定失败于上下文上限。
  显存峰值、首 token、总耗时随该失败作废，未记录为有效指标。
- 本轮结论与设施随后经独立审查判定不通过（F1—F3），修复见
  `2026-08-14-062500-plan023-review-remediation.md`。
- 现场清理：进程、端口、launcher receipt、私有临时对象四项全部成功；证据文件未生成；
  主工作区除 ignored 配置外无改动。
- 未做：Turn B、L7、Local M3、8k、Rust、Docker、云 API、训练。
