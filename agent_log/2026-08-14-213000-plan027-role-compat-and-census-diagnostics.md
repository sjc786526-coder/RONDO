# 2026-08-14 Plan 027 / WP3b-A2c：provider-neutral 角色顺序兼容与 census 最小失败定位

分支 `027-wp3b-a2c-role-compat-census-diagnostics`，起点 `78aefb1`。无模型、无网络、无 Cargo/Docker。

## 实质修改

1. **`eval/rondo_eval/evidence.py`**：static input payload v2 → **v3**（决策输出 schema 仍是
   `rondo_static_approval_v1`，未随动）。`_neutral_items()` 新增分支 `_normalize_evidence_role()`：
   带 role 的证据消息在原位把 `developer` 改写为 `user`，`user`/`assistant` 保持不变。
   只改 role —— `phase`、`id`、passthrough metadata 等仍走 Plan 025 定下的 `_strip_transport_metadata`
   处理，不顺带扩大到消息级 metadata。不带 role 的 item（function_call、其 output、tool_search_output）
   完全不动，因此没有任何跨 tool call/output 的重排。
   fail-closed：未知/缺失 role、非消息 item 携带 role、空或非数组 content、与角色不匹配的文本 subtype
   （user 必须 `input_text`、assistant 必须 `output_text`）、含多余键的 content part 一律 `EvidenceError`。
   终端 validator 增加 `_reject_unnormalized_roles()`，顶层证据 item 的 role 只能是 `user`/`assistant`。
2. **`eval/rondo_eval/local_approval/client.py`**：只同步 v3 文案与错误信息，未加任何 consumer 侧转换。
3. **`eval/rondo_eval/local_approval/token_census.py`**：通用计数失败补三项最小 facts ——
   有界 `stage`（`anchor_count` / `archive_count`）、当前 `e_final_sha256`、`counted_before_failure`
   （失败前已取得 exact count 的唯一归档数，锚点计入）。锚点与集合遍历两处都保留 `except CensusError`
   立即中止，未把通用 500/transport 降级成样本拒绝；`RequestRejected` 的 per-record `refusal` 不加字段，
   正式 baseline 里不会多出诊断噪声。
4. **测试**：`test_contracts_and_evidence.py` 新增角色规范化保序保文本用例、17 种畸形/未知消息形状
   fail-closed、v1/v2 双版本 sink 拒绝、sink 拒绝手工回填 role；`test_local_approval.py` 新增
   `FrozenTemplateRoleOrderTests`（3 项）与两项 census 定位回归，并把一条 census 归档 fixture 换成含
   `assistant → developer` 的形状。

## 关键决策

- **为什么是 `developer` → `user`**：只读聚合扫描确认 47 条归档只有 `user`/`developer`/`assistant`
  三种消息角色、6 种 role 序列，content 全部是单一 `input_text`/`output_text`。冻结 Ministral 模板里
  `user` 是唯一在 system/user/assistant/tool 之后都被接受的角色，所以原地换 role 是保留文本、顺序与
  消息边界的最窄办法，不必新增中立结构标记，也不必建对话重写器。
- **为什么无条件改写**：只在「跟在 assistant/tool 之后」时改写会让同样的证据因位置得到不同角色，
  并把某个模板的顺序规则暗中写进本应 provider-neutral 的 payload。
- **模板角色顺序门只放在测试里**，而且规则是用正则从冻结模板资产里解析出来的，不是手抄的常量，
  避免门禁与真实模板漂移；生产 consumer 不含任何 provider 特判。

## 验收结果

- focused tests：`tests.test_contracts_and_evidence` + `tests.test_local_approval` 共 **116/116** 通过。
- `tests.test_terminal_bench` 中唯一消费 `policy_identity` 的用例 **1/1** 通过（该消费者只用
  `sha256` / `request_shape`，结果工件不记录 schema 版本，因此升 v3 没有下游工件影响）。
- 依赖锁：`uv lock --directory eval --check` **85 packages** 通过。未按原样跑 `just eval-lock`
  —— 该配方硬编码 `$PWD/eval-data/uv-cache`，本 worktree 无 `eval-data/`，改用指向主仓 cache 的等价命令。
- **47 条只读聚合检查**（从 Git common root 只读，内存内完成，未输出正文、请求体或渲染 prompt）：

  ```
  47/47 构造 static payload v3        47/47 构造 Local 请求
  47/47 三 consumer canonical bytes 逐字节一致
  残留 developer/system role = 0      残留 reasoning/encrypted = 0
  冻结模板角色顺序门：v3 47/47 通过；规范化前 24/47 通过
    23 条失败原因均为 Unexpected role 'system' after role 'assistant'
  ```

  规范化前的 24/23 与 Plan 026 的离线结论完全一致，说明本次改动确实作用在同一个形状上。

## 未运行 / 不主张

- 未运行：真实模型、GPU、count endpoint、census 重跑、任何 generation、Cargo、Docker、云 API、全量 eval。
- 本次只证明**构造层与模板角色顺序兼容**，不证明 47 条在真实 b10333 上能完成计数。
- 新增的 stage/digest/counted 字段只用于定位**下一次**失败，不能回溯解释 Plan 026 那次通用 500，
  也不追认 Plan 024 两条旧 500 的现场原因。
- WP3b-A2 仍 blocked/incomplete；未发布 token baseline，未选上下文档位，capability 仍为
  `linux_cuda_built_model_unvalidated`，qualification 状态未变。
