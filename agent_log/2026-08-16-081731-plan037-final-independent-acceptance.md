# Plan 037 最终独立验收（2026-08-16）

## 结论

- 审查提交：`cc2f6440f4601220fb3349cdd39885d8e7cef896`。
- **验收通过，Plan 037 任务目标完成。** 470-only 训练、真实正式 LoRA、同源 paired-GGUF、本地
  `130 × 2`、canonical pair evidence 与 Plan 036 正式导入均有可复验实物；未发现需要重训、重跑模型或扩建审计设施的
  功能性阻断。
- Local M4 **尚未完成**：当前只到 390 行输入 `ready_for_blind_packaging`，没有运行裁判、解盲或人判，也没有质量结论。

## 独立复验证据

- `verify-artifacts` 重新逐文件校验 formal 输出，得到 `29 files / verified`，manifest
  `ec4b9ac5…def37`。training receipt `d551e5cf…c97f` 为 `completed/formal`，绑定 470 条
  completion-only train、118 steps / 2 epochs、loss `0.2667613620`、冻结 recipe `eeb98a18…84b1`
  和隔离 reload `ff5cec5c…0461`。adapter 为 178,328,936 bytes、`146d6871…4c41`；476 个 tensor
  精确对应 238 组 LoRA A/B，没有 vision/projector/`lm_head` 命中。投影 ID 与 470 条 train 精确相等，
  与 130 条 validation 交集为 0。
- conversion receipt `bc471f50…2600` 和 manifest `06ff1734…7530` 绑定官方 BF16 revision、正式
  adapter tree、同一 converter/quantizer/Q4_K_M 合同及两枚实际 GGUF：base `9d2ae96a…9eeb`、fine-tuned
  `c3f34fe8…6621`。pair 目录使用这些文件的同 inode hardlink，不是未验真的副本。
- 正式 `verify-import` 重新读取 private locator，并流式重哈希七项 source（含两枚 5.198 GB GGUF），返回
  `ready_for_blind_packaging`。390 行为三侧各 130、各批 65/65；本地 journal 为 260 attempt + 260 唯一
  terminal，全部为真实 decision。两侧 server log 分别加载实际 base/fine-tuned GGUF，均为 b10333、单 slot、
  12,288 context，完成后各有一次 cleanup。
- RunPod MCP 实时只读复核：Pod、network volume、endpoint、template、registry credential 均为 0；12 小时账单
  精确为 `$1.404635605867952`（GPU `$1.3439874555915594`、Pod disk `$0.0606481502763927`、其他为 0），
  低于 `$12` 批准上限和 `$25` 余额硬边界。HF `whoami` 为 `WHU-SJC`；候选 model repo 查询为空，本任务未使用
  HF 计算或持久化。
- 本地 GPU compute-app 查询为空，监听端口中没有任务使用的 `18437`，没有 `llama-server` 进程。当前五个直接相关
  unittest 模块合计 **96/96 通过**（核心四模块 85，b10333 pair 11）；`git diff --check` 通过。执行日志中的
  `89/89` 没有保留精确选择命令，但被当前更宽的 96 项复验覆盖，不作为阻断。

## 审查中处理的问题

- `doc/WBS.md` 原先沿用旧分支的 Multi 状态，会把 current `main@2f73240` 已合入的 M-1 写回“首个增量待定”。
  已做窄协调：仅保留 Plan 037 的 L6 完成 / Local M4 待执行变化，同时恢复 Multi M-1 已合入、M-2 为下一阶段的
  当前事实；未改 Multi 源码、子 WBS 或并行 worktree。
- Pod 删除后没有本地保留 smoke 专属 pending/reload receipt 或逐次五分钟监控流水。因此本轮可由正式 118-step
  receipt、同 recipe 隔离 reload、最终账单桶和资源终态证明训练链与费用结果，但不能事后独立重放“smoke 必然先于
  formal”的时间顺序或监控采样频率。按个人项目的轻量验收尺度，此为非阻断的可复核性限制：最终功能和预算均有实物
  证明，不为补历史证据重建监控系统或重新训练。以后同类云任务保留一份简短时间戳 smoke/monitor 日志即可。
- training receipt 中的 `$0.265714` 是 receipt finalize 时的阶段累计成本，不是最终任务总账；最终总额以 RunPod
  billing 和完成日志的 `$1.4046356059` 为准。本次未超预算，不要求为已冻结 receipt 追加新字段。

## 替用户作出的决定

1. 接受 `paired_gguf` 作为本轮正式部署路线。它由 adapter converter 的实际格式不兼容触发，只改变部署格式；没有第二个
   训练 recipe，也没有依据 validation 质量选路线。
2. 不补建 HF repo、不补上传本地工件。当前本地哈希验真副本已满足任务合同，事后新增远端状态没有必要。
3. 接受上述 smoke 顺序/监控频率的轻量证据限制，不重训、不补复杂审计；正式训练、adapter reload、产物身份、费用和
   清理均已得到足够功能证据。
4. 下一 Local 工作只使用现有 390 行输入进入正式 M4 盲化、裁判、解盲与人判；不得根据当前 allow/deny 分布继续训练或
   提前宣称 M4 通过。涉及真实裁判 API、轮数和费用时仍按 WBS 单独授权。
5. 本次只提交 037 worktree 的 WBS 协调与验收报告；不合并、不推送、不重命名分支，等待用户批准交付。

## 未运行边界

本审查没有重新启动 8B 模型、训练、转换或 260 次推理，没有运行 Opus/真实裁判、解盲、holdout、Cargo、Docker、CI
或全量测试，也没有创建、上传、修改或删除任何远端对象。
