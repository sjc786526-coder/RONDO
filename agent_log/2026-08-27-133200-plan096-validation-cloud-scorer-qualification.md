# Plan 096：Validation 云端 Scorer 资格与任务对齐参考上界测定

日期：2026-08-27 ｜ worktree：`.claude/worktrees/096-validation-cloud-scorer-qualification`
｜ 分支：`worktree-096-validation-cloud-scorer-qualification` ｜ 起点：`main@00502a9`

合同：`plan/096-validation-cloud-scorer-qualification-and-headroom-execplan.md`。

## 1. 实质性修改

- 在既有 `CloudPublicationScorer` 增加同一请求、parser、retry 与 identity 路径上的 eval-only scalar/usage observation；新增
  `codex-publication-critic-cloud-eval` one-shot binary。产品 service/client/wire/verdict、local worker、default-off 与发布行为不变。
- 在 `eval/rondo_eval/publication_critic/cloud_quality/` 增加 Plan 096 薄层：freeze/static contract、Decimal 费用门、write-once
  commissioning/formal archive、blind runner、恢复、独立复算与 exact 1.7B/4B 历史投影。复用 Plan 073 operating curve/质量门和既有严格
  secret loader，没有复制第二套 Publication Critic 测评体系。
- 冻结 descriptor/quality contract 放在 `eval/locks/`；tracked 正式结果为
  `eval/results/publication-critic/deepseek-v4-flash-cloud-quality-v1.{json,md}`。JSON 含 freeze、55 个本地 score/label、完整 curve、聚合、
  8 个 disagreement、usage/cost 和历史对照；provider 调用记录不保存请求/响应正文。

## 2. Commissioning 与正式轮

首轮真实 synthetic commissioning 使用 4096 output-token 上限，55 次单 attempt 得到 54 个成功 scalar；1 个回复恰好
`completion_tokens=4096` 并因截断被严格 parser 正确拒绝。该配置累计 `0.3987545 RMB`，整轮作为无效 commissioning 独立保留，未与后续
结果拼接。保持模型、prompt、默认 thinking/high effort 与 parser 不变，仅把 output headroom 提升到 8192；在 source commit
`7bdcad9196d4e7a2de39f6618e0d193476b0d6e6` 和新 namespace 完整重跑后为 55/55、55 attempts、零 typed failure、`0.3548550 RMB`。

正式 freeze SHA-256 为 `4497883159a2d278ca6611b6b6ce4101efec09d56f319e357c9214fbfd31836b`，绑定 canonical validation
release SHA-256 `757dd624c3d47f87dd5683d24f9f1753b1dbbffb42fdeff567c9e3e5e0b71a91`。唯一正式 namespace
`plan096-formal-20260827T201304Z-validation-55` 从空目录开始，完成 55/55 有限 scalar、零最终 typed failure、56 provider attempts。
其中 `pc064-rpg-webhook-mask-rewrite` 首次为冻结 policy 允许的 `ProviderTransientFailure`、无 usage，按 1 RMB fallback 计费后同一
logical call 第二次成功；未重跑任何有效 scalar 或有效负向质量结果。正式轮费用 `1.3855704 RMB`。

## 3. 正式结果

终态：`CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH`。

| 指标 | DeepSeek V4 Flash cloud | exact 1.7B base | exact 4B base |
|---|---:|---:|---:|
| False PASS | 8/21 | 6/21 | 12/21 |
| False REWRITE | 0/34 | 13/34 | 4/34 |
| balanced accuracy | 0.809524 | 0.665966 | 0.655462 |
| ROC AUC | 0.840336 | 0.616947 | 0.621849 |
| Boundary strict win | 15/19 | 15/19 | 13/19 |
| Within-PASS strict win | 3/7 | 6/7 | 6/7 |
| admissible operating point | 否 | 否 | 否 |

cloud fallback threshold 为 `0.9`。False PASS `8/21` 未达到 `<=5/21`，所以资格失败；ROC AUC 与 Boundary strict win 两个预冻结
threshold-free 门均通过，所以 headroom 为 HIGH。该结果说明任务分辨能力明显高于两个本地 base，但现有分数/error trade-off 仍不能满足发布
质量底线；不解锁 Plan 097，也不授予产品资格。cloud/local template、raw score、threshold/calibration、tokenizer/window、延迟与资源不可直接等同。

## 4. 验证

| 门禁 | 结果 |
|---|---|
| Plan 073/079/096 相关 Python unittest | 94/94 passed |
| `just test -p codex-publication-critic` | 62/62 passed |
| `just clippy -p codex-publication-critic` | 通过 |
| `just fmt` | 通过 |
| compiled binary 55 项 loopback lifecycle | 55/55、55 attempts、零 failure |
| formal 独立复算 | freeze + canonical release + scores 与 archived result 逐字段一致 |
| 全 workspace | 未运行；按任务合同只跑受影响模块 |

重型 Rust 构建/测试全部通过仓库 `just` / `scripts/with-build-lock.sh`，唯一 target 为主物理根
`.codex/cargo-target/rondo-multi`。最终审计发现测试工具曾在 worktree 留下 12 KiB 的空目录
`multidev/codex-rs/target/nextest/local`，其中没有 build artifact；已用精确 `rmdir` 清除，交付时 worktree 与 `/tmp` 均无第二套 target。
未使用 Docker、GPU、RunPod 或真实本地模型。

## 5. 费用、数据与 ignored 资产

Plan 096 共 165 个 logical calls / 166 个 provider HTTP attempts：两轮 commissioning 与正式轮合计 `2.1391799 RMB`，低于 30 RMB
硬上限，剩余 `27.8608201 RMB` 不转移为后续授权。成功 attempt 按 provider usage 与冻结谷时价卡计算；唯一无 usage transient attempt 按
1 RMB fallback 计入。

task-owned ignored archive 位于主物理根 `eval-data/publication-critic/plan096/`，共 179 个文件、约 948 KiB，包含 synthetic input、
environment/commissioning/formal freeze、body-free call records、authority 与复算输入。只向 provider 发送 validation 的 bounded
`PublicationPacket` cloud projection；labels/pairs/split supervision、unseen、训练集、源码与密钥均未发送。`.env.local` 未被打开、搜索、打印、
复制、修改或 source，只由既有严格 loader 静默读取 allowlisted `DEEPSEEK_API_KEY` 并注入目标子进程。

## 6. 待审边界

实现、正式结果与当前 WBS 状态已准备提交 task branch。按 ExecPlan decision 013，首次独立审查接受前不更新
`doc/WBS-COMPLETED.md` 或把 Plan 096 写成最终验收完成。未经用户批准不合并、不推送、不重命名/归档分支、不删除 worktree。
