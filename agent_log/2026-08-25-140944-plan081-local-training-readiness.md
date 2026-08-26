# Plan 081 本地训练路线就绪实现

## 实质修改

- 新增 exact 1.7B、冻结 v8 train/validation、非 PEFT 直接参数更新的 route 合同，以及 A40→L40S、单卡不超过 12 小时、
  总外部费用不超过 15 USD 且尚未授权的云端 handoff。
- 增加 Plan 081 专用连续控制薄层：typed train-only update 接缝、同 cohort validation 全指标与 signed pair margin、多 update/observation、
  观测后显式扩大实际参数 scope、base/previous/best 趋势、base incumbent/训练 best/候选/no-improvement 分离。
- 永久保存小型 observation；分离可裁剪模型评价快照与包含 optimizer/scheduler/RNG/data cursor/controller history 的完整恢复 checkpoint；
  保留 best/latest/少量 turning point，并用持久、并发安全的 attempt reservation 避免同一旧 checkpoint 连续重放覆盖。
- fake 路线始终声明不产生真实 research candidate、产品 GO、M3-C2/unseen 或云端授权证据；未修改 Plan 060/066 历史 validator。

## 审查整改

- 两轮内部独立审查聚焦 correctness，补齐观测驱动 scope、checkpoint data cursor、typed train 输入、validation cohort fingerprint、
  严格 staging 恢复、连续 replay attempt、公开 dataclass 校验与 train-only row/membership 不变量；均有 focused 回归覆盖。
- 第二次只读复核确认所有已报 P2 关闭，未发现新增或剩余 P1/P2；指定跨会话审查者的最终验收仍待执行。

## 验证

- Plan 081 fixture/fake 专用测试 10/10 通过；连同 Plan 060/066/073 精选历史回归共 17/17 通过。
- 5 个新增 Python 文件源码 compile 通过；环境未提供 ruff/pyright/black，未临时安装或同步依赖。
- staged diff whitespace 检查通过，未发现 task-owned 临时文件、pyc 或其它意外生成物。
- canonical `final-01-extracted` 无 unseen bundle 只读核对通过：train 128 candidates / 58 pairs，validation 55 candidates / 26 pairs；
  training identity `e727bb98fe956331441c0e354adbaa2559e25b5b7700b90dfd414fb59ed9bd01`，validation identity
  `cd24b1981c879a9522cb652b6151270827478dfdc2d4e517dc3373f10ece0c30`。

## 边界

未加载、推理或训练真实模型；未使用 GPU、Docker、Cargo、云资源、外部付费或远端写操作；未读取 unseen 正文、`.env.local`、
模型权重或 checkpoint；未修改其它任务工作树和 ignored 大型资产。当前仅能证明本地 fixture/fake 控制与现有无 unseen 数据接缝就绪，
指定审查者的 `LOCAL_TRAINING_READINESS_PASS` 仍待独立验收。
