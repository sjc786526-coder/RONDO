# Plan 037 阶段二完成记录（2026-08-16）

## 结果

- 唯一 RunPod 对象为 `iudn1ajhkkvjsr`：Secure EU-SE-1 A40 48 GB，40 GB container + 100 GB Pod volume，
  GPU `$0.44/h`、运行总费率约 `$0.459/h`。最终账单 `$1.4046356059`（GPU `$1.3439874556`、Pod disk
  `$0.0606481503`、network volume `$0`），与起止余额 `$25.000000 → $23.5953643966` 的差额除浮点舍入外一致；
  任务结束时 Pod/network volume 列表为空、`currentSpendPerHr=0`。未创建 template、registry
  credential、network volume 或 HF repo，未上传 HF，也未产生 HF 新增费用。
- frozen train-only bundle 与官方 BF16 revision 在远端重新验真。真实 smoke 完成 1 optimizer step、238 个文本
  LoRA target 和隔离 adapter reload；正式 recipe 未漂移，训练完成 118 steps / 2 epochs，train loss
  `0.2667613620381463`。completed training receipt 为 `d551e5cf…c97f`，adapter 为 178,328,936 bytes、
  `146d6871…4c41`，29 项 formal 工件已先回收本地并逐文件验真。
- `convert_lora_to_gguf.py` 实际把 rank-16 adapter 展开成 309 个完整模型张量和约 17 GB GGUF，故按转换兼容性
  转入同源 `paired_gguf`，没有重训或依据 validation 选路线。最终 base/fine-tuned Q4_K_M 分别为
  5,198,378,592 / 5,198,378,560 bytes，SHA-256 `9d2ae96a…9eeb` / `c3f34fe8…6621`；14 项 conversion
  工件的 manifest/receipt 为 `06ff1734…7530` / `bc471f50…2600`，远端与本地复验一致。
- 冻结 b10333 两侧 structural smoke 通过后永久删除 Pod；随后串行完成 130×2，本地 260 个终态均为真实
  decision。与 frozen Sol 侧合并为 390 行，输出 / pair receipt / private evidence 为
  `0e8fbbc7…00aa` / `1d57def1…129c` / `4dd7966c…1727`，Plan 036 正式 CLI 导入为
  `ready_for_blind_packaging`。未运行 Opus/裁判、解盲、真实 holdout 或质量重训。

## 现场窄修

- tokenizer callable 在真实 Transformers 返回单 batch Mapping 时，训练入口先解包再做 token-id 严格校验；对应
  回归覆盖真实失败形状。
- conversion 控制器改为 detached 状态文件并禁止 Python bytecode 污染固定工具包；adapter route 现在每 2 秒抽样
  产物增长，超过 source adapter 总字节数 8 倍加 64 MB 就终止并保留日志，避免再次写出全模型大小的伪 LoRA。
  paired merge 逐字复制 frozen tokenizer，避免 Transformers 重序列化为 b10333 不兼容类名。
- `python -m rondo_eval.local_approval.cross_eval verify-import` 会因 `__main__` 与包名模块的 Python 类身份不同，
  把已全量重验的 formal capability 误判为裸 receipt。修复只在七项 source/实际 deployment 重验完成后重包装当前
  模块 capability，不放宽裸 receipt 门禁；真实 390 行 CLI 已复验通过。
- SCP 回收保留了 Pod 端过宽的 `0666/0777` 模式；本地 stage1/stage2 私有目录统一收紧为目录 `0700`、文件
  `0600`（任务内 quantizer `0700`）。权限只改 inode mode、不改字节，随后重新通过 train bundle、29 项 formal、
  14 项 deployment 和 390 行 evidence 的全部内容验真。

## 验证与本地工件

- focused unittest：`89/89` 通过；三个 RunPod shell 脚本 `bash -n`、Python `py_compile`、JSON 解析和
  `git diff --check` 通过。
- no-model cohort preflight：130 条、65 / 65、26 source groups + 26 split groups、0 模型调用、0 fake 输出；
  其 `waiting_for_l6_outputs` 只表示该 cohort-only preflight 不消费正式输出，390 行 ready 状态由正式导入证明。
- 主工作区 ignored：stage1 数据/合同 `19,592,761` bytes；formal recovery `734,413,364` bytes；deployment
  `10,396,963,660` bytes；pair 目录逻辑大小 `10,595,307,090` bytes（GGUF/adapter 采用同文件系统 hardlink，
  不是同等物理增量）；controller known-hosts `142` bytes。
- 037 worktree ignored conversion 包 `60,306,450` bytes；tar / manifest / contract SHA-256 为
  `a9112ae8…ddf5` / `fcf169c6…102c` / `1b643573…8fd5`。
