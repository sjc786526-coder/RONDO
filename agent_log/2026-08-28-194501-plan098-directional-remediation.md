# Plan 098 验收后方向性整改实施记录

日期：2026-08-28
状态：`POST_ACCEPTANCE_DIRECTIONAL_REMEDIATION_IMPLEMENTED / FINAL_REVIEW_PENDING`

## 范围与结果

- 保留 `rondo-publication-critic-task@v2`、五头、non-compensating AND、现有 consumer 与 `publication-critic-v9` 主体；工作包三继续锁定。
- 新增下游 `rondo-publication-critic-decision@v1`，显式冻结逐头 margin、保守 continuity N/A、validation-only decision config 与逐维 confusion/failure recall。decision config 绑定 implementation commit `9d281cf56d1b66140b24a765cfced12db78af9c1` 和 bundle `ebddb382d8fd166b69763665bf4efcdae20fd187d390954c322f80fefbadb824`；原 v2 accepted identity 不变。
- 定向 finalizer/runtime 绑定精确字节 identity；decoder、metrics、runtime、source/review、固定路径或行数漂移均 fail-closed，没有引入通用审计、签名或可信平台。
- 独立代码复核发现的 runtime 未绑定、decision config 未绑定 decoder、qualification metadata 路径/行数不精确三项问题均已闭合并补 focused regression。

## 数据与独立复核

- 原三个模块负责人只整改 v9 train/validation，交付 hard 19、continuity 11、soft 12，共 42 个 replacements；原盲审员分别以 0 finding 接受。v9 test 正文未读取、未改写。
- development-only `publication-critic-v10` 冻结 162 train / 27 validation candidates，不含 test 目录或 loader。scope 长度 AUC 为 train `0.7088383838383838`、validation `0.5277777777777778`；commentary cue 0、exact duplicate 0、cross-group near duplicate 0。
- 全新 test-only 负责人和独立盲审员以 0 finding 接受 sealed `publication-critic-qualification-v1`：50 groups / 200 candidates / 100 pairs，template/scenario/family 均为 50 个唯一组，每维 10 个 boundary targets，逐维 failure 支持为 30/20/25/55/25，跨组及与开发集 near duplicate 均为 0。总执行者只做 schema、coverage、identity 的机械冻结，未读取资格正文。
- 正式 v10 与 qualification release 从空目录一次生成，并在临时目录逐字节复现；临时复现目录已清除。

## 身份与验证

- directional design SHA-256：`be259651812726163665e0894f3b5d6e7e1924e375754e6faf7fa1ae7bb1f68f`。
- directional config SHA-256：`e61c42d882736baed20a1774f54ca4d97f0b4296a4166462ee2e436227aabc10`。
- v10 manifest SHA-256：`ea0cfd1e9a46e407009870a3686fffcc605259985083cbdc8829d086005e49e4`。
- qualification manifest SHA-256：`e2c28848a5258a656f6cb9f2fad8c25954c0c6d379ef2dca8051b927b7ca4dec`。
- directional/qualification/successor 33/33；旧 contract/training-data/identity/v7 43/43；合计 76/76 定向 Python 回归通过。相关 Python 文件 Ruff format 与 `F,E9` 检查通过。
- `publication-critic-v9` tree 在复审基线和当前均为 `65be7257a33717331240c0c4c5061da580ab9871`；v8 均为 `63981483baa00c671987d4b82887909fcc320690`。未运行 Rust、Cargo、Docker、真实模型、GPU、网络数据或付费操作。

## Ignored 暂存

- 任务 namespace `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098/` 当前共 `1.8M`，包含本轮及此前 Plan 098 commissioning 资产。
- 本轮新增 `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098/directional-remediation/`（`120K`）：三个 patch 和三个原盲审记录。
- 本轮新增 `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098/qualification-set/`（`248K`）：sealed source 与独立 blind review。
- 上述本轮路径应保留至最终复验完成，用于身份核对与可复现；通过后可按用户需要清理。未覆盖或清理其他任务 namespace。

## 待办

- 提交全部 tracked 交付并保持工作树 clean 后，通过指定 Codex queue 申请独立最终复验；复验通过前不恢复 Plan 098 完成态、不启动工作包三。
