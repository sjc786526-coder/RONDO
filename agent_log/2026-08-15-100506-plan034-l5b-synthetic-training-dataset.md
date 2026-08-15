# Plan 034：L5b 合成训练数据与资产冻结

日期：2026-08-15 ｜ 分支/worktree：`034-l5b-synthetic-training-dataset`
方案：`plan/034-l5b-synthetic-training-dataset-execplan.md`

## 实质性改动

- 新增 `synthetic_training.py` 及 focused 测试，复用现有 Plan 032 严格 reader 与 static-v3 / decision-v1
  合同，提供 seed-only 受控投影、候选校验、800 唯一候选上限、canonical payload 精确去重、holdout 内存近重复
  排除、源/近重复连通组稳定 split、确定性写出和真实 release 复算。实现只用标准库，不调用模型或外部服务。
- 当前人在场开发用 Codex `gpt-5.6-sol` 直接 author 600 个唯一 synthetic 候选。最终六类为明确安全 180、
  明确危险 100、边界模糊 120、证据不足 70、伪装成安全的危险动作 65、工具结果与请求不一致 65；
  allow 240、deny 360。
- 冻结 prompt/schema、数据卡、manifest 与 `train.jsonl` 470 条 / `validation.jsonl` 130 条到
  `training/local-approval-synthetic-v1/`。两份正文共 1,670,240 bytes；train、validation 与 manifest
  SHA-256 分别为 `1e66c06e…c110a`、`cbab8084…8dd2`、`dbf5fffe…7190`。
- seed 投影、Sol-authored authoring、候选、receipt 与逐条过滤明细保留在主工作区 ignored 私有批次
  `eval-data/synthetic-training/20260815-l5b-synthetic-training-v1/`；私有子目录 0700、普通文件 0600。

## 生成与过滤事实

- Plan 032 冻结源重新严格校验为 40 条、seed 24 / holdout 16、`ready_for_l3=true`，labels SHA-256 与
  tracked lock 一致。只有 seed 受控投影进入 Sol 上下文；holdout 正文、身份、逐条标签和匹配均未进入生成上下文。
- 600 个 raw 候选即 600 个唯一候选；精确重复 0。holdout 只由 finalizer 在内存中比较，近重复命中 0，
  聚合最大分数 0.202128。120 个源/近重复连通组未跨 split。
- authoring 脚本在任何候选文件落盘前出现两次纯格式错误：synthetic command string 未闭合、shell brace 与
  `.format` 冲突；均窄修后重新做内存校验。没有候选重试、按 outcome 重问或正式批次重生成。

## 验收结果与边界

- focused 合成 fixture 与直接受影响的既有合同/教师/回放测试 **90/90 通过**；`py_compile`、
  `UV_CACHE_DIR=.uv-cache uv lock --directory eval --check`（85 packages）、`git diff --check` 均通过。
- 真实 `verify` 从私有候选、冻结教师批次和 holdout 内存过滤重新生成全部 tracked bytes；600 条、分布、split、
  文件权限与三个发布 SHA 均一致。训练 JSONL 对冻结 seed 标记、真实身份字段、provider 私有字段、项目绝对路径
  和常见密钥模式扫描零命中；tracked/private 任务树无符号链接。
- 未运行训练或 training dry-run、本地模型、Docker、Cargo、API、Hub、云资源、CI、PR 或全量 eval；未修改
  `mydev/`、`multidev/`、Plan 032/033、static v3、L4 指标或历史结果，也未合并或推送。
