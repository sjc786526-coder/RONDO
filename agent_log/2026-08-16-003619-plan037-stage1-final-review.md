# Plan 037 阶段一最终验收

复验对象：`6ab798ee3c90f8685d788e4f17550df55ea7ed93`，重点范围
`d5aae82..6ab798e`。本轮只读审查代码、合同、focused tests、RunPod 操作手册和阶段一 ignored
实物；未创建或修改 RunPod/HF 对象，未上传、未训练、未产生费用，也未触碰 main 或 038 worktree。

## 结论

- **阶段一验收通过。** 上次报告的实际部署工件绑定、formal v2 文件导入和 RunPod 恢复路径三个
  问题均按最小范围关闭，未发现阶段二付费动作前的剩余功能阻断。
- **Plan 037 总任务目标尚未完成，但没有失败。** 真实 8B optimizer smoke、adapter reload、正式
  训练、实际转换/b10333 加载、两侧 `130 × 2` 输出和 Plan 036 正式导入仍须在阶段二完成。
- 当前状态是“阶段一本地准备验收通过，等待用户单独授权阶段二”。本次验收本身不构成购买资源、
  上传或训练授权。

## 关键复验结果

1. `paired_outputs.py` 现在分别哈希两侧 canonical b10333 deployment manifest，不再把
   `model-contract-v1.json` 冒充 `local-static` 工件。manifest 重验实际 model GGUF、deployed
   adapter、converter、quantizer 与 quantization；微调侧的 source adapter tree 与 completed formal
   training receipt 逐文件一致。
2. adapter on/off 路线强制两侧共享同一实际 base GGUF，只有微调侧带 deployed adapter；paired-GGUF
   路线强制两个实际 GGUF 不同。两种路线均强制共享 converter、quantizer、quantization，runner
   callback 只获得重验后的 `ResolvedDeployment` 路径。路线仍可由真实 b10333 兼容性决定。
3. 0600 private pair-evidence locator 会落盘 receipt、source manifest 与七项 source 路径；重新加载时
   重建 `BuiltPairReceipt` 并重新哈希实物。正式 `verify-import` 已用落盘 v2 fixture 通过；`pack` 与
   `import-results` 将同一 `--pair-evidence` 贯穿内部重建路径，legacy v1 Mapping 语义保留。
4. RunPod 手册已改用实际存在的 `runpodctl ssh info <pod-id>`，重启后 SSH/SCP 统一使用刷新后的
   host/port。已有 pending receipt 时只执行 reload → finalize → verify → SCP，不重复正式训练；
   completed、pending 和无可恢复 receipt 三种状态分开处理。
5. WBS、子 WBS 与 plan 只声明阶段一完成并等待阶段二授权，没有提前把 L6、Plan 037 或 Local M4
   写为完成。

## 门禁证据

- focused unittest：`75/75` 通过；其中训练侧 `23/23`，pair/正式文件入口两条路线及漂移拒绝均有
  回归覆盖。
- Plan 036 no-model preflight：130 条，65/65 两批，26 source groups、26 split groups，0 model
  calls，状态 `waiting_for_l6_outputs`。
- train-only bundle：`ready`，470 records / 11 files；projection
  `0026cddd2a80771039c6644378120793d98310abdf66f01e7475416f23b2cc14`；manifest
  `e429ca575c3f9c35f0f66a6606a26e3f7e669dad262e4837fba01dd247ec56ad`。
- bundle tar SHA-256：`45f098d64ac61aad504ab8ebab40afc029bd5ffd9c00cdae0e65a4e5b351018c`；
  census SHA-256：`fdb96728dedb40f9fd7b650b89e5304ab0ab61ef9f3c4c16b5ec0af378e4155e`。
- entrypoint `bash -n`、本机 `runpodctl 2.9.0` 的 `ssh info --help`、整改 diff 的
  `git diff --check` 通过；worktree 交审时 clean。

## 阶段二实证边界

当前 deployment tests 使用小型 fixture，证明的是路径、文件身份、路线公平性和导入功能，不证明真实
8B 模型能由 b10333 加载。正式转换必须从冻结官方 BF16 revision 开始并使用 receipt 绑定的 source
adapter；转换完成后再以真实工件生成 deployment manifest 并做少量结构化 smoke。这是阶段二预期
工作，不需要在阶段一下载 8B 或增加转换证明平台。

## 代用户作出的决策

1. 接受当前阶段二资源方案作为授权候选：Secure A40 48GB 主选；RTX A6000 仅在创建时 live 价格
   不高于 `$0.60/h` 时作备选；一个 task-only Pod、40GB container + 100GB Pod volume；任务费用
   上限 `$12`，`$8` soft stop、`$10` recovery line、10 小时强制终止。
2. 默认不创建 network volume、template 或 registry credential。若创建前发现 A40/A6000 路线不可用
   且确需 network volume，应先报告其 live 容量、费率、预计保留时长和新的最坏总费用，不能静默
   改路线。
3. HF 只允许作完成工件的可选私有镜像，不作训练、转换或推理后端；仅当 Free private quota 可确认
   足够且增量费用为 `$0` 时使用 named private repo。canonical receipt 先由 Pod 工件和本地下载验真
   形成，HF commit 作为后置镜像记录，避免 receipt 自引用。无法确认免费额度时直接跳过 HF。
4. adapter on/off 与 paired-GGUF 都保留，由真实 smoke 后的 b10333 兼容性选择最简单可靠的一条；不为
   此再增加签名、数据库或通用 artifact registry。smoke 可触发一次有原因的技术收敛，普通依赖、
   OOM、传输或基础设施错误允许窄修和有原因重试；一个有效正式 recipe 完成后不因质量再训练第二套。
5. 上述是审查决策，不替代用户要求的阶段二单独授权。实际创建 Pod、上传 train-only bundle、创建
   HF repo 或产生费用前，执行者仍须用创建时 live 单价重新报告显卡、预计分段时长、最坏时长、磁盘/
   volume 费用和最坏总费用，并等待用户明确授权。
