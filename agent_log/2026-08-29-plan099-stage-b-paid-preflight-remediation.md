# Plan 099 阶段 B 付费前窄修

阶段 A 批准后、创建计费 Pod 前的可执行性复核确认了几个真实 seam；本轮未改变模型、v10 数据、五头 loss、scope、recipe、数值准入门或外部资源路线。

- 冻结 CLI 直接生成 budget snapshot 与 live-resource receipt，三类 runtime control 继续使用确定性 bytes、content SHA 和交叉绑定；bootstrap 也消费 fresh segment，并把 assembly、venv、pip 与 freeze 验签机械限制在该 segment timeout 和 60 秒 kill grace 内。
- execution assembly 在 Pod 内 exclusive-create source identity；新增 exact snapshot 纯文件验签入口与小型 receipt allowlist。
- L40S 仍要求 exact device name，显存门改为 44 GiB CUDA-visible 下界，避免把厂商标称 48 GB 错当成 48 GiB；environment receipt 同时锁定 Python、Torch/CUDA 及五个直接依赖版本，bootstrap 执行 `pip check`。
- 运行手册同步了 launch budget→resource→lifecycle→fresh segment 顺序、确定性 JSON 字节口径、exact 12 文件下载和 fresh-process 调用边界。

定向结果：Plan 099、Plan 094 lifecycle 与 Plan 087 terminal 组合 `24 passed`；freeze CLI、Ruff、compileall、shell syntax 和 diff-check 通过，freeze SHA-256 为 `13eb7ad169432d515fd282f98435cff0ec7884e28fabcf265f18e384209d98c0`。独立只读复核提出的 bootstrap segment timeout 已闭合；未发现其余 High/Medium finding。

本轮尚未创建 RunPod、上传资产、下载或加载真实模型，也未读取 v9 test、qualification sealed 或旧 unseen 正文。

## 当前 Pod runtime-control 窄例外

创建并独立核验 exact Pod 后，网络卷 FUSE 将 task-owned 控制 JSON 固定呈现为 `0666`，bootstrap 因而在模型下载前 fail-closed。
经审查者明确批准，仅当前 Pod 的三类控制 JSON 改用 exact `/run/rondo-plan099-z1z3m7n90nz4xr/runtime-control`：父目录、根和 role
目录均须普通非 symlink `0700`，文件须普通非 symlink `0600`、不超过 16 KiB、content-addressed 且绑定 exact Pod id/name。
validator、worker、资产合同、runbook 与拒绝路径测试已同步；易失控制面每次环境重建或新 segment 都由 host 权威文件重新复制并完整验签，
不承载任何其他任务资产，也不延伸至 replacement Pod。

定向结果：相同组合 `24 passed`；freeze CLI、Ruff、compileall、shell syntax 和 diff-check 通过，freeze SHA-256 为
`5b045e4c00a706244e097e94cf4710abc255c107b1a83f8a67c089ca9633f71d`。独立只读审查 findings 已全部闭合。

进入云端恢复前复核发现 host guard armed receipt 所记 PID 已不存活且无结果 receipt。该失败触发既有安全止费授权：首 Pod
`z1z3m7n90nz4xr` 已 exact delete，终态为 `pod_count=0`、compute `$0/h`，账户只剩既有卷费 `$0.007/h`。未下载或加载模型，未执行
commissioning/formal；replacement Pod 的新 exact `/run` 路径和可持续 guard 启动方式改由指定队列批示。

审查者批准最后一个 replacement Pod、动态 `/run/rondo-plan099-{validated_actual_pod_id}/runtime-control` 模板和前台长期 exec guard。
实现已移除首 Pod ID/name 硬编码：actual ID/name 由独立核验结果传给 CLI/worker并与三类控制链逐项绑定，首 Pod ID 显式退役；两组不同合法 ID
可独立实例化，错 ID、旧 Pod、workspace `0666` 与其他 `/run` 路径均拒绝。相同 focused 组合仍为 `24 passed`。
