# Plan 082 阶段 B 首轮 commissioning 接缝修复

时间：2026-08-26 ｜ 阶段：`PHASE_B_COMMISSIONING`

## 实际发现与修改

- 阶段 A source bundle 未包含训练 CLI 实际加载的 Plan 081 route 合同；将该单一受跟踪合同加入 Plan 082 source 白名单和必需成员，提取回归直接核对其正文。
- detached 训练进程若未显式携带镜像身份，会在真实 runtime identity 观察时失败；launcher 现在于 detach 前要求并继承 bootstrap 使用的 exact image identity，runbook 同步该入口。
- 第一次真实 update 已完成到 checkpoint 新鲜读回，但 `torch.load(map_location=cuda)` 把 CPU/CUDA RNG state 都变成 CUDA tensor，`torch.set_rng_state` 实际复现报 `RNG state must be a torch.ByteTensor`。训练状态改为从 CPU 反序列化，optimizer 再按参数设备恢复，直接回归固定该行为。

## 验证与边界

- 三套 Plan 082 相邻轻量测试 `28/28` 通过；两项新直接回归、launcher shell parse、Ruff 0.15.12 聚焦规则和 `git diff --check` 通过。
- 失败 commissioning 未产生合格 checkpoint，也未被用于正式证据；保留失败 status/log 和观测工件。修复提交后重建 source archive，再从新的 commissioning namespace 继续 start→fresh-process resume。
- 资源保持单张 L40S Secure 与一个 40GB Plan 082 网络卷；未访问 unseen、未换模型/seed/比较规则，未创建第二 Pod 或第二卷。
