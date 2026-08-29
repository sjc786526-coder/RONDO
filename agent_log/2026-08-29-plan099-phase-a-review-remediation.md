# Plan 099 阶段 A 首轮审查整改

## 结果

- 候选复核改为验证全部五个 write-once evaluation artifact，仅要求最终 best 的完整 checkpoint、fresh-process recovery 与 retention
  marker 在线；完整 checkpoint 保留上限仍为 best/latest/step 8 共至多三个。早期 `assessment=None` 合法跳过排名，后续点仍可形成候选。
- fresh recovery 后清空 recovery pointer；paused resume 严格选择 latest。checkpoint 已原子发布但外部 pending state 尚未发布时，只允许采用
  下一个冻结观察点且其 controller 前驱、updates、selection、evaluation、source/freeze/namespace 全部精确一致的 orphan checkpoint。
- step 8 已完成 fresh recovery 且五点均无 decision config 时，正式轨迹现在以 `best=None` 正常冻结为有效 `NO-GO`；retention marker 已存在时
  验证并复用，覆盖 prune/marker 完成后 terminal state 发布前的崩溃重入。
- bootstrap venv 改为 `--system-site-packages`，安装普通依赖前后都断言镜像 Torch 为 `2.8.0+cu128`、CUDA runtime 为 `12.8`，依赖清单不安装
  或替换 Torch。
- 复用 Plan 094 lifecycle guard 并增加封闭的 `plan099` profile。正常提前释放仍需指定 queue approval receipt；只有 authorization 中不可移动的
  绝对 trigger 到达时，宿主 guard 才直接调用冻结的 Plan 087 exact-Pod helper，自动 stop/delete 并在 360 秒内确认 0 Pod、compute `$0/h`。

## 验证与边界

- `test_plan099_five_head_training.py`、Plan 094 delivery guard、Plan 087 terminal script 定向组合：`22 passed`。
- 新增覆盖裁剪后 candidate export/local verify、early-none→candidate、all-none→`NO-GO`、step 12 continuation、orphan checkpoint、terminal
  retention reentry、venv Torch 可见性合同、absolute trigger 与 exact Plan 099 terminal 参数。
- `validate-freeze`、Ruff format/check、Python compile、shell syntax、`git diff --check` 均通过；freeze 锁新增 Plan 094 guard 与 Plan 087 terminal helper。
- 未运行真实模型加载、推理或训练；未使用 GPU/RunPod/Docker/付费 API，未上传下载外部资产，未读取 v9 test、qualification sealed 或旧 unseen
  正文。阶段 B 仍未授权。
