# Plan 073 整改复验审查

日期：2026-08-25

## 结论

- **验收不通过。** `02759ae` 拒绝了上次演示的浅层伪造，但 unseen 物理隔离仍未实现，selection lock 仍能由一组自洽但未绑定真实 validation 输入的证据打开；两个原 blocker 都没有完整关闭。
- **任务目标完成。** 正式三候选结果仍可精确复算为 `NO-GO`，且该结论不依赖 Judge。现有质量事实继续有效，不选择 base 兜底，Publication Critic 保持 default-off，M3-D 保持锁定。

## 阻塞性 finding

### 1. 新 reader 仍然读取并物化 unseen

`selection/dataset_source.py` 改成逐行流式过滤，但数据源仍是同时包含 train、validation、unseen 的混合文件：

- `dataset_source.py:97-101` 调用 `verify_freeze_manifest()`；后者在 `training_data/freeze.py:88-98` 遍历并哈希读取 manifest 中的全部数据文件。
- supervision 在 `dataset_source.py:108-112` 先由 `_stream_jsonl()` 完整 `json.loads` 并校验，之后才判断 split。
- packets/census/pairs 分别在 `dataset_source.py:121-149` 接收完整 row 后才检查 membership。
- `_stream_jsonl()` 本身在 `dataset_source.py:193-204` 先读取整行并物化 JSON。因此实现只是“不累计保留”unseen，每条 unseen body 仍进入了 validation 进程。

新增测试也只检查返回对象不含 unseen ID，并 mock 旧 `DatasetConsumer` 未被调用；它没有证明混合数据文件未打开或 unseen row 未 decode。测试 `setUp` 反而会整体读取 supervision。执行日志和 Plan 所称“从未把 unseen 放入进程”“blocker 已关闭”不成立。

此外，新 reader 只对选中行做 per-row 校验和 census 非负检查，没有完整复用旧 consumer 的跨行 packet/supervision 投影、pair direction/context/omission 与 omission 可应用性校验。“完整性不降级”的表述也没有成立。

最小整改不是继续优化混合 JSONL 的过滤方式，而是让 validation 消费**物理上不含 unseen body**的冻结资产。已有 Plan 066 train+validation-only bundle 可作为优先起点，也可以采用等强的 split 专用冻结投影；在该输入上复用现有跨行与 omission 校验。测试应使用访问 spy/sentinel 证明 validation 成功路径根本没有打开 unseen-bearing 文件或行。

### 2. selection lock 仍由 result 自证，且 report 可接受未校验 confirmation

浅层翻转 terminal/selected/admission 已能被拒绝，这是有效修复；但 `validate_validation_result()` 仍只从同一份 result 自带 rows 重算部分指标：

- `decision.py:352-440` 的 rows 不绑定实际 validation release，且丢弃真实 slices/facets；只重算 threshold search、confusion 和 AUC，boundary、完整 overall、Judge view 等仍来自 result 自报。
- `decision.py:443-509` 对 release 只有 SHA 格式检查，没有输入真实 release/raw scores/Judge package/aggregate，也没有绑定固定 run archive。
- `build_selection_lock()` 因此仍把这份可整体替换的 result 当作授权依据。

审查以真实正式 freeze 配上一份 24 行合成 release，仅把其 `dataset_manifest_sha256` 声明成冻结 v8 的 hash；现有 `evaluate_validation()` 得到 `SELECTED c3`，`validate_validation_result()` 接受，`build_selection_lock()` 返回 `unseen_release_authorized=true`。这不需要签名攻击，只说明 CLI/函数没有把 lock 绑定到本轮真实 release 与 score evidence。

另有同类终态问题：`runner.py:562-608` 对 `--unseen-confirmation` 只做 JSON 读取，未验证 schema、freeze、selection lock、locked combination 或 terminal 推导，却可以据其把 tracked report 写成 `GO`。Judge package 绑定在显式提供时有效，但 `--judge-package` 仍可省略，aggregate 仍可绕过绑定。

最小整改是构锁时要求本轮 validation release、三份 raw score、Judge package/aggregate，复用现有 `evaluate_validation()` 重算后与待锁 result canonical equality；aggregate/package 必须成对出现。report 的 confirmation 至少严格绑定 freeze + selection lock + locked combination，或直接从同一组 confirmation 输入重算。无需签名、数据库、registry 或其它可信平台。

## 非阻塞项

- package id 禁止 split 词、Opus 身份检查、incomplete scoring fail-closed 均有效；`test/train` 的简单子串拦截可能误拒 `contest/latest` 一类合法 ID，可顺手改为分隔 token 判断，不单独阻塞。
- `score` 新增 snapshot 文件摘要是有用观测，但该摘要既未进入 freeze，也未由 `_validate_scores()` 校验，所以不能表述为通用 snapshot binding 已完成。本轮三 snapshot/token count 的人工核对足以支持既有 `NO-GO`，无需因此重跑模型或改旧 freeze。
- tracked 结果说明前段仍称 Judge“不含 split 名”，后段又承认正式 package id 含 `validation`，应统一为“item 内容盲化，但控制 ID 泄漏了 validation”。

## 复验证据

- Plan 073 focused tests：`51/51` 通过；全部 `test_publication_critic*.py`：`308` 项通过、`1` 项 skip。绿灯没有覆盖上述混合文件访问和自证输入问题。
- 从归档 freeze、validation release、三份 raw scores、Judge package/aggregate 重建 result，与归档完全相等；严格 validator 接受，canonical SHA-256 仍为 `2b36eb4b408ff9a1a6a9830429fb806e9e2df1e54b6374755b98febb3cc98915`，terminal 仍为 `NO_GO`。
- tracked report 重建后逐字节相等，SHA-256 仍为 `f97fcdcc78c9932dd96eb17c419ef29bf574649d7b67c1c497e861daa2eee8e4`。
- 本次未加载模型，未运行 Cargo、Docker、Opus 或正式 unseen campaign。需要特别说明：现有 focused/full tests 会调用缺陷 reader，因此测试进程自身再次读取并解析了混合 v8 中的 unseen rows；没有生成 unseen release、score、Judge 或归档。
- review 前 Plan 073、main、Plan 069 均 clean；Plan 074 的既有未提交修改保持原样，未读取或改动其内容。

## 代用户作出的决定

1. 保留 `NO-GO` 质量结论和现有 raw 证据；不选 base 兜底，不生成 selection lock，不释放 unseen，不解锁 M3-D。
2. `02759ae` 不通过复验，分支在两个 blocker 真正关闭前不得合并。下一轮只做上述窄整改与 pure/focused 复验，不建设复杂审计或可信体系。
3. 不重跑三候选模型或 Opus。reader 修复应重建出相同 validation release；lock/report 修复使用已有 archive 输入复算即可。
4. validation 必须改用物理上不含 unseen 的冻结输入；“流式扫描混合文件后丢弃”不再接受为封存实现。职责契合时优先复用现有 Plan 066 train+validation-only bundle，执行者仍可采用更干净的等强方案。
5. selection lock 必须绑定真实 release/raw/Judge 输入而不是由 result 自证；这里只要求复用已有 evaluator 做重算和 canonical equality，不要求防恶意本机篡改的密码学设施。

本审查只提交 Plan 073 worktree；未合并、未推送、未归档分支。
