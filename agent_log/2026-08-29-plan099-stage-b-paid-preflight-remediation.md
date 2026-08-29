# Plan 099 阶段 B 付费前窄修

阶段 A 批准后、创建计费 Pod 前的可执行性复核确认了几个真实 seam；本轮未改变模型、v10 数据、五头 loss、scope、recipe、数值准入门或外部资源路线。

- 冻结 CLI 直接生成 budget snapshot 与 live-resource receipt，三类 runtime control 继续使用确定性 bytes、content SHA 和交叉绑定；bootstrap 也消费 fresh segment，并把 assembly、venv、pip 与 freeze 验签机械限制在该 segment timeout 和 60 秒 kill grace 内。
- execution assembly 在 Pod 内 exclusive-create source identity；新增 exact snapshot 纯文件验签入口与小型 receipt allowlist。
- L40S 仍要求 exact device name，显存门改为 44 GiB CUDA-visible 下界，避免把厂商标称 48 GB 错当成 48 GiB；environment receipt 同时锁定 Python、Torch/CUDA 及五个直接依赖版本，bootstrap 执行 `pip check`。
- 运行手册同步了 launch budget→resource→lifecycle→fresh segment 顺序、确定性 JSON 字节口径、exact 12 文件下载和 fresh-process 调用边界。

定向结果：Plan 099、Plan 094 lifecycle 与 Plan 087 terminal 组合 `24 passed`；freeze CLI、Ruff、compileall、shell syntax 和 diff-check 通过，freeze SHA-256 为 `13eb7ad169432d515fd282f98435cff0ec7884e28fabcf265f18e384209d98c0`。独立只读复核提出的 bootstrap segment timeout 已闭合；未发现其余 High/Medium finding。

本轮尚未创建 RunPod、上传资产、下载或加载真实模型，也未读取 v9 test、qualification sealed 或旧 unseen 正文。
