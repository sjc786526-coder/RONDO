# Plan 099 阶段 A 第二轮整改独立验收

## 结论

阶段 A **验收通过**，受审实现提交为 `f7597448c74b842e68e84585edaa67ca83f90612`。此前阻断付费执行的 copied venv、10,800 秒累计计费墙钟和三类 runtime control host→Pod 边界均已闭合；未发现会阻断 commissioning 或 formal 的 High/Medium 正确性问题。

本报告与发送给执行者的指定 queue 批准共同解锁阶段 B。批准不授予第二模型路线、qualification/test 正文读取、产品启用、合并或推送。

## 核心验收

- bootstrap 使用 `venv --copies --system-site-packages`；独立真实创建的 `venv/bin/python` 为可执行普通文件而非 symlink，满足 worker 的同一门，并继续在 pip 前后核验 exact image Torch/CUDA。
- lifecycle authorization 机械满足 `prior wall + maximum lifecycle + 60 秒 kill grace + 360 秒终态确认 <= 10800`；trigger 固定在 provider start 加主体窗口与 kill grace，guard 的确认 deadline 再受 360 秒上限约束。正常提前释放仍须 reviewer receipt，absolute trigger 是唯一自动止费例外。
- 静态上传仍严格只有两份 bundle 与两份 receipt；运行时只新增 live-resource、lifecycle、paid-segment 三类不超过 16 KiB、`0600`、canonical、content-addressed JSON。worker 在 CLI 动作前验证 exact task-root 路径、schema、bytes、content SHA、Pod/价格/trigger 与跨 receipt hash 链。
- 五头模型、v10 train/validation、loss、trainable scope、正式 checkpoint/evaluation 节奏、decoder、pair-aware selector、准入门和 candidate/`NO-GO` 语义未漂移。

## 审查者决定

1. 10,800 秒继续解释为所有任务 Pod 从 provider start 到 0-Pod 确认的累计计费墙钟硬上限，包含 60 秒 kill grace 和 360 秒终态确认预留。
2. 动态预算不预填会快速过期的美元数；每次付费动作前以实时余额、已知未结/延迟费用和现有卷实时费率按冻结公式重算。结果小于等于零或不足以覆盖该段与安全收口时不得启动或继续。
3. runtime control JSON 必须只由冻结 Plan 099 CLI 从本轮 live receipt/budget 生成并逐字节复制，禁止人工编辑或重算。独立复核提出的“恶意重写字段并重算全部 SHA”属于本个人项目不建设的对抗性可信边界；在唯一受支持生成路径下不构成功能阻断。absolute guard 仍以宿主原始 lifecycle authorization 独立执行。
4. 创建后发现硬件、区域、价格、镜像、卷挂载或预算不合格，以及 guard 无法及时武装，属于已授权的安全止费场景，可立即精确释放该 task Pod，无需等待核心任务后的预释放审查；正常完成或正常提前结束仍走 reviewer gate。
5. 阶段 B 若 commissioning 或 formal 暴露真实实现正确性问题，可在不改变模型、数据正文、recipe、scope、loss、准入门或资源上限的前提下提交窄修，并从该新提交重新生成同四个逻辑 bundle/receipt、完成本地 freeze/allowlist 复验后上传替换。修复相关路径须重新 commissioning；formal 只能从修复后的干净 namespace 开始或按同一完整 checkpoint 恢复。该授权不允许借“技术修复”调质量结果。

## 阶段 B 外部授权边界

- **模型与训练**：仅 `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`，`model.safetensors` SHA-256 为 `117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9`。只训练五个 FP32 无 bias heads 共 22,528 参数；backbone 保持 BF16 frozen/eval/no-grad；recipe、数据、loss、门限和路线不得更换。
- **Provider 与资源**：RunPod Secure Cloud、`US-TX-3`、单张 NVIDIA L40S 48GB、image `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`、20GB container disk。同时最多一个计费 Pod，累计最多两个；第二个只用于首 Pod 已确认不存在后的同路线技术恢复。库存紧张只使用 `scripts/create-runpod-when-ready.py`，创建后独立核验实际硬件、区域、价格、镜像和卷挂载。
- **卷**：只复用 `mwemzrn33y`，只写 `/workspace/rondo-plan099-*`，历史 roots 只读；允许在确有必要且预算覆盖时把现有卷扩至最多 100GB，不新建或删除卷。任务结束保留该卷和 Plan 099 大型 checkpoint/cache，状态须明确。
- **时间与预算**：所有任务 Pod 累计计费墙钟硬上限 10,800 秒，逐 Pod 满足 `prior + lifecycle + 60 + 360 <= 10800`。总预算严格为 `max(实时可用余额 - 已知未结或延迟费用 - 6 × 现有网络卷实时小时费率, 0)`，不授权充值；compute、container、任务期间卷费、commissioning、formal、技术恢复、候选回传、审查等待和 stop/delete 收口都计入同一上限。
- **上传**：初始只允许四个已核验 Phase A 文件：`source-bundle.tar`、`source-bundle-receipt.json`、`data-bundle.tar`、`data-bundle-receipt.json`，以及 Pod 核验后冻结的三类 runtime control JSON。仅发生上述真实技术窄修时，允许重新提交、生成并上传同名四件套；data 正文和所有语义/路线身份必须保持不变。不得上传 `.env.local`、其他模型/数据、任意第四类控制 JSON或禁区正文。
- **公共下载**：只允许上述 exact Hugging Face repository/revision 下冻结清单中的 `.gitattributes`、`README.md`、`added_tokens.json`、`assets/skywork_logo.png`、`chat_template.jinja`、`config.json`、`merges.txt`、`model.safetensors`、`special_tokens_map.json`、`tokenizer.json`、`tokenizer_config.json`、`vocab.json`，并逐文件校验冻结身份；不得访问其他 repository/revision。
- **Commissioning**：仅在独立空 namespace 使用冻结的六个 train pairs 做一次非零 update，闭合 checkpoint-first、评价、新 OS 进程恢复与小型回传 smoke；通过后才能形成 `COMMISSIONING-PASS`，其 checkpoint 不得进入 formal 候选血统。
- **Formal 与技术整改**：从 exact base 和空 formal namespace 开始 16 次完整 v10 train cohort update，在 2/4/8/12/16 固定评价；step 8 与最终 best 必须 fresh-process 恢复。实现、环境、OOM、依赖、连接、存储、保存、恢复或传输导致的技术无效可在同一 recipe、总预算/时间和最多两 Pod 内窄修、相称恢复或 clean rerun；有效质量不足必须冻结为 `NO-GO`，不得调门、换模型或开第二路线。
- **回传**：若形成候选，Pod 预释放审查前必须把完整 `candidate/inference-ready/**` 权重、decision config、assessment、recovery/controller/manifest 和必要小型 evidence 下载到主物理根 Plan 099 ignored namespace，并本地复核 exact tree、bytes 和逐文件 SHA-256。其他完整 checkpoint、optimizer/scheduler/RNG、feature cache、venv 与 HF cache留在现有卷。`NO-GO` 只回传证明有效负向结论所需的小型证据。
- **收口**：核心任务完成并提交 clean 分支后，通过指定 queue 申请 Pod 预释放审查。正常释放只有收到“确认不再需要 Pod，批准立即释放”后执行；absolute trigger 或上述不合格/预算/guard 安全止费场景按授权立即 exact stop/delete。最终必须实时确认 task Pod 为 0、compute `$0/h`；卷保留，释放后不得为文档重建 Pod。

## 复验证据

- worktree 与主工作区在审查写报告前 tracked 状态 clean，未合并、未推送。
- Plan 099 focused 独立重跑：`14 passed in 2.48s`；两位只读复核分别覆盖 lifecycle/guard、runtime control、bundle 重组与 venv。
- `validate-freeze` 通过，freeze SHA-256 为 `8823d7d1b3b503c253f0b20c02e80a96b34ba9d7755401b47fb7950120405959`。
- 四个 Phase A ignored 工件的 bytes、权限 `0600`、SHA-256 和 commit receipt 与执行者汇报一致；data tar 只列出 v10 train/validation 允许成员，receipt 为 `test_body_files=0`、`qualification_body_files=0`。
- 未加载真实模型，未使用 GPU、RunPod、Docker 或付费 API，未上传外部资产，未读取 v9 test、qualification sealed 或旧 unseen 正文，未运行 Cargo 或其他重型测试。

当前状态：`PHASE_A_REVIEW_ACCEPTED / PHASE_B_AUTHORIZED_WITH_FROZEN_EXTERNAL_BOUNDS`；完整 Plan 099 为 `IN_PROGRESS`，尚未形成开发候选或 `NO-GO`。
