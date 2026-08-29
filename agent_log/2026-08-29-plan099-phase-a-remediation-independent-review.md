# Plan 099 阶段 A 整改独立复验

## 结论

阶段 A **复验不通过**，阶段 B 保持 **未授权**。首轮审查提出的候选导出、无 config `NO-GO`、恢复指针、orphan checkpoint、retention 重入、Torch/CUDA 版本断言和绝对截止止费兜底主体均已按任务语义闭合；但仍有一个会让 commissioning/formal 无法启动的 High，以及两处阶段 B 运行合同 Medium。三者都能在付费前做一次窄修。

这些都是阶段 A 范围内的实现/合同闭合问题，不需要更换模型、数据、loss、scope、准入门、云资源方案或申请额外授权。本轮不批准创建 Pod、上传资产或产生费用。

## 阻断项

### bootstrap 产物会被 worker 拒绝（High）

`training/publication-critic-plan099/runpod-bootstrap.sh:38` 使用 `python3 -m venv --system-site-packages`。标准 Linux venv 默认把 `venv/bin/python` 建成指向基础解释器的符号链接，但 `training/publication-critic-plan099/runpod-worker.sh:30-31` 明确在该路径为符号链接时 `exit 2`。

本次在 `/tmp` 用 bootstrap 的同一条 venv 命令做最小复现，得到：

```text
exists=True
executable=True
is_symlink=True
worker_guard_accepts=False
```

因此 bootstrap 内的 Torch 断言可以通过，随后 commissioning/formal worker 仍会在训练 CLI 前退出。执行者可在 bootstrap 生成符合 worker 门的复制式解释器，或在保持 task-root 边界与实际解释器身份检查的前提下接受标准 venv 链接；具体实现路线由执行者自主选择。回归应实际创建 venv 并证明 bootstrap 所产出的解释器满足 worker 的同一检查，避免仅检查脚本文字。

### absolute deadline 的审批例外与 10,800 秒口径不一致（Medium）

`training/publication-critic-plan099/runbook.md:59-63` 正确允许绝对 trigger 先到时无需 queue receipt 自动释放 exact Pod；但同文件 `:106-109` 与 ExecPlan 的硬约束/执行提示又绝对要求收到审查批准前不得 stop/delete，执行者无法同时遵守。

另外，resource contract 把累计墙钟硬上限写成 10,800 秒，而 lifecycle authorization 到 `pod_started_at + maximum_lifecycle_seconds` 才触发 stop/delete，之后另有最多 360 秒终态确认，预算计算还另列 60 秒 worker kill grace。当前实现允许实际 0 Pod 确认晚于 10,800 秒，和冻结申请不一致。

本审查代用户统一口径：10,800 秒是所有任务 Pod 的**累计计费墙钟硬上限**，包含 worker kill grace 与 stop/delete 终态确认预留；正常提前释放仍须审查批准，只有不可移动 absolute deadline 是无需 queue receipt 的精确止费例外。实现可自行安排 worker deadline、trigger 和确认窗口，但必须证明 prior Pod wall 与本 Pod 最坏收口合计不超过 10,800 秒，并把该例外同步到所有释放文字。

### 必需的运行时授权没有合法 host→Pod 传输边界（Medium）

`runbook.md:38-44` 要求在宿主生成 live resource/lifecycle/segment 等小型授权或回执，并把 immutable lifecycle authorization 复制进云端 task root 供 worker 哈希绑定；但 `asset-contract-v1.json` 和机械校验把全部上传严格限定为四个 Phase A bundle/receipt。按当前冻结合同，没有合法路径传入 worker 的必需运行时控制 JSON。

整改只需把阶段 A 静态上传与 Pod 创建后产生的轻量 runtime control transfer 分责，并精确列出 worker 实际需要的 JSON 类别/落点；不得借此扩大数据、模型、密钥或任意文件上传范围，也不需要新建通用传输或审计体系。

## 已闭合的首轮 finding

- 五个 write-once evaluation artifact 与有限完整 checkpoint 保留已分责，裁剪后候选可复核和导出。
- 早期无 decision config 不阻断后续候选，五点全无 config 可终结为有效 `NO-GO`。
- fresh recovery 清除旧指针，paused 从 latest 续训；下一个合法 orphan checkpoint 可被核验采用；retention marker 可幂等重入。
- Torch `2.8.0+cu128` / CUDA `12.8` 在 pip 前后均有断言。
- Plan 099 absolute lifecycle guard 已具备 queue 等待时自动释放 exact task Pod 并核验 0 Pod、compute `$0/h` 的主体能力；剩余问题是合同文字和累计墙钟口径统一。

## 复验证据

- 受审实现提交为 `a166e117bd06b9939e2a7df510bdf3d04dd90e26`；审查写报告前 worktree 与主工作区 tracked 状态均 clean，未合并、未推送。
- Plan 099 focused 测试独立窄重跑：`13 passed in 1.47s`。现有 venv 测试没有创建真实 venv，因而没有捕获上述冲突。
- `validate-freeze` 通过，freeze SHA-256 为 `fd8726a4d207d9e8eb6509cffe48fc74d131b5278d246a0810eb504890a7b726`。
- 四个 Phase A ignored 工件的 bytes、权限 `0600` 和 SHA-256 均与执行者汇报一致。
- 未加载真实模型，未使用 GPU、RunPod、Docker 或付费 API，未上传资产，未读取 v9 test、qualification sealed 或旧 unseen 正文，未运行 Cargo 或其他重型测试。

## 再验收最小条件

1. 消除 bootstrap venv 与 worker 解释器门的冲突，不改变冻结训练路线；增加一个实际创建 venv 并复用 worker 判定的窄测试。
2. 统一 reviewer gate 的 absolute-deadline 例外，并让所有 Pod 的最坏累计计费墙钟（含 kill grace、终态确认）不超过 10,800 秒。
3. 为实际必需的小型 runtime control JSON 给出封闭且可执行的 host→Pod 传输 allowlist，继续禁止其他上传。
4. 只复跑 Plan 099 focused、freeze、shell 和 diff 门，无需扩大测试；提交 clean worktree，并重建、核对绑定新实现提交的 Phase A source/data bundle 与 receipt。
5. 通过既定 queue 再次申请阶段 A 复验；收到明确批准前不得进入阶段 B。

除上述 10,800 秒统一口径外，本轮没有需要代用户新增的路线或资源决策；沿用首轮决定：正常 Pod 提前释放须审查批准，absolute lifecycle deadline 是预算硬边界，可自动精确止费。

当前状态：`PHASE_A_REVIEW_FAILED / NARROW_REMEDIATION_ALLOWED`；`PHASE_B_NOT_AUTHORIZED`；完整 Plan 099 为 `IN_PROGRESS`。
