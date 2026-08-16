# Plan 037 阶段一审查窄修

复核确认四项审查发现均真实并完成窄修：LoRA target 改为只完整匹配 Transformers runtime 文本层的单个 PEFT regex，
实际 targeted modules 与 trainable LoRA 参数再次 fail-closed；formal pair receipt 只从 completed RunPod training receipt、
冻结模型/runtime/chat/request 合同和实际 artifact source 构建，v2 导入拒绝裸 mapping，微调侧 manifest 必须逐文件等于
receipt adapter tree；悬空 attempt 显式记录为 infrastructure failure 后只继续剩余样本；阶段二 A-J 上传、安装、
smoke/formal、止费、下载验真、一次恢复重启和删除命令已落盘。另补 completed receipt 最后写入前中断时仅接受逐字一致
orphan manifest 的恢复。

直接相关 unittest 68/68 通过；真实 no-model preflight 仍为 130 条、65/65、0 model calls、
`waiting_for_l6_outputs`。470 条 census 未变：145,360 tokens，min/P50/P95/max 278/311/331/333，超限 0，470/470
prompt 全 mask、completion 非空且有 label。最终 bundle manifest 为 `e429ca57…56ad`，tar 为 `45f098d6…018c`，
目录与 tar 解包后均通过 470/11 文件 verifier；`py_compile`、entrypoint `bash -n`、JSON、敏感/大文件和 diff 门禁通过。

未创建或修改 RunPod/HF 对象，未上传、付费、下载 base 权重、加载 8B、训练、转换、调用模型/API 或运行 130 条模型输出。
旧 ignored bundle 只移动到 `/tmp/plan037-stage1-before-orphan-recovery.lZFK7A`，未删除。
