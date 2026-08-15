# Plan 036：Local M4 本地离线三方盲评准备设施

日期：2026-08-15 ｜ 分支：`worktree-036-local-m4-offline-harness`

## 实质修改

- 冻结全部 130 条 synthetic validation 的 body-free cohort；source / near-duplicate 联合闭包确定性分为
  65 / 65，两批各 13 个组。
- 新增 Local M4 离线 CLI 与机器合同：canonical L6 pair receipt、三方完整导入、同审批输入深比较、匿名
  SHA-256 Latin-square 打包、裁判结果身份校验、全部批次先验后私有解盲和纯事实聚合。
- 冻结裁判 prompt 与 side output、L6 receipt、judge result、blinding、holdout summary 模板；正式私有目录
  限定为 ignored `eval-data/cross-eval/<execution_id>/`，目录 0700、文件 0600。
- holdout 仅实现独立私有合同与严格批次计数白名单，公共投影不接受逐条字段；未读取或物化真实 holdout。

## 主要整改

- 独立审查发现并复现了短 side 标签/模型路径泄漏、L6 pair 只有输出自报、holdout 投影 fail-open、第二批结果
  失败后残留第一批解盲文件、正式私有路径未限定等问题。实现改为 receipt 内容哈希绑定、上下文与明确短标签扫描、
  nested exact whitelist、全批次先验证再写出、ignored execution scope，并补齐负向回归。
- 普通 `local workspace` 是审批语义，不能一律当身份泄漏；扫描规则仅拒绝 standalone/身份语境 side 标签、明确
  模型工件路径及 receipt 提供的实际私有模型标识。真实 130 条冻结 target 已做无误杀回归。
- 位置算法从运行时 RNG 改为私有 seed + SHA-256 label 排序，避免未来重建依赖 Python RNG 实现细节。

## 验证

- `PYTHONPATH=eval python3 -m unittest -v eval.tests.test_local_m4_cross_eval`：27/27 通过，0 skip。
- `python3 -m py_compile eval/rondo_eval/local_approval/cross_eval.py eval/tests/test_local_m4_cross_eval.py`：通过。
- 真实 `freeze-synthetic-cohort`：130 条，`synthetic-body-b01=65`、`synthetic-body-b02=65`，状态
  `waiting_for_l6_outputs`；cohort SHA-256
  `9dd901fff3df072ed65ff3962d1e4524255a5a42a3f810903d191457cb494b95`。
- `git diff --check`：通过。主工作区任务专用 preflight 目录保持 0700，receipt 保持 0600。

## 未运行与边界

未调用 Sol、Opus、任何模型/API或网络；未加载权重，未运行推理、训练、LoRA、转换、量化、Cargo、Docker、CI、
全量测试或完整测评。未读取 `.env.local`、`rondo.local.toml`、模型权重或真实 holdout。未开始 L6、正式 Local M4
或三选一人判定，未生成 fake Local 输出；Plan 033 baseline 只保留历史参考地位。
