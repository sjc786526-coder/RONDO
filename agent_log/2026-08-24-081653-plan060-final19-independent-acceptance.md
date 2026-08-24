# Plan 060 final-19 独立验收与 M3-B1c 交接

## 结论

- **验收通过，`remaining correctness/functionality findings=[]`。** final-19 已完成 Plan 060 的核心训练资格目标，M3-B1b 技术结论为 `GO`。
- 用户明确要求因 H100 难抢而暂不释放当前运行 Pod/胜者卷。因此本报告不虚构 provider terminal state、settled billing 或运行费用归零；Plan 060 与
  后续 Plan 066 改为从原 Plan 060 基线连续记入同一 23 USD 总账，远端终态清理和最终结算由 Plan 066 收口。
- Plan 064 冻结 v8 的一次有界预算适配结论为 `DATA_GO`，M3-B1c 可按新 ExecPlan 和明确授权在当前热资源上开始；这不代表模型质量或产品资格 GO。

## 独立核验

- 审查对象为 clean worktree commit `c7cf3b4c7999c76dbeea2c129186c05ee4de9299`。final-19 archive 为 768,000 bytes，SHA-256
  `066a9f60eb308312bd99f25008ddb66f3fd893e2ea082e920a4e725d3df67a61`；独立 strict verifier 得到 55 files、6 Binary、2 Pair、
  C1/C2/C3 pair 数 0/1/2，manifest `735e928ce733e08742f0e03c55497ac1f94f53674ec2855df37ca843e1f43a8d`、content
  `699e355e550f17b2efe158b66d4bf50619b7fa3d55194b42c378fefe6b4cb9a1`。
- start/pending receipt 均通过当前严格合同；独立复核二者 start receipt hash、identity、coverage 和 checkpoint binding 一致。start 与 resume 的
  process instance/PID 不同，确认从 global step 3 恢复并继续到 step 4。
- 正式 identity 绑定 exact `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`、weight hash、
  H100 PCIe 80GB 和 `flashoptim.FlashAdamW`。1,720,577,024 个参数、311 tensors 均为 CUDA BF16、`requires_grad`，optimizer 311/311
  exact coverage；未见 PEFT、量化模型、offload、部分冻结或 AdamW fallback。
- C1 Binary、C2 +Boundary、C3 +Within-PASS 及恢复后的 C3 均记录有限 loss、全局/代表性 gradient、optimizer state、LR 和 effective-master/model update；
  三个正式 stage 分别到 global step 1/2/3，恢复进程到 step 4。各监督 component 都有独立非零 gradient contribution 证据，方向合同与本地回归一致。
- full checkpoint 为 10,555,051,419 bytes、12 files，manifest
  `c5cf77d60e37fbcc0aab6c0bce2aabff45d825f80de67ee2ea16718a50e5365b`；已保存、verify、load optimizer/scheduler/RNG 并继续更新。
- formal start 的 C1/C2/C3 为 11.108/1.342/1.471 秒，resume C3 为 2.381 秒；峰值 CUDA allocated/reserved 约 18.29/21.27GB。
  这些数值证明 80GB 上路线有充分显存余量。执行者冻结门禁为 focused 128 passed、1 optional Torch seam skipped、77 subtests；本次没有重跑重型环境，
  只复跑 strict bundle/receipt validator 与轻量交叉绑定检查。两路独立代码/工件复核均返回 `remaining=[]`。

## v8 有界预算适配

- Plan 064 accepted v8 为 228 candidates、104 pairs、178,646 exact tokens；train 为 128 candidates、50 Boundary、8 Within-PASS，validation/unseen-test
  为 55/45 candidates。复算 train candidate tokens 为 95,483；一次 C1、C2、C3 累计消费约为 95,483、172,921、183,339 tokens，三个阶段各一遍
  合计 451,743 tokens。
- 最新只读费用事实为：相对原基线临时累计约 8.300263 USD，当前持续费率 2.924 USD/h。23 USD 共享上限尚余约 14.699737 USD，等价约 5.03
  个当前费率 GPU 小时；即使以包含 cold/JIT 的最低 smoke 吞吐约 318 tokens/s 粗略保守外推，451,743 tokens 约 24 分钟，再计三次约 62 秒 checkpoint、
  validation、commissioning、恢复和清理，仍有数倍余量。正式 recipe 不应机械用满预算，执行者须在开始时用最新账单和实测 batch 再锁定工作/止损线。
- 因此 Plan 064 唯一未决的训练预算适配已由正式 H100 事实闭合为 `DATA_GO`。该结论只说明冻结规模适合进入有界正式训练，不重做数据、不保证质量改善。

## 代用户作出的决定

1. **接受 Plan 060 技术 GO。** 核心资格目标完成，不再追加本地重型 Torch、完整模型或泛化审计设施。
2. **遵从用户最新覆盖决定，保留热资源。** 不停止/删除当前 Pod `oe6gbptvq5yhja`、winner 卷 `hi3iaz8rsr` 或 final-19 checkpoint；它们直接交接
   Plan 066。原 Plan 060 的“先清理再最终 GO”由用户明确改为连续任务总账，终态事实延后但必须诚实标 pending。
3. **立即清理不影响热路径的残余。** Plan 066 执行者先只读确认身份，再删除 stopped legacy Pod `b0fazq4ueaii2k` 和 loser 卷 `bbfxl15nqr`；
   final-19 checkpoint 保留到 Plan 066 新恢复点验证后再删。
4. **M3-B1c 解锁并使用 Plan 066。** 允许复用当前唯一 Pod/卷和已验证模型/依赖/cache，仍不得创建第二/replacement Pod、改变模型/GPU/FlashAdamW
   路线或突破 23 USD 连续总上限。
5. **先整合最新主线。** 当前分支基于旧 main；执行者在修改正式训练代码前必须把最新本地 main 合入当前 worktree，保留 main 中 Plan 061/062/064/065
   的事实和 Plan 064 v8，并人工合并两个 WBS 文件，不得用旧分支版本覆盖主线。
6. **Git 边界不变。** 本轮只在当前 worktree 提交；不合并回 main、不推送、不归档或删除 worktree，等待用户后续批准。

## 状态

- 验收：`PASS`
- Plan 060 核心任务目标：`COMPLETE`
- M3-B1b：`TECHNICAL_GO`
- Plan 064 数据资格：`DATA_GO`
- M3-B1c：`UNLOCKED / PLAN 066 READY`
- 远端终态与最终账单：`DEFERRED TO PLAN 066 BY USER DECISION`
