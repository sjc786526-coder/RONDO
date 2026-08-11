# Plan 014 冻结 Codex catalog 正式投影

## 修改

- 将 CLI 诊断中已真实验证的 `model_catalog_json` 机制提取为共享 source-bound helper：从 binary manifest
  指定的 frozen source commit 读取 git object，只选择本次 main/Guardian 条目，并仅设置主条目的
  `auto_review_model_override`。
- frozen Codex 正式 Terminal-Bench live 路径生成最小私有 catalog，绑定 source commit 与 SHA256，经 Harbor
  adapter 上传后复核 regular-file、`0400`、owner、digest 和运行时只读性，再传给冻结 CLI。RONDO 明确拒绝
  该 frozen-only 投影，继续使用自身 `[auto_review]` 配置。
- no-API 兼容路径仍可不提供 catalog；paid live 的 frozen Codex 路径必定生成并投影 catalog。

## 验收

- 实际 frozen source `be6e8eac029b183056b7e4402879f15d2c85f61b` 与 active Sol/Sol profile 的只读投影成功：
  只含 `gpt-5.6-sol`，override 为 `gpt-5.6-sol`，投影 SHA256 为
  `21f7805b7aa9d9ad84e09636b32355b912880ea973e7c3b70cf895d1b5b974e7`。
- catalog/Terminal-Bench/model diagnostic/provider probe 41/41 与 budget proxy 41/41 通过，共 82/82；
  Python compile 与 `git diff --check` 通过。
- 没有 Cargo、Docker、真实 API、paid pair 或 M1。

## 边界

- 本批闭合 catalog/source identity 正式投影；新 pair lock、profile drift 和 public/redacted failure result
  仍是 Plan 014 后续离线工作。
