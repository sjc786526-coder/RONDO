# Plan 037 阶段一整改复验

复验对象：`a90f5c13b0b21527d3971e7c1c1fa6a5241850f9`（整改范围
`2a8e1c1..a90f5c1`）。本次只读复验训练脚手架、成对输出/Plan 036 导入合同、RunPod
操作手册和阶段一 ignored 实物；未创建远端资源、未上传、未训练、未产生费用，也未触碰 main 或
038 worktree。

## 结论

- **阶段一验收不通过。** 大部分前次问题已正确关闭，但正式闭环还剩两个功能阻断和一个很小的
  RunPod 恢复手册错误；它们均可在阶段一内窄修，不需要增加审计平台或改变训练路线。
- **Plan 037 任务目标未完成，但当前不是任务失败。** 真实 8B optimizer smoke、adapter reload、
  正式训练、两侧 130 条输出及 Plan 036 正式导入尚未执行；当前问题也不需要越过预算、数据或
  安全边界即可修复。
- 本复验不授予阶段二权限。在下述窄修通过前，不创建 Pod/HF repo、不上传 train bundle、不产生
  费用。

## 已确认正确的整改

1. LoRA target 已收敛为仅匹配 `model.language_model.layers.*` 的文本层 regex，并在运行时验证实际
   targeted modules 与全部 trainable parameter owner；视觉塔、projector、`lm_head` 命中会失败。
2. completed formal receipt、冻结模型/数据身份、精确 `12288 / 512 / 0 / 1 / 42` sampling 及 runtime、
   template、request/output 合同已由实物重验；裸 receipt mapping 不再能冒充 formal v2 evidence。
3. 唯一悬空 tail attempt 可显式收敛为 `infrastructure_failure`，不会重调该样本或伪造成 `deny`，随后
   能继续剩余样本。legacy v1 导入兼容保留。
4. 正式训练 receipt 的 orphan manifest 恢复只接受逐字一致实物。RunPod 手册主路径已覆盖 bundle
   上传/验包、冻结 revision 下载、依赖、smoke/formal、费用控制、回收验真、HF 后置私有镜像和 Pod
   删除；HF receipt 自引用歧义已消除。

## 剩余阻断与最小修复

### 1. Pair receipt 没有绑定 b10333 实际部署工件，并写死 adapter 形态

`paired_outputs.py:652-691,791-844` 强制 `local-static` 与 BF16 lineage 的
`model-contract-v1.json` 是同一路径/同一哈希，因此 receipt 中未微调侧的
`model_artifact_sha256` 实际是 tracked 合同 JSON，不是 b10333 真正加载的 base GGUF（或其
canonical deployment manifest）。微调侧又要求 manifest 的文件逐项等于训练 receipt 内原始 PEFT
adapter tree，既未绑定同一 base 部署工件，也无法表达 b10333 可能实际加载的转换后 LoRA；成对
GGUF 路线也被类型检查直接排除。实际 GGUF、转换器、量化器或转换后 adapter 可以漂移而 receipt
不变，和本任务的同源公平比较及可复核工件要求冲突。

最小修复：继续把官方 BF16 lock 当作 lineage；另让 `local-static` 与 `local-ft-static` 都绑定真实
deployment manifest。adapter on/off 路线至少绑定同一 base GGUF、训练 receipt 的 source adapter、
实际 deployed adapter 及转换身份；paired-GGUF 路线绑定两个实际 GGUF并校验共享 converter、
quantizer、quantization 合同。无需预先选择路线，也不需要签名链或数据库；各用一个 canonical JSON
manifest 和针对性回归测试即可。

### 2. 正式 `verify-import` 文件入口必然拒绝 Plan 037 v2 输出

`cross_eval.py:1159-1186` 对 v2 local 行要求 `FormalL6PairEvidence`，但
`cross_eval.py:1249-1264` 的正式文件 importer 只从 `pair_receipt_path` 读取裸 Mapping，随后把该
Mapping 传入前者。因此落盘后的正式 `verify-import` 会固定报 `l6_pair_sources_required`。现有绿色
测试只覆盖同一 Python 进程内传递 Built evidence，没有覆盖 Plan 036 实际消费的文件入口。

最小修复：让正式 importer 从落盘 receipt、source manifest 和明确实物路径重建并重验 evidence，
或提供等价的正式 file importer；补一条 v2 JSONL/receipt/source evidence 落盘后调用正式入口并
通过的回归测试。legacy v1 Mapping 路径原样保留。

### 3. 唯一恢复分支的 RunPod 命令和变量不一致

`stage2-runbook.md:383-385` 写成不存在的 `runpodctl pod ssh info`，本机 CLI 正确入口是
`runpodctl ssh info <pod-id>`；它刷新 `TASK_SSH_HOST/TASK_SSH_PORT`，但
`stage2-runbook.md:428-430` 的 SCP 仍使用旧的 `TASK_POD_IP/TASK_POD_SSH_PORT`。同一窄修中统一
实际使用的 host/port 变量即可。再补充 pending receipt 已生成、但 reload/finalize 前中断时的恢复
命令：在同一输出上直接执行 adapter reload、验真并 finalize，不重新启动一次正式训练。

## 复验门禁

- focused unittest：`68/68` 通过。
- Plan 036 no-model preflight：130 条，65/65 两批，26 source groups、26 split groups，0 model
  calls，状态 `waiting_for_l6_outputs`。
- train-only bundle：`ready`，470 records / 11 files；manifest
  `e429ca575c3f9c35f0f66a6606a26e3f7e669dad262e4837fba01dd247ec56ad`。
- bundle tar SHA-256：`45f098d64ac61aad504ab8ebab40afc029bd5ffd9c00cdae0e65a4e5b351018c`。
- token census SHA-256：`fdb96728dedb40f9fd7b650b89e5304ab0ab61ef9f3c4c16b5ec0af378e4155e`。
- `runpod-stage2-entrypoint.sh` 的 `bash -n`、整改 diff 的 `git diff --check` 通过。

这些绿色结果证明训练数据与大部分脚手架成立，但不会覆盖上述正式部署 identity 和 file importer
断路，因此不能用测试数量抵消阻断。

## 代用户作出的实施决策

1. 阶段二资源建议保留：Secure A40 48GB 主选；RTX A6000 仅在创建时价格不高于 `$0.60/h` 时作
   备选；单 Pod、40GB container + 100GB Pod volume，任务上限 `$12`，`$8` soft stop、`$10`
   recovery line。当前不需要 network volume/template/registry credential。
2. HF 只作完成工件的可选私有镜像，不作训练、转换或推理后端；canonical completed receipt 先由
   Pod 输出和本地逐文件验真形成。只有确认 Free private quota 足够、增量费用为 `$0`，并在阶段二
   明确授权 named repo 后才创建/上传；否则跳过 HF，不影响训练闭环。
3. 不提前锁死 adapter on/off 或 paired-GGUF。stage-2 smoke 后按 b10333 实际兼容性选择最简单可靠
   的一条，但阶段一的 deployment manifest/importer 必须能诚实表达所选实物。普通依赖、OOM、传输
   或基础设施问题允许有原因地修复和重试；一个有效正式 recipe 完成后不因质量继续训练第二套。
4. 本轮不接受增加签名、远程数据库、通用 artifact registry 或其他复杂审计设施。窄修上述合同、
   正式入口和手册即可重新复验。

## 窄修交接

执行者仅处理上述三项并补相应 focused tests；重新运行四组 focused unittest、no-model preflight、
bundle verify、`bash -n` 和 `git diff --check`。若 pair/importer 改动不属于 train-only bundle，不要无因
重建训练 bundle。完成后只提交 037 worktree 并停止，继续保持无远端资源、无上传、无训练、无费用、
不合并、不推送。
