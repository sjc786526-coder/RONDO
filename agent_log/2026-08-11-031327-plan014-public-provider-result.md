# Plan 014 public provider result 投影

## 修改

- `ProviderProjection` 新增专门的 tracked-result public projection，只输出 provider alias/API、profile SHA、
  endpoint SHA、main/Guardian model、effort、价卡和 retry 合同；不输出 raw endpoint、display name、key env、
  整份 local config SHA 或 config source。
- Terminal-Bench success 与 claimed failure 共用该投影。失败记录不再缺失 profile/endpoint hash，后续 pair
  漂移诊断可在不读取本机 provider 字段的前提下比较两侧。

## 验收

- contracts/results 50/50，config hardening/pair/Terminal-Bench 35/35，共 85/85 通过；`git diff --check`
  通过。
- 回归显式断言成功/失败 public JSON 均不含 raw endpoint、display name、key env 和 local config SHA。
- 没有 Cargo、Docker、真实 API、paid pair 或 M1。

## 边界

- 旧 v8 tracked result/ledger 不修改。新 pair lock 与 sequence profile binding 仍待 Plan 014 后续离线批次。
