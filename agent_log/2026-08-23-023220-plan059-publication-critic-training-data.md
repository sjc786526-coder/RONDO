# Plan 059 Publication Critic 训练数据实现

## 结果

- v1 固定标签文本、v2 exact-token 长度捷径、v3 独立验收 6 项 finding、v4 干净上下文预审的 continuity/scope finding 和 v5
  正式 normalized-text shortcut 均判定数据 NO-GO；这些失败冻结只留在 Plan 059 ignored namespace。最终 tracked release 升级为
  `training/publication-critic-v6/`，没有原地掩盖旧 revision。
- v6 继续直接复用 Plan 054 的 `PublicationPacket v1`、strict validation、render 和 exact tokenizer。新增的 input-identity seam 从 Plan 054
  v4 freeze 推导固定 rubric/input identity，只校验 model lock 列出的 7 个 tokenizer 文件，不读取模型权重。
- 默认 consumer 在构造时物理裁去 validation/unseen-test packet、supervision 和 pair；显式 evaluation 模式才保留三 split。模型消息只使用
  Plan 054 固定 rubric，formal finalizer 强制匹配 Plan 054 input/tokenizer identity、v6 teacher freeze、raw run/review hash 和当前合同 hash。
- continuity Q- 以各场景不同的产品状态缺口同时关闭“缺少 handoff 但正文仍可行动”的问题；scope Q- 改为六种不同的真实过程噪声，移除统一
  desktop/UI 和“记录 1/2”模板。length bucket 改为 Scenario 级 exact-token 合同，三 split 各有一个真实 long scenario，每个 long context
  使用 4 条不同且有用的 public history。数据卡明确 synthetic teacher reference 不是人类真值。

## 渐进生成与复核

- v4 干净预审报告 `2026-08-23-plan059-v4-final-preacceptance.md` 找到两个真实语义 finding；rehearsal-v15 至 v18 逐批返修并停止扩大，
  rehearsal-v19 的独立 `gpt-5.6-sol/xhigh` reviewer 最终接受 33/33 candidate 和 17/17 pair，确认 continuity 与 scope 语义收敛。
- formal-v10 的 72/72 candidate 与 36/36 pair 均有 terminal accept，但全量机械门禁发现四个 REWRITE 跨 split 共用 `没有收口` char-4
  fragment，因此 v5 仍为 NO-GO。v6 只把 `pc059-b-continuity-06-qminus` 的表面短语改为“还有空白”，不改变 label、defect、pair 方向或
  产品语义；按用户对本轮的临时豁免复用 v19 独立语义决定，并由执行者重新运行全量 shortcut、tokenizer、consumer 与 freeze 门禁。未把这次
  复用表述为一轮新的 v6 独立终审。
- generator：`gpt-5.6-sol/runtime_not_exposed`，session `01a02ec2-6085-73a1-95bf-dee63931a3c1`，v6 prompt
  `c40aac8f9aca869dfdc05d5731fa29c42a498b99829314eb3554a8a289e0d1d9`。reviewer：独立 `gpt-5.6-sol/xhigh`，session
  `/root/teacher_reviewer_v2`，prompt `38235f56bcb3a0a29ce39dd90b6ca1d32dda4e6c9866c430bf9f72db25878d2c`。

## 正式冻结证据

- `formal-v11` 冻结 36 scenario group、72 candidate：train/validation/unseen-test=`42/16/14`，PASS/REWRITE=`39/33`；30 Boundary、
  6 Within-PASS。train C1/C2/C3=`42 Binary / +18 Boundary / +3 Within-PASS`。
- 12 条 near-duplicate edge 进入 group closure；跨 split 引用/组件泄漏、Plan 054 reference match、model-visible text shortcut 与双向
  exact-token length shortcut 均为 0。source composition 为 34 synthetic / 2 bounded tracked public anchor scenario。
- 全量 exact-tokenizer census 为 49,634 tokens，单条 553–1,367，三 split 各有 2 个 long endpoint，continuity omission 为 0。默认
  consumer 物理保留 42 packet / 42 supervision / 21 pair；显式 evaluation 为 72/72/36。train-only smoke bundle 只含 train。
- tracked `training/publication-critic-v6/` 与 ignored `formal-v11-final` 的 12 个文件逐字节一致；content SHA-256 为
  `9c44fa1239e2190254ef983fb825a4bff6bbf20b8a18be7aaaf7b3fc848a6900`。

## 验证与边界

- 5 个 focused `unittest` 模块共 60 项通过；tracked consumer smoke 通过，C1/C2/C3 pair 数为 0/18/21，默认/evaluation 可达集合分别为
  42/42/21 与 72/72/36。正式全量 exact-tokenizer census、manifest/hash、coverage、group closure、dedup/shortcut 与 bundle 门禁通过。
- 当前轮按用户明确指示由执行者完成最终自检，不再启动新的独立子智能体复审；计划制定者最终验收仍独立，M3-B1b 未解锁。
- 未运行 Rust、Bazel、Cargo、Docker、完整模型/权重、model forward、训练、真实 API、CI 或 PR；项目新增付费预算为 0 USD。Plan 058、
  `.env.local` 和主工作区 tracked 内容均未触碰。
- 主根 Plan 059 ignored namespace 保留 45 个 rehearsal/formal 顶层目录、432 个文件，共 7.8 MiB；全部目录 0700、文件 0600、无 symlink。
  当前证据为 `rehearsal-v20{,-final}` 与 `formal-v11{,-final}`，至少保留到计划制定者验收；其他旧批次是失败/返修历史，验收后可安全清理。
  临时 tokenizer-only venv（约 866 MiB）已在完成 census 后删除。
