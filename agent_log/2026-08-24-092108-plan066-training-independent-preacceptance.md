# Plan 066 正式训练独立预验收

## 结论

- **训练主体验收通过，`blocking correctness/functionality findings=[]`。** final-01 已满足 C1→C2→C3、BF16 全参数 FlashAdamW、三个阶段候选、
  validation 隔离、完整 checkpoint 和新进程恢复的功能目标。
- 当前计算 Pod 对正确性复核已无保留价值，**批准立即终止并删除 Pod `oe6gbptvq5yhja`**。保留 winner Standard 卷 `hi3iaz8rsr`、
  C1/C2/C3 候选和正式 checkpoint；不批准删除该卷或候选。
- Plan 066 尚需 compute terminal facts、settled billing 和 formal final receipt 才能写最终 `COMPLETE`。这是正常终态步骤，不是训练失败；Pod 删除后无需
  为等待账单继续付 GPU 费用。

## 独立核验

- worktree clean，HEAD `bee315c`；实现提交 `b543bbba2dacdcfeddb6540746bde13166a61618` 在执行前冻结并由 formal identity 绑定。
  final-01 archive SHA-256 为 `897dc5ad9c47018de5e190fb55668f069e8f796be022b640d9cd0cc4e71275b0`。
- 独立 bundle verifier 通过：63 files，v8 train 128 candidates/58 pairs，validation 55/26，unseen rows=0；manifest
  `2970c693fa32d1118d3b8e949a04231970bf96dfc27f7c7d14a22f98a4ed2252`。
- formal start/pending 当前严格 validator 与交叉绑定检查通过。start receipt SHA-256
  `cdb9c9a41d054077ee6ae2455eab4d3fe3902b4cb5b99940ae6d06ebae19ccdd` 正确绑定 pending；start/resume process identity 不同，
  full checkpoint 从 step 3 恢复并继续到 step 4。
- exact Skywork repo/revision/weight、H100 PCIe 80GB、CUDA BF16、1,720,577,024 trainable parameters、311/311 optimizer tensor 和
  FlashAdamW runtime 闭合。C1/C2/C3 分别消费 95,483/172,921/183,339 tokens，component 为 128 Binary、+50 Boundary、+8
  Within-PASS；loss、gradient、optimizer state、LR、model/effective-master update 均有限。
- C1/C2/C3 model-only candidates 均为 3,457,072,872 bytes，manifest SHA-256 分别为 `157d93...5a46`、`5943d3...75677`、
  `3c0ff2...f602`。远端逐文件/hash/safetensors 结构复验与 receipt/resource-hold 绑定一致；各阶段权重 hash 不同，C3 权重与正式 checkpoint
  full-model 权重一致。大文件仍安全保留在 winner 卷，本地只回收小型 manifest/receipt。
- 每阶段 validation 固定消费 55 candidates、19 Boundary、7 Within-PASS；receipt 记录 inference mode、所有 parameter grads 为 None、optimizer/scheduler
  状态不变且不反馈训练。unseen-test 未进入 bundle、未导出、未运行。
- 本次只复跑 10 项 Plan 066 focused tests，全部通过；三个 launcher `bash -n`、strict bundle/receipt validator 和 `git diff --check` 通过。第一次
  unittest 模块选择写法不适用当前路径，改用 discover 后 10/10 通过；这不是代码失败。未重跑模型、远端训练、全仓、Docker、Cargo 或本地重型 Torch。
- 两路独立只读复核均未发现训练证据 blocker。最新只读控制面确认仅此 Pod 仍为 RUNNING 且 GPU/CPU/memory utilization 为 0，唯一网络卷为
  `hi3iaz8rsr`；继续空转约 2.89 USD/h 没有验收收益。

### 非 Pod 阻断的窄后续项

- `validate_plan066_resume_receipt()` 当前接受 receipt 自报的 `new_os_process_confirmed=true`，没有在 validator 内独立校验 start/resume process 字段及差异。
  实际 final-01 的 PID、instance id 和 started_at 均不同，runner 的 `require_new_process()` 也已在生成路径执行，因此本轮恢复事实有效；但终态提交前应补一条
  负向 focused test 和窄校验，避免未来 finalizer 接受自相矛盾的 receipt。该修复完全本地，不得因此保留 GPU。
- candidate verifier 已做逐文件 SHA-256、完整 safetensors span/容器校验、阶段/identity 绑定，且 C3 权重与 checkpoint full-model 权重一致，但没有执行
  `from_pretrained` 实际加载。当前三个候选与完整 checkpoint 都保留在 winner 卷，因此不阻断释放 Pod；在删除唯一卷副本前，应由 M3-C1 或专门回收步骤对
  至少拟使用候选完成真实加载验证。

## 代用户作出的决定

1. **立即释放计算。** 执行者现在终止并删除 Pod `oe6gbptvq5yhja`，不是只停机保留本机卷；随后确认 task compute cost 为 0。
2. **暂时保留 winner 卷。** 保留 `hi3iaz8rsr`、三个候选、正式 checkpoint、exact 模型、venv 和必要 cache。网络卷费用低且候选大文件尚未回收到本地，
   现在删除会破坏 M3-C1 交接。
3. **暂不删除正式 checkpoint。** 它不改变 60GB 固定卷费率，且提供额外恢复保险；待 M3-C1 工件策略或用户后续决定再精确清理。
4. **不追加质量调参或 unseen 运行。** 当前 validation 只作记录，模型质量/候选选择属于 M3-C1；不得为让指标更好继续烧 GPU。
5. **终态流程继续。** Pod 删除后等待 provider 账单结算，生成 terminal provider facts 与 Plan 066 final receipt，更新 plan/WBS/日志并提交同一 worktree；
   同时补齐上述 resume receipt 的窄 validator 回归；不合并、不推送。最终独立验收只需核对该修复、终态、费用、receipt 与文档，不重审训练主体。

## 当前状态

- 训练主体验收：`PASS`
- 训练主体目标：`COMPLETE`
- Plan 066 整体任务：`TERMINAL CLEANUP PENDING`，非失败
- Pod 释放：`APPROVED NOW`
- winner 卷：`RETAIN`
- M3-C1：尚未因本报告自动解锁；等待 Plan 066 terminal final receipt 与最终验收
