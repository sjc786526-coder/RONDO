# Plan 008 第五次独立审查补充整改

时间：2026-08-10（Asia/Shanghai）

基线提交：`fe517bcf9bace5325d205803ff00e0c036008e8d`

审查输入：`agent_log/2026-08-10-181713-plan008-fifth-independent-review.md`

## 1. 范围与边界

本批只处理第五次审查指出的 B2 v5 Docker 重验前合同缺口：UID 1000 的 Git 可用性、no-API marker
的真实 Git 依赖、cleanup 证明、失败上下文、耐久 runtime 字段、恢复退出分类和 agent-user 安全诊断。
同步当前 Plan/WBS/数据布局/开发环境，不推进 B3/M1 或 L2 model-backed。

本批没有运行 Docker、Cargo、真实 API 或模型，没有读取 `.env.local`，没有创建或修改 v5 pair ledger，
也没有改写已退休的 v4 ledger、trial、watchdog 或结果证据。

## 2. 审查结论核实

第五次审查的主要事实成立：

1. 只把 root-owned fix-git 仓库改成可写不能绕过 Git dubious ownership；原 no-API code-mode 命令只执行
   `printf`，因此存在 Git 不可用却得到 completed 的 false-green 路径。
2. 旧失败摘要只依据最后一个空 sample 判断清理完成，没有要求 supervisor 明确给出 cleanup phase；cleanup
   命令或复采失败时可能把无法确认的状态写成 `verified_empty`。
3. late failure 的 fake/tool/Harbor/artifact 事实会丢失并被 0/null 固定值替代；runtime 摘要也缺少 user、
   network/rootfs 和 completed 场景的精确 limits。
4. durable failed summary 恢复统一返回 70，不能保持原 65/70 分类；关键 agent-user 命令仍可能经过 Harbor
   的 raw error renderer。

审查提到的 uv cache 路径问题也成立：相对 `UV_CACHE_DIR` 会在 `uv --directory eval` 下落到
`eval/eval-data/uv-cache`。本批把统一 recipe 改为仓库根绝对投影；旧 ignored cache 未删除。

## 3. 实现

### 3.1 scoped Git 身份和真实 no-API probe

- adapter 的 agent 环境增加私有 `GIT_CONFIG_GLOBAL=/tmp/rondo-eval-codex-home/gitconfig`，文件由
  1000:1000 自建并设为 `0600`。
- 只为固定 `/app/personal-site` 写入唯一 `safe.directory`，随后以 Harbor 冻结的 agent user 复核 UID/GID、
  配置唯一值、`rev-parse` 和只读 `git status`。不使用 `safe.directory=*`，不恢复 `chown`、capability 或
  privileged。
- fake 的 code-mode 命令冻结为：先对精确 `/app/personal-site` 运行只读 `git status`，成功后才输出固定
  `rondo_code_mode_smoke` marker。marker 因此不能绕过 Git probe。

### 3.2 cleanup 和耐久 runtime 证据

- supervisor 对正常 host 返回后的自然清空或 teardown-grace 清空追加明确 `cleanup_verified` phase。
- safe summary 只有最后 sample 为 `cleanup_verified` 且 container/network/volume 精确计数均为 0 时才写
  `verified_empty`；`cleanup_unverified` 保留实际计数，旧空 sample 或无 phase 一律写
  `unverified + cleanup_not_verified`，未知计数为 `null`。
- runtime 摘要新增并严格校验 container `user`、`read_only_rootfs`、`network_mode`；completed 还必须精确为
  `1000:1000`、2 GiB memory、3 GiB memory+swap、256 pids、private cgroup、`cap_drop=ALL`、NNP 和
  writable rootfs。mount/network 继续只保存去宿主路径后的 digest。

### 3.3 失败事实、退出码与安全诊断

- `run_docker_no_api_smoke()` 使用 typed failure context 保存实际可得的 parsed outcome/task/reward、fake
  request/hit、tool round-trip、agent JSON event、Harbor return code、Docker samples 以及 trial
  result/exception SHA。真正未观察字段保持 `null`，不补造 0。
- summary schema v2 新增固定 `exit_code`：completed 必须为 0；infra failure 为 70；其他 evidence/agent/
  contract failure 为 65。ledger 每次回读重验该分类，恢复入口返回原值。
- agent-user 的 Git、secret owner/auth、runtime access、Codex exec 与 cleanup 都通过本项目的闭集
  `_checked_exec_as_agent`，只暴露 stage、command-id 和受限 stderr 分类；不传播 raw command、stdout/
  stderr、异常 cause 或 secret。cleanup 失败不覆盖 primary failure。

### 3.4 文档与轻量入口

- 更新 Plan 008、`doc/WBS.md`、`doc/WBS/eval-benchmark.md`、`doc/eval-data-layout.md` 和
  `doc/development-environment.md`，明确第五轮合同只有 pure/fake 验证，v5 尚未运行 Docker，B2 未验收。
- 订正第四轮日志中的非实现枚举 `observed_complete` 为实际 `observed`。
- 根 `justfile` 使用 `$PWD/eval-data/uv-cache`，避免 `uv --directory eval` 把新 cache 放入 `eval/` 子树。

## 4. 回归与门禁

- Terminal-Bench adapter/pair/docker-smoke/supervisor：87/87 通过。
- Terminal-Bench adapter/pair/docker-smoke/supervisor/results/runtime-bridge 组合：142/142 通过。
- `just eval-test`：286/286 通过，无 failure/error/skip；只含 pure/fake/loopback 与进程死亡注入，不代表
  Docker、API 或模型验收。
- `just eval-lock`：85 packages，lock 未更新。
- `python -m py_compile`（本批生产与测试文件）：通过。
- `git diff --check`：通过。
- common-root `eval-data/pairs/p1-fix-git-pair-v5-no-api.json`：不存在。

## 5. 未验边界

- v5 RONDO→Codex 双侧真实 Docker 尚未运行，不能宣告 B2 或 Plan 008 完成。
- compose upload 后的实际 owner、UID 1000 scoped Git probe、secret 只读 mount、workdir chmod、日志目录、
  supervisor cleanup phase 和耐久 runtime 投影仍需下一次严格串行 v5 Docker 验收。
- paid B3/M1 保持 hard-disabled；生产 declared-role 与 pre-journal publishing 终态仍是后续解锁条件。
- L2 仍只有 CPU x64 frontend/runtime closure；launcher/server 生命周期、实际加载字节、GPU/model-backed
  路径和真实推理均未验收。

因此本提交只交付第五次审查的第一阶段补充整改，不声称“闭环”、无缺陷或 B2 已通过。
