# Plan 016 model-free launcher、模板与 CUDA 交接

- 入口 `main...origin/main` 均为 `fea01f86905459edb4e697f7ba2702802a5c1a5d`；创建独立
  `0812-plan016-local-launcher` worktree/branch。只读检查发现既有 canary post-audit worktree 有未提交修改，本批未进入或修改。
- 逐项复核 llama.cpp b10333/commit `08659901…` 的 `common.h`、`arg.cpp` 和 server README；配置/launcher 现显式生成
  原生 `--gpu-layers auto|all|N`、fit、512/256 batch、F16 K/V、no-mmproj、Jinja/template、flash、parallel 1，单卡固定
  split none/main GPU 0。4k smoke 与 8k baseline 只切换 context、GPU layers、fit，不引入 profile 或额外 argv 透传。
- 通过 HF CLI 1.27.0 只获取
  `mistralai/Ministral-3-8B-Instruct-2512@5b26027e7b19eeb4b7352e1fed3926375dd2cb4d/chat_template.jinja`；
  精确 11,912 bytes、SHA-256 `74eeb55fd3341286ec3fd44e902b7120721acc81cd394e96b431f85e93a1ea56`。外部文件与临时
  HF metadata 共 12,204 bytes；没有下载 tokenizer、GGUF、safetensors、mmproj 或其他模型资产。
- 模板保存于 `eval/templates/local-approval/`，exact JSON lock 保存 repo/revision/source/relative path/bytes/SHA。
  launcher 限制到 worktree 的固定 tracked subtree，拒绝 unsafe ancestor、symlink、路径/lock/config 漂移、size/SHA/文件身份变化，
  命令始终显式传模板，不回退 GGUF 内嵌模板。现有 CPU 包 `llama-template-analysis --template-file` 在未传模型、不启动 server/
  GPU 的条件下完成 parser/model-free 分析，只作为 Jinja parser 证据。
- receipt 升级 schema v2，新增不含密钥的 `serve_config_sha256`；该指纹与实际 command 共用唯一参数构造器，绑定模板摘要及所有
  服务参数，client 在 identity probe 后、请求前和响应后按当前配置重算。既有 PID/start ticks、listener、runtime/model
  SHA/path/id、endpoint、`/proc/<pid>/cmdline` 校验均保留；旧 v1 receipt fail-closed。
- focused 验收：
  - `/home/sjc/desktop/RONDO/eval/.venv/bin/python -m unittest discover -s eval/tests -p 'test_local_approval.py' -v`：
    从 Plan 016 worktree 执行，45/45 通过。
  - `/home/sjc/desktop/RONDO/eval/.venv/bin/python -m unittest discover -s eval/tests -p 'test_config_hardening.py' -v`：
    从 Plan 016 worktree 执行，8/8 通过。
  - `/home/sjc/desktop/RONDO/eval/.venv/bin/python -m unittest discover -s eval/tests -p 'test_config_and_artifacts.py' -v`：
    从 Plan 016 worktree 执行，27/27 通过。
  - `git diff --check`：通过；模板 stat/SHA/cmp 与 TOML/lock 一致性由 focused test 和轻量命令复核。
- 独立终审在最新 diff 上复跑同一组 80 项测试并通过；其指出的 binary 配置身份绑定、CMake `$ORIGIN` 转义和实际解释器
  命令证据均已闭合，无剩余阻塞 finding。
- Git 交付：实现提交 `c4a7fc1af55f97d67a4b59e80e718291211cdcad`，no-ff 合并提交
  `53abd670c361dd67fd85984a2ebb50a4d7f815d2` 已推送并通过 `git ls-remote` 核对；交付收口仅更新本 Plan/日志状态。
- Linux CUDA 后续以独立 source/build/runtime/lock 落地，先冻结 toolkit-only 工具链、Ada arch 89、完整 CMake argv、ELF/runtime/
  host dependency 闭包；无模型中间能力仅为 `linux_cuda_built_model_unvalidated`。只有 exact GGUF、Linux CUDA runtime 和本轮
  模板/launcher 合同汇合并通过 model-backed 4k smoke 后才能进入 `gpu_model_serving_validated`，8k baseline 仍需另验。
- 本批没有下载权重，没有安装 CUDA/Ninja/依赖，没有构建或启动 llama.cpp，没有运行模型/GPU/Docker/Cargo/Bazel/just，
  没有修改 CPU runtime lock/capability、实际 `rondo.local.toml`、`.env.local`、canary/L2a/paid-eval 或远端资源。
  Plan 015 仍为 `download_ready_blocked_on_user_approval`，整体部署不是“只差启动”。
