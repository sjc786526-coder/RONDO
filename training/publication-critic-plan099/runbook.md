# Plan 099 阶段 B 运行手册

本手册只执行 `freeze-lock-v1.json` 锁定的唯一方案。只有指定队列中存在审查者明确回复
“Plan 099 阶段 A 验收通过，批准进入阶段 B”及完整外部边界，才可执行真实模型、上传、RunPod、
GPU 或付费步骤；每次启动仍须核对该批准及本轮预算和资源 receipt。

## 固定边界

- exact base：`Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`；
  权重 SHA-256 为 `117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9`。
- 只训练五个 FP32 无 bias 线性 head，共 22,528 个参数；BF16 backbone 冻结、eval、no-grad；16 次完整
  train cohort macro update，不得改模型、scope、loss、数据、门限或另开路线。
- RunPod Secure Cloud、`US-TX-3`、单张 `NVIDIA L40S 48GB`、exact image
  `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`、20GB container disk。
- 复用网络卷 `mwemzrn33y`，预计初始 70GB、上限 100GB；不新建卷，不删除该卷；任务 root 必须匹配
  `/workspace/rondo-plan099-*`，历史 root 只读。
- 同时最多 1 个计费 Pod，累计最多 2 个；所有任务 Pod 的累计计费墙钟硬上限为 10,800 秒，其中每个 Pod
  按 `prior + maximum_lifecycle + 60 秒 worker kill grace + 360 秒终态确认` 计入。第二个 Pod 只允许在首个
  已确认不存在且属于技术恢复时创建。库存紧张只使用根目录 `scripts/create-runpod-when-ready.py` 抢卡。
- 动态预算为批准时实时可用余额减已知未结/延迟费用，再减现有网络卷 6 小时实时保留费后取非负值；不得充值。
  每段运行前刷新预算快照，并确认 commissioning、formal、候选回传、预释放审查等待及 stop/delete 收口均可覆盖。

## 资产和环境

阶段 A 静态资产只生成并允许上传四个文件：`phase-a/source-bundle.tar`、`source-bundle-receipt.json`、
`data-bundle.tar`、`data-bundle-receipt.json`。data bundle 的物理成员只来自
`training/publication-critic-v10/`，含 train/validation，无 v9 test、qualification sealed 或旧 unseen 正文。
上传后先逐个校验 receipt 中的 archive SHA-256；`runpod-bootstrap.sh` 只用 source bundle 建立临时引导树，随后
由 `assemble-execution-root` 分别安全解包、逐树验签 source/data，合并至一个全新的 task-owned source root，最后
重新执行 freeze 校验。bootstrap 必须以 `venv --copies --system-site-packages` 生成 task-owned 实体 Python；该路径
通过 worker 的 executable/non-symlink 判定后才复用 exact image Torch。训练不得直接在临时引导树中运行。
远端公共下载只允许 `asset-contract-v1.json` 中 exact repository/revision/file 列表；先校验全部 SHA-256，
再加载模型。不得上传 `.env.local`，不得把密钥当 shell 文件 source。

Pod 独立核验后，host→Pod 运行时控制 JSON 只允许三类：live-resource receipt、Pod lifecycle authorization、
paid-segment authorization。仅本次最后一个 replacement Pod 使用由已核验实际 Pod ID 唯一派生的易失控制根
`/run/rondo-plan099-{validated_actual_pod_id}/runtime-control`；首 Pod `z1z3m7n90nz4xr` 已退役且必须拒绝。该根、父目录及三个 role 目录必须是
普通非 symlink 目录且权限
`0700`。每份文件必须是普通非 symlink 文件、不超过 16 KiB、权限 `0600`，并放在
`{runtime_root}/{live-resource|lifecycle|segment}/{content_sha256}.json`；文件名必须等于经对应 schema 校验后的
content SHA-256。三类文件只由冻结 CLI 生成并逐字节复制，禁止手工编辑或重算：content SHA 基于 core 的 canonical
JSON，实际文件则是确定性的 `pretty_json_bytes_v1`。worker 在启动任何 CLI 动作前逐文件校验路径、权限、文件字节、schema、content SHA 与
三者交叉绑定。budget snapshot、guard/release receipt、环境或训练状态、provider 原始响应、任意第四类 JSON、
模型、日志及密钥均不在此运行时上传边界内。容器或进程环境重建、恢复或进入新 segment 前，都从 host 权威文件
重新逐字节复制并完整验证，不依赖 `/run` 持久化。首次使用及每次环境重建时必须在已核验 replacement Pod 内 exclusive 新建上述
普通目录；若 exact task-owned 易失根已存在，先精确清空并重建，禁止复用其内容。实际 ID/name 必须同时绑定 live-resource、lifecycle、segment
与 worker 参数；错 ID、其他 `/run` 路径和网络卷副本均 fail-closed。本例外不扩展到第三 Pod。

Pod 创建后，训练前独立核验实际 provider、Secure Cloud、`US-TX-3`、L40S 数量/显存、单价、镜像、20GB
container disk 和卷 `mwemzrn33y` 的挂载；任一项不符立即释放，不进入 commissioning。创建响应不确定时先按
exact name 对账，不得重复创建。将核验结果、source/data receipt、模型 snapshot receipt、版本、GPU、价格和预算
快照写入任务 root 的小型 JSON evidence。

每个 Pod 的唯一授权链路是：先刷新 launch budget snapshot，并用冻结 CLI 生成 live-resource receipt；在二者和
`pod_started_at` 均不超过 300 秒时生成 immutable lifecycle authorization。每次后续付费动作紧邻执行前再刷新 budget
snapshot，最后生成 fresh paid-segment authorization。若已结束任务 Pod 的累计
保守墙钟为 `P`、本 Pod 主体窗口为 `L`，则必须满足 `P + L + 60 + 360 <= 10800`；绝对 termination trigger 固定为
`pod_started_at + L + 60`，确认 deadline 固定为 trigger 后 360 秒，因而最晚 0-Pod 确认不会越过累计硬上限。
segment 必须逐哈希绑定 budget、resource、lifecycle、exact Pod id/name、实际 compute/container 单价、termination
trigger、60 秒 kill grace 与 360 秒终态确认预留；worker 的 `RONDO_PLAN099_MAX_SECONDS` 必须与 segment 完全相等。
所有云端 snapshot、artifact、state 和输出路径都必须在当前 `/workspace/rondo-plan099-*` task root 内；宿主 lifecycle
authorization 与 guard receipt 留在主物理根 Plan 099 ignored host namespace；按上述三类 runtime-control allowlist
把 resource、immutable lifecycle 和每段新生成的 segment 文件复制进 exact `/run` 控制根，供 bootstrap/worker
逐哈希绑定。网络卷内因 FUSE 呈现 `0666` 的旧 runtime-control 副本不得消费，并精确清理；`/run` 不得存放其他资产。

Pod 创建并独立核验后，必须先在主物理根 Plan 099 ignored host namespace 生成 lifecycle authorization，并在授权后
60 秒内以前台进程启动冻结的宿主 guard，由开发工具持有的长期 exec 会话持续托管；禁止 `nohup`、`setsid`、shell 后台符号、system service 或
宿主全局修改。取得 exec session id 后，armed receipt 中的 PID 必须仍存活且 exact Pod id/name、绝对 trigger
与 authorization 一致，并从另一条普通工具调用再次确认进程与 exec session 存活。上述闭合前不得上传、bootstrap 或使用 Pod。
bootstrap 本身也必须消费一个 fresh segment，
在 execution assembly、venv 或依赖动作前验证三类控制链；assembly 同时在 Pod 内 exclusive-create `runtime-local/source-identity.json`，
不从 host 上传第四类 JSON。已验 SHA 的外层只提取小型 bootstrap tree，随后立即以 `timeout --kill-after=60s` 在
segment `maximum_seconds` 内重新进入脚本；assembly、venv、pip、pip-check 与 freeze 校验全部处于该机械窗口。
固定 guard 调用轮廓如下（变量值均来自本轮已核验 receipt）：

```bash
env RONDO_PLAN099_STAGE_B_APPROVED=1 PYTHONPATH=eval \
  python3 -B -P training/publication-critic-plan094/runpod-lifecycle-guard.py \
  --profile plan099 --authorization "$PLAN099_LIFECYCLE_AUTHORIZATION" \
  --terminal-helper training/publication-critic-plan087/runpod-terminal.py \
  --task-root "$PLAN099_HOST_TASK_ROOT" --armed-output "$PLAN099_GUARD_ARMED" \
  --result "$PLAN099_GUARD_RESULT"
```

正常提前释放仍只接受指定 queue 的批准 receipt 并走 `runpod-release.py`。Pod 预释放审查等待与绝对 trigger 取先到者：
guard exec session 必须持续到 trigger，或正常预释放后仍到点完成幂等 0 费用确认。每个付费 segment 前快速复核 session、guard PID、armed
receipt 与当前时间；任一消失或异常返回且没有成功 result receipt，立即用冻结 terminal helper 删除 replacement Pod 并确认 0 compute。
若批准先到，立即走 gated release；若绝对 trigger 先到，guard 无需 queue receipt，直接调用 exact-Pod helper 自动
stop/delete，并在 360 秒窗口内确认 0 Pod、compute `$0/h`。guard 不得取消，也不触碰网络卷；提前释放后它到点仅对
已不存在的 exact Pod作幂等零费用确认。此绝对截止例外只守住累计 10,800 秒硬上限，不授权提前释放、延后 trigger
或改变训练路线。

## Commissioning

bootstrap 后只允许显式下载 asset contract 中的 12 个文件，单 worker、exact revision、独立 task-owned cache：

```bash
HF_HOME="$RONDO_PLAN099_TASK_ROOT/hf-cache" HF_HUB_DISABLE_IMPLICIT_TOKEN=1 \
  "$RONDO_PLAN099_TASK_ROOT/venv/bin/hf" download \
  Skywork/Skywork-Reward-V2-Qwen3-1.7B \
  .gitattributes README.md added_tokens.json assets/skywork_logo.png \
  chat_template.jinja config.json merges.txt model.safetensors \
  special_tokens_map.json tokenizer.json tokenizer_config.json vocab.json \
  --revision e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc \
  --local-dir "$RONDO_PLAN099_TASK_ROOT/model/exact-snapshot" \
  --cache-dir "$RONDO_PLAN099_TASK_ROOT/hf-cache/hub" --max-workers 1
```

下载后用冻结 CLI `verify-snapshot --root ... --output .../evidence/model-snapshot-receipt.json` 校验 exact tree、
model lock 与逐文件 SHA；receipt 必须在 snapshot 目录外。未通过不得加载模型。

设置 `RONDO_PLAN099_STAGE_B_APPROVED=1`、exact image identity、任务 root、source root、segment authorization
等 worker 所需环境后，从 exact base 和独立空 `rondo-plan099-commissioning-*` namespace 运行 `start --run-kind
commissioning`。它只取 train 中每头一条 boundary 加一条 soft-only pair，执行 1 次非零更新，先原子保存完整
checkpoint，再评价，并停在 `recovery_required`。

必须由新的 OS 进程运行 `resume`：它只从 checkpoint 的完整模型、optimizer、precision、RNG、data cursor、
selection 和冻结 feature cache 恢复，逐字节复现 checkpoint 后评价，形成 recovery receipt。随后用小型临时回传
文件验证下载与校验路径。失败属于实现、环境、存储、传输或资源适配问题时，在总预算/墙钟/单路线边界内窄修并
重做 commissioning；不得把 commissioning checkpoint 当候选。

commissioning 只有在新进程复现成功后才能形成 `COMMISSIONING-PASS`；正式 `start` 必须显式读取并绑定该终态、
同一 source identity 与 freeze。commissioning 永远不能形成 `CANDIDATE` 或 `NO-GO`。

`capture-environment`、commissioning `start` 和新 OS 进程的 `resume` 分别使用 fresh segment；worker 的共同环境
必须显式给出 task/source root、三类 runtime-control path、exact image 和等于 segment `maximum_seconds` 的 timeout。
`start` 使用 `runtime-local/source-identity.json`、snapshot、独立 `rondo-plan099-commissioning-*` namespace、artifact/state
与 environment receipt；`resume` 复用相同 state/artifact 但必须是新的 worker/Python invocation。环境 receipt 绑定 exact
Pod；若发生已授权的第二 Pod 技术恢复，必须重新 capture，不能复用首 Pod receipt。

## Clean formal

commissioning 完整通过后，从 exact base 与全新空 `rondo-plan099-formal-*` namespace 运行 `start --run-kind
formal`。checkpoint/evaluation 固定在 2、4、8、12、16；每次严格 checkpoint-first。第 8 步停在
`recovery_required`，必须由新的 OS 进程 `resume` 并复现后才能继续至 16。最佳 checkpoint 只按预冻结排序自动
选择；所有 12 个 validation pair 闭合前不可准入。
控制状态在 checkpoint 落盘后和评价发布后都原子写回外部 state；进程若停在 `evaluation_pending`，新进程从已验证
checkpoint 恢复并补齐或逐字节复现 evaluation。正常暂停也只能从 latest 完整 checkpoint 恢复。到达第 16 步后，
若最佳 checkpoint 尚未被独立新进程复现，控制器再次停在 `recovery_required`，复现最佳点后才允许冻结终态。

若轨迹因代码、依赖、OOM、存储、连接、保存或恢复等技术正确性问题无效，可在同一 exact recipe 和总边界内
修复，从相称完整 checkpoint 恢复，或清空本任务无效 formal namespace 后最多用第二个 Pod clean rerun。若轨迹
有效但质量未过冻结开发门，终态必须是 `NO-GO`，不得追结果调参或开启第二路线。

formal `start` 使用全新的 `rondo-plan099-formal-*` namespace、空 artifact root、commissioning terminal state 以及 fresh
segment。step 8 后每个 `resume` 都是新的 OS 进程并使用新的 segment；若 step 16 后 best 尚未 fresh-process 恢复，
继续以同样方式运行最后一次 `resume`。不得在同一 worker 进程内伪造 fresh-process seam。

## 候选回传和资源收口

形成 `CANDIDATE` 时，在 Pod 预释放审查前运行 `export-candidate`，并把完整 `candidate/inference-ready/`、
decision config、candidate manifest 及允许的小型 evidence 下载至主物理根
`eval-data/publication-critic/plan099/`。本地重新执行 exact-tree、bytes、逐文件 SHA-256 和 manifest 校验；不得只回传
adapter 或摘要。完整 recovery checkpoints、optimizer/scheduler/RNG state、feature cache、venv 和 HF cache 留在网络卷
的 Plan 099 root。`NO-GO` 只回传足以证明有效负向结论的小型结果与恢复证据。
`export-candidate` 会从全部五个不可变 checkpoint/evaluation 重新计算最佳点和严格 step-zero 改进，核对最佳点的
fresh-process recovery 与 retention marker，再输出完整 inference-ready tree、decision config、development
assessment、recovery receipt、controller state 及外层逐文件 bytes/SHA-256/exact-tree manifest。本地回传后必须运行
`verify-candidate`，不得信任传输前的摘要。

核心训练、fresh-process 恢复、正式评价、候选/`NO-GO` 冻结和回传完成后先提交 tracked 变动，通过指定 queue
申请“Plan 099 阶段 B 核心任务与 Pod 预释放准备”审查并停止。正常提前释放须先收到审查者明确回复“确认不再需要
Pod，批准立即释放”；不可移动 absolute trigger 先到是唯一无需 queue receipt 的例外，由已武装 guard 自动释放。
收到正常释放批准后立即 stop/delete 所有任务 Pod并实时复核任务 Pod 为 0、compute 为 `$0/h`；
保留既有网络卷。批准释放后不得因文档整理重建 Pod。
释放必须把审查队列原文写成带 canonical content SHA-256 的 approval receipt，并通过冻结的
`runpod-release.py` 调用 exact-Pod terminal helper；wrapper 固定审查 thread、批准短语和 `rondo-plan099-` 名称前缀，
最终仍须得到 0 task Pod 与 compute `$0/h` 的实时回执。
