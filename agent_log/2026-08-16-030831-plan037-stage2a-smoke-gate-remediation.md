# Plan 037 阶段二A：structural smoke 门禁窄修

时间：2026-08-16 03:08 PDT

- 审查问题属实：原 smoke 把“每侧至少一个 decision”误作正式 130×2 前置条件，会让合法的结构化失败、超时或拒绝
  永久阻断正式运行。
- smoke receipt 升级为任务内 v2：两侧固定身份串行会话完成、每条请求形成合法 terminal union 且进程清理完成即
  `passed`；decision 与各终态数量仅记录为诊断，formal gate 会重算并核对这些字段。
- 实际 subprocess 清理后增加存活检查；加载、身份、连接或基础设施异常仍直接失败，不会被样本终态伪装成通过。
- deployment fallback 仍只允许由转换或冻结 b10333 LoRA 加载不兼容触发；零 decision、结构化失败、超时或拒绝均
  不得触发换路线或重新训练。
- 回归覆盖两侧 0 decision、同时包含结构化失败/超时/拒绝仍通过 smoke 并实际进入 formal runner；未创建 RunPod/HF
  对象，未上传、加载真实模型、训练、转换或产生费用。
- 验证：阶段二A直接相关 unittest 92/92 通过；runbook 29 个 Bash fence、RunPod entrypoint `bash -n`、改动
  Python `py_compile` 和 `git diff --check` 均通过。训练与转换 bundle 未变化。
