# Plan 098 方向性整改最终复验窄修实施记录

日期：2026-08-28
状态：`DIRECTIONAL_NARROW_REMEDIATION_IMPLEMENTED / FINAL_REVIEW_PENDING`

## Finding 闭合

- continuity decoder 改为保守三路规则：仅 `N/A - max(PASS, FAIL) > na margin` 时输出 `N/A`；否则只有 `PASS > N/A` 且 `PASS - FAIL > pass margin` 才输出 `PASS`，其余全部 `FAIL`。focused regression 固定 weak-N/A-top + strong PASS-over-FAIL、N/A margin 相等、决定性 N/A、明确 applicable PASS 及 gate 结果。
- 标准 reference selector 现只暴露 `DevelopmentRelease.select_and_freeze_validation_decision_config()`。该入口从实际 v10 release 机械派生 revision、manifest SHA、validation candidate SHA 与 labels，并要求调用方提供的 candidate ID 顺序与文件行序完全一致；纯选择核降为内部函数，不再接受公开调用者自报 identity/labels。
- v9 原 `continuity-context` 盲审员以 role `plan098-blind-reviewer-continuity-context` 对原 patch SHA `8f92bc725f265f95fe448bb391875dea09d9a48b8e28c07a274b08c777c7ece4` 的同一 11 个 replacements 完成窄复验：`accept`、0 finding，review SHA-256 `9c6c01ae78f7bee5238e77b1635b5c6c2107e66b11f7e8d2448dc9e6c49dd9f6`。盲审员确认未读取 v9 test、旧 unseen、qualification sealed 正文或其他模块。
- 按审查决定只修正实时陈述：decision config 绑定 implementation bundle，directional design 另绑定 commit 与 bundle；历史实施日志不回写，也未增加冗余 commit 字段或通用审计设施。

## 新身份与正式重建

- decision implementation commit：`a9a856ad8f742f62474ba8bf473769d2fca1c571`；contract/decoder/projection/metrics 组件 SHA-256 为 `bd427310...29cd0` / `5ceee8c5...0cb4a8` / `3a651e1a...f512a` / `1a9aadb2...51ec`，bundle 为 `00700f45afb6c5f7bb97cc90ecd3f859c82f1cc604e5c242abcd9590284d6201`。
- directional runtime commit：`535bfbe9ba31b3110c243b3af15230a2ff5c382b`；component SHA-256 `1d68f86291a64f10697f96e8dc35a8a8210631fcccff92fbf4f3296a62f25212`，bundle `b1706139a755b857d8dc8f909490c31a42c2ace3e6123012f78679dc1dd1e869`。
- directional design/config SHA-256：`414241ff0e9c41d7f606b1acbf3200baccc8f220a3478f3c49697fa0317ecd7b` / `77ae901d52ba0a616f97df6fcf9beaf1ca3f81c7ef7870f1e05c4f49309878c2`。
- v10/qualification manifest SHA-256：`595768fad0f17ff49cb3aea04d9cfb607fa9fde537c6cbc196cabc6e7bed7172` / `366983baf08412e8a26662d974407721d2d11c521862d7f606e80c4f3a8dad82`。
- 两份正式 release 从空目录重建。复现 CLI 的正式路径门在写入前按预期拒绝临时路径；随后使用 finalizer 已有的 `enforce_config_paths=False` 复现入口在独立临时目录生成，两棵 release 与正式输出 `diff -qr` 均为空。临时复现与备份目录已清理。

## 验证与边界

- focused qualification/directional 17/17；directional/qualification/successor 33/33；旧 contract/training-data/identity/v7 43/43，合计 76/76 定向 Python 回归通过。
- v9 tree 在审查基线和当前均为 `65be7257a33717331240c0c4c5061da580ab9871`；v8 均为 `63981483baa00c671987d4b82887909fcc320690`。v9 test、旧 unseen 与 qualification sealed 正文未由总执行者读取；没有运行 Rust/Cargo、Docker、真实模型、GPU、付费 API 或产品动作。
- ignored namespace `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098/` 当前 `1.8M`；其中本轮复用并更新 `directional-remediation/`（`120K`）的 continuity review，`qualification-set/`（`248K`）正文未改。两者继续保留至最终复验结束，之后可按用户需要清理。

## 待办

- 完成格式、diff 和 clean-tree 门禁后提交本工作树，通过指定 Codex queue 申请最终复验。验收通过前不恢复 Plan 098 完成态、不启动工作包三。
