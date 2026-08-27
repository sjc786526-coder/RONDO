# Plan 090 阶段 A 审查整改

阶段 A 首轮审查的 `1 High / 3 Medium` 已在提交 `a2f8aa1` 窄修。第二次 BF16 不再表述为跨 seed 稳定性：freeze、run spec、真实 runtime identity、run/terminal result 和 runbook 均把它绑定为不同 seed 元数据下的独立 clean repeat，明确正式路径没有 shuffle、有效 dropout 或其它已绑定的 seed-sensitive consumer，并固定 `seed_sensitive_stability_tested=false`；没有人为引入随机性改变 Route O。

base 与旧 Route O 的 no-update 诊断现在共用正式 objective diagnostic builder，train/validation 都记录 weighted 与三项 component loss，并先核对 no-gradient、training-state-unchanged 和各自数据 identity receipt。task-root 写门统一要求 resolved basename 为非空 `rondo-plan090-*`。终态允许两个正向 BF16 后因必需恢复/闭环基础设施故障诚实收口为 `INCONCLUSIVE_INFRASTRUCTURE`，也覆盖 FP32 已完成后的同类故障；任一已有负面结果仍不能被 infrastructure 覆盖。

聚焦测试为 `16 passed`，实际穿过 exact-base/legacy 两个诊断角色、legacy checkpoint identity/load、runtime 语义漂移拒绝、Plan 090/087/任意 task root 和两/三条正向结果的恢复故障终态。相邻 Plan 081/082/087 回归为 `85 passed, 34 subtests passed`；定向 Ruff、format、compile、三个 shell `bash -n`、freeze exact JSON 和 `git diff --check` 通过。独立只读整改复核为 `0 High / 0 Medium`。未运行本地 Cargo、Docker、真实模型或全 workspace 测试。

主物理根新增并保留约 `6.6 MiB` 的任务自有 ignored 资产：

- `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan090/rondo-plan090-stage-a-a2f8aa1/`：整改后正式阶段 A namespace；旧 `stage-a-final/` 保留为 `847301d` 历史输入，不再作为正式执行源。
- `source-bundle-a2f8aa1.tar`：绑定 commit `a2f8aa12f9b7bf6469289185e4489b3317f588c1`，archive SHA-256 `22bbfd7098c56bf3bfae59a66b7973b2d52883ce4b77d5ee321fdcdccce3c414`，source content SHA-256 `8d30a1c00c735512d8cd035d7729c09d545320ef6623f73ae61030d38ad87152`，125 files；提取后 exact-tree 复验通过。
- `data-bundle.tar`：archive SHA-256 `6d98c163a2b1f64cf23eec8357b3158ed56e7a2719fbfeb84eb0aa21ee888163`，content SHA-256 `2247dd09c168900a47d37a50ecd6511d66d62d3f2ec8056ea3bc829c93de8b46`；源与重新提取结果均为 train `128/58`、validation `55/26`、unseen `0`。
- 同目录保留 source/data receipt 与提取后的 exact source/data 小树，供阶段 B 上传前再次核验。

Plan 087 ignored 输入全程只读，主工作区 tracked 状态保持 clean。阶段 A 未查询 RunPod/Hugging Face live 状态，未创建或启动 Pod，未上传、下载或运行模型，未训练、未产生费用。WBS 按审查决定保持不变；付费门继续关闭，等待审查者明确批准。
