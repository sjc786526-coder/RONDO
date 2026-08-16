# Plan 037 阶段一最终窄修

针对 `d5aae82` 的复验报告核对后，三个问题均确认存在并完成窄修：

- pair receipt 改为绑定两侧 canonical b10333 deployment manifest。两种候选路线均保留：adapter on/off 强制共享
  实际 base GGUF，paired GGUF 强制两侧工件不同；共同 converter、quantizer、quantization 及微调侧 formal source
  adapter exact tree 均逐文件重验，额外文件、目录、symlink 或非普通文件在 invocation 前拒绝。
- 新增 0600 private pair-evidence locator，记录 receipt、source manifest 与七项实物 locator。正式文件入口加载时重建
  `BuiltPairReceipt` 并重新哈希全部来源；`verify-import`、`pack`、`import-results` 均贯通 `--pair-evidence`，v2 缺 evidence
  继续 fail-closed，legacy v1 保持兼容。
- RunPod recovery runbook 改用正确的 `runpodctl ssh info`，统一重启后的 host/port，显式重新进入远端 shell并传入 Pod ID；
  completed、pending、无可恢复 receipt 三态分门。pending 只做条件式 adapter reload、finalize、远端 verify 和 SCP，不重复训练。

验证：直接相关 unittest 75/75 通过；130 条 no-model preflight 保持 65/65、26 个 source group、26 个 split group、
`waiting_for_l6_outputs`、0 model call；470 条 train-only bundle 实物校验通过，manifest
`e429ca575c3f9c35f0f66a6606a26e3f7e669dad262e4837fba01dd247ec56ad`，tar
`45f098d64ac61aad504ab8ebab40afc029bd5ffd9c00cdae0e65a4e5b351018c`，census
`fdb96728dedb40f9fd7b650b89e5304ab0ab61ef9f3c4c16b5ec0af378e4155e`。Python compile、17 个 runbook bash fence、
entrypoint `bash -n`、`runpodctl ssh info --help` 与 `git diff --check` 通过。训练与 pair 最终独立复验均无阻断。

本批没有重建训练 bundle，没有下载/加载 8B、训练、转换或运行 130 条模型输出；没有创建、修改、上传或删除任何
RunPod/HF 对象，也没有新增费用。阶段二仍须用户单独授权。
