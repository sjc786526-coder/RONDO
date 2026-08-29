# Plan 099 阶段 A 第二轮整改

整改复验指出的三项问题均存在，本轮保持 frozen model、v10 数据、五头 loss、scope、数值准入门与资源路线不变，只做付费前窄修。

- bootstrap 改用 `venv --copies --system-site-packages`；回归真实创建 copied venv，并执行 worker 的同一 executable/non-symlink 判定。
- 生命周期统一为 `prior wall + maximum lifecycle + 60 秒 kill grace + 360 秒终态确认 <= 10800`；receipt 显式携带 prior 与累计上界，trigger 为 provider start 加主体窗口及 kill grace，guard 在余下 360 秒内确认 0 Pod。正常提前释放仍须 reviewer receipt，absolute trigger 是唯一自动 exact-Pod 止费例外。
- 静态上传仍只有两份 bundle 与两份 receipt；Pod 核验后的 host→Pod runtime control 只开放 live-resource、lifecycle、paid-segment 三类 16 KiB 以内、`0600`、canonical、content-addressed JSON。worker CLI 在动作前校验路径、schema、bytes、content SHA 与三者交叉绑定。

定向结果：Plan 099 `14 passed`；Plan 094 lifecycle 与 Plan 087 terminal 回归 `9 passed`；freeze CLI、Ruff、compileall、shell syntax 与 `git diff --check` 通过，freeze SHA-256 为 `8823d7d1b3b503c253f0b20c02e80a96b34ba9d7755401b47fb7950120405959`。一次独立只读窄复核未发现 High/Medium finding。未运行真实模型、GPU/RunPod、Docker、付费 API，未上传资产，未读取 v9 test、qualification 或旧 unseen 正文。
