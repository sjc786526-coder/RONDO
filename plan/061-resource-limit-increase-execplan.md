# Plan 061：构建资源固定门线调整

> 本计划是 Plan 061 的稳定任务合同。除“当前状态”和“关键决策记录”外，实施期间默认不得修改。
> 如果目标、范围、门线或验收标准发生实质变化，应暂停执行并请求用户确认。
> 本计划只描述本次固定数值调整；跨任务路线仍以 `doc/WBS.md` 与 `doc/WBS/*.md` 为唯一来源。

## 1. 目标

### 1.1 最终目标

保持现有构建锁、systemd scope、资源看门狗和固定阈值设计不变，只调整默认资源门线：

| 门线 | 当前值 | 新值 | 单位语义 |
|---|---:|---:|---|
| `MemoryHigh` | `19G` | `21G` | systemd `G`，即二进制 GiB |
| `MemoryMax` | `21G` | `22G` | systemd `G`，即二进制 GiB |
| `MemorySwapMax` | `5G` | `5G` | 不变 |
| 项目告警线 | `180000000000` | `240000000000` | 十进制字节 |
| 项目主动停止线 | `195000000000` | `255000000000` | 十进制字节 |
| 项目绝对线 | `200000000000` | `260000000000` | 十进制字节 |

本次不做 frozen binary 去重，不按宿主内存比例动态计算，不改变并发度，也不扩建新的资源策略、审计或证据体系。

### 1.2 完成/验收标准

- 默认 wrapper 实际创建的 cgroup 精确为：
  - `memory.high=22548578304` B（21 GiB）；
  - `memory.max=23622320128` B（22 GiB）；
  - `memory.swap.max=5368709120` B（5 GiB）。
- 项目默认告警/主动停止/绝对线精确为
  `240000000000/255000000000/260000000000 B`，且继续满足 `warn < stop < max`。
- `runtime_bridge.py` 对默认 cgroup 的生产校验与 wrapper 新默认一致；限制漂移仍然 fail-closed。
- override 变量名、解析和直接覆盖机制不变；未覆盖的维度继承新默认，因此部分旧组合不再有效。
- Windows `C:` 50GB 构建停止线、Docker 门线、不可回收内存停止线、宿主内存/swap/PSI 停止条件、采样周期和残留清理语义全部不变。
- Cargo jobs、rustc 槽和 Nextest 并发保持现值；不新增或迁移 target。
- 当前维护文档只更新“当前默认值”和受其影响的示例；历史 plan、日志、冻结 manifest/result、旧 summary
  和既有完成记录原样保留，完成时只新增本任务的一条精炼成果。
- 通过 Shell 语法检查、聚焦 Python 单元测试和一个约两秒的真实 wrapper scope；不运行 Cargo、Docker、模型或 API。

## 2. 当前证据与判断

### 2.1 2026-08-23 只读快照

| 项目 | 当前值（约数） | 与本任务的关系 |
|---|---:|---|
| RONDO 项目目录 | 119 GB | 距新 240 GB 告警线约 121 GB |
| Windows `C:` 可用 | 196 GB | 50 GB 独立构建底线不需调整 |
| WSL `MemTotal` | 27.4 GiB | 22 GiB scope 硬上限仍留约 5.4 GiB 名义空间 |
| WSL `MemAvailable` | 19.3 GiB | 只代表计划形成时快照，不写入策略 |
| WSL swap 总量/可用 | 10.0/9.5 GiB | scope swap 上限继续为 5 GiB |

`MemoryHigh` 是软回收/节流起点，不是静态预留；从 19G 提到 21G 允许构建使用更多可回收页。
`MemoryMax` 从 21G 提到 22G 后仍由既有宿主 `MemAvailable`、swap、PSI 和不可回收内存停止线兜底。
本次有意把 high 到 max 的缓冲从 2G 缩为 1G，不把这次调整解释为可取消宿主级保护。

### 2.2 数字冲突的处理

用户本次明确要求“high 增加 2GB、max 增加 1GB、存储三线增加 60GB”。以仓库当前
`19G/21G/5G` 和 `180/195/200GB` 为基线，结果只能是：

```text
21G / 22G / 5G
240GB / 255GB / 260GB
```

先前建议中的 `21G/23G/5G` 与 `230/245/250GB` 分别对应 max 增加 2G、存储增加 50GB，
与本次增量不一致，因此不采用。

### 2.3 需要同步编辑的默认值持有者

- `scripts/with-build-lock.sh`：默认值的唯一执行入口，同时把实际值写入 `summary.env`。
- `eval/rondo_eval/runtime_bridge.py`：对 live cgroup 的 `memory.high/max/swap.max` 做生产级精确校验，必须同步。
- `eval/tests/test_runtime_bridge.py`：构造 cgroup 计数器树并验证限制漂移，必须同步测试期望。
- `AGENTS.md`、`CLAUDE.md`、`doc/development-environment.md`：描述当前生效门线，必须同步。

其它运行路径通过 `runtime_bridge.py` 自动继承新默认，无需逐文件修改。

`eval/rondo_eval/publication_critic/evidence.py` 的模块职责明确限定为 Plan 054 v4 冻结证据投影，其
`19G/21G/5G` 与旧项目线属于历史测量合同。它仍是 runner 的活动调用代码，但本任务不更新它及对应
测试夹具、冻结 manifest、结果和 summary。由此形成明确的能力边界：Plan 061 生效后，Plan 054 v4
可以继续读取和验证既有历史工件，但其 `calibrate/freeze/measure/finalize` 不得再用新 wrapper summary
重新执行，因为新 summary 的 `21G/22G/5G` 会被旧 evidence contract 拒绝。未来新 campaign 另行升级
证据版本并冻结新合同；Plan 061 不增加双版本兼容层。

## 3. 范围

### 3.1 允许修改

- `scripts/with-build-lock.sh`
- `eval/rondo_eval/runtime_bridge.py`
- `eval/tests/test_runtime_bridge.py`
- `AGENTS.md`
- `CLAUDE.md`
- `doc/development-environment.md`
- 本计划；实施完成时可新增一份精炼 `agent_log/` 记录，并向 `doc/WBS-COMPLETED.md` 追加一条精炼成果
- ignored 验收产物：061 内预先不存在的 `.codex/build-watchdog/plan061-limit-smoke/`

### 3.2 不允许修改

- `eval-data/bin/`、其它 `eval-data/` 资产和任何 frozen binary 路径、manifest、lock
- `eval/rondo_eval/publication_critic/evidence.py`、runner、对应测试、冻结 manifest 和 tracked result
- 历史 plan、既有 `agent_log`、`doc/audit-snapshots/`、`doc/WBS-COMPLETED.md` 既有条目和既有 `summary.env`
- `doc/WBS.md` 与 `doc/WBS/*.md`；本任务不改变当前路线和后续工作包
- `mydev/`、`multidev/`、`.cargo/`、根 `justfile`、Cargo target 和依赖
- `.wslconfig`、宿主机配置、系统服务、Docker 对象、模型和 API 状态
- 060、062 worktree 的任何文件或用户/并行任务修改

### 3.3 不允许读取

- `.env.local` 内容、密钥、provider 私有返回和与本任务无关的私有数据

## 4. 硬约束

1. 实际编辑只在 `.claude/worktrees/061-resource-capacity-dedup-plan` 中进行；主工作区和其它 worktree 保持原样。
2. 本任务只替换固定默认值及其直接消费者，不新增 policy 模块、summary schema、探针、守护进程或配置层。
3. 内存继续使用 systemd 的 `G` 语义，项目容量继续使用十进制字节，不引入比例、浮点或自动调参。
4. 只提高 high、max 与三条项目线，swap 默认值维持 5G；override 的变量名、解析和直接覆盖机制不改，
   但未覆盖维度继承新默认，实施后不保证旧的单变量组合仍有序或有效。
5. `MemoryHigh < MemoryMax` 和项目 `warn < stop < max` 必须保持；不得为通过测试放松 runtime bridge 的精确校验。
6. 19 GiB 不可回收内存停止线、4/4.75 GiB scope swap 停止线、宿主 3.5 GiB 可用内存停止线、
   1 GiB 宿主 SwapFree 紧急线和 full PSI 条件均保持现状。
7. 不把更高项目线解释为允许并行重型任务、两个常驻完整热 target 或绕过 Windows `C:` 容量门禁。
8. 历史证据中的旧值不做机械替换；所有改动都必须按文件职责逐处审查。
9. 当前仅授权修订计划。本计划本身不授权实施、真实 scope、提交、合并或推送。

## 5. 实施设计

### 5.1 固定默认值

在 `scripts/with-build-lock.sh` 只更新文件头的默认值说明与五个变化值，并保留完整默认组合如下：

```bash
memory_high="${RONDO_BUILD_MEMORY_HIGH:-21G}"
memory_max="${RONDO_BUILD_MEMORY_MAX:-22G}"
swap_max="${RONDO_BUILD_SWAP_MAX:-5G}"
project_warn_bytes="${RONDO_BUILD_PROJECT_WARN_BYTES:-240000000000}"
project_stop_bytes="${RONDO_BUILD_PROJECT_STOP_BYTES:-255000000000}"
project_max_bytes="${RONDO_BUILD_PROJECT_MAX_BYTES:-260000000000}"
```

不重构 wrapper，不改 `build-watchdog-lib.sh`，也不增加读取 `MemTotal` 的新逻辑。文件头原有
“默认低于一次性 22GiB probe”的说明会因新 `MemoryMax=22G` 失真，必须改写成只描述当前固定默认值
和既有宿主级兜底，不机械保留该比较。

### 5.2 live cgroup 消费者

在 `runtime_bridge.py` 只把 high/max 两个默认精确字节常量更新为 `21/22 GiB`；swap 常量继续为 5 GiB。
`_read_required_cgroup_counters()`
继续逐次读取全部必要计数器，并在任一限制不等于项目默认值时拒绝 mint/保持 lease。

在 `test_runtime_bridge.py` 同步伪 cgroup 树与 drift 恢复值，继续覆盖：

- 新默认能够 mint lease；
- 用同一个参数化测试依次篡改 `memory.high`、`memory.max`、`memory.swap.max`，三者任一漂移均拒绝；
- 修复为新默认后行为恢复；
- `RONDO_BUILD_*` override 仍不能作为 production proof。

不新增测试模块，不把脚本常量再复制到一个新的共享 Python 配置层。

### 5.3 当前文档

- `AGENTS.md`、`CLAUDE.md`：只更新当前资源门线一句。
- `doc/development-environment.md`：更新当前 cgroup 表、项目容量章节标题与三线、当前保护说明；
  历史实测峰值保持不变。
- 现有“单次收紧”示例若因新 `MemoryHigh=21G` 变得不合理，改成显式成对的
  `RONDO_BUILD_MEMORY_HIGH=19G RONDO_BUILD_MEMORY_MAX=21G`；项目单变量示例改为仍满足新顺序的
  `RONDO_BUILD_PROJECT_STOP_BYTES=250000000000`。不改变 override 实现。
- 历史测量段落中原有“21G 硬上限”明确标注为“当次测量值”，不机械改写历史事实为 22G。
- 不更新 README/WBS，因为它们没有复制具体数字，而是继续指向根 `AGENTS.md`。

## 6. 实施步骤

1. 再次确认 main、061、060、062 状态；若 061 出现来源不明修改，先停止并报告。
2. 修改 wrapper 的文件头说明和五个变化值，不触碰 swap 赋值或其它控制流。
3. 修改 runtime bridge 的 high/max 两个固定字节常量及现有聚焦测试期望。
4. 更新三份当前维护文档，只替换当前事实和受影响示例。
5. 审查 diff，确认没有 binary、历史证据、产品源码、当前 WBS 路线或其它 worktree 变化；
   `doc/WBS-COMPLETED.md` 只能新增本次一条成果。
6. 按第 7 节运行轻量验收；任一失败只修复本任务直接回归，不扩大为看门狗重构。
7. 获得实施和交付授权后，记录精炼日志、向 `doc/WBS-COMPLETED.md` 追加一条成果、提交 061、
   合并本地 main、推送 `origin/main`，
   再把已合并分支重命名为 `zz-done/*`。不推送 worktree 分支。

## 7. 验证与完成门禁

### 7.1 静态检查

- `bash -n scripts/with-build-lock.sh`
- `git diff --check`
- 定向 `rg` 复核当前文件中的新值，并确认历史目录没有进入 diff。
- 检查 `git status`：061 只包含计划允许的文件；确认 061 未写入 main、060 或 062，并记录这些
  并行工作区结束时的实际状态，不要求它们与任务开始时完全相同。

### 7.2 聚焦 Python 测试

使用共享 eval venv 运行固定的 runtime bridge 测试类，不运行整个 eval 套件：

```bash
common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
"$common_root/eval/.venv/bin/python" -B -m unittest -v \
  eval.tests.test_runtime_bridge.WatchdogBridgeTests
```

再运行一个精确的 Plan 054 旧证据测试，证明历史 loader 未被间接破坏：

```bash
common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
"$common_root/eval/.venv/bin/python" -B -m unittest -v \
  eval.tests.test_publication_critic_eval.PublicationCriticEvalTests.test_strict_calibration_and_watchdog_evidence_reject_semantic_drift
```

上述两个入口必须按原命令通过；不设置失败后扩大到整个文件或全量套件的 fallback。

### 7.3 真实 wrapper scope

在确认没有 Cargo、Docker 或模型重型任务后，使用下面的固定命令。`metrics_dir` 必须预先不存在，
且只能使用 061 wrapper 直接启动共享 eval venv 的 Python；`PYTHONPATH` 显式绑定 061 的 `eval/` 源码：

```bash
set -euo pipefail
common_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
metrics_dir="$PWD/.codex/build-watchdog/plan061-limit-smoke"
test ! -e "$metrics_dir"
test -x "$common_root/eval/.venv/bin/python"
PYTHONPATH="$PWD/eval" \
RONDO_BUILD_METRICS_DIR="$metrics_dir" \
"$PWD/scripts/with-build-lock.sh" \
"$common_root/eval/.venv/bin/python" -B -c '
import time
from pathlib import Path
from rondo_eval.runtime_bridge import lease_from_watchdog

expected = {
    "memory.high": 22548578304,
    "memory.max": 23622320128,
    "memory.swap.max": 5368709120,
}
proof = lease_from_watchdog()
proof.lease.validate()
if proof.guard.is_held(proof.lease) is not True:
    raise SystemExit("watchdog guard is not held before limit read")
relative = next(
    line.split(":", 2)[2]
    for line in Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
    if line.startswith("0::")
)
cgroup = Path("/sys/fs/cgroup") / relative.lstrip("/")
observed = {
    name: int((cgroup / name).read_text(encoding="ascii").strip())
    for name in expected
}
if observed != expected:
    raise SystemExit(f"cgroup limits differ: {observed!r}")
time.sleep(2)
if proof.guard.is_held(proof.lease) is not True:
    raise SystemExit("watchdog guard is not held after wait")
print(observed)
'
```

命令成功后，在同一 061 工作目录执行固定的结果检查：

```bash
set -euo pipefail
metrics_dir="$PWD/.codex/build-watchdog/plan061-limit-smoke"
mapfile -t summaries < <(
  find "$metrics_dir" -mindepth 2 -maxdepth 2 -type f -name summary.env -print
)
test "${#summaries[@]}" -eq 1
summary="${summaries[0]}"
expected_lines=(
  'command_name=python'
  'wrapper_status=complete'
  'run_rc=0'
  'final_rc=0'
  'stop_reason=none'
  'cleanup_reason=none'
  'junit_status=not_applicable'
  'memory_high=21G'
  'memory_max=22G'
  'swap_max=5G'
  'project_stop_bytes=255000000000'
  'project_max_bytes=260000000000'
)
for expected_line in "${expected_lines[@]}"; do
  grep -Fx -- "$expected_line" "$summary" >/dev/null
done
unit="$(sed -n 's/^unit=//p' "$summary")"
[[ "$unit" =~ ^rondo-build-[0-9]+-[0-9]+-[0-9]+[.]scope$ ]]
systemctl --user show-environment >/dev/null
if systemctl --user is-active --quiet "$unit"; then
  echo "scope is still active: $unit" >&2
  exit 1
fi
if systemctl --user is-failed --quiet "$unit"; then
  echo "scope remains failed: $unit" >&2
  exit 1
fi
```

`metrics_dir` 下必须恰好只有本次生成的一份 `summary.env`。只对该 summary 记录的 unit 检查
`is-active/is-failed`；不得枚举、检查或清理其它任务的 scope。

验收要求：

- scope 内读取到 `22548578304/23622320128/5368709120 B`；
- wrapper `summary.env` 为 `command_name=python`、`wrapper_status=complete`、`run_rc=0`、`final_rc=0`、
  `stop_reason=none`、`cleanup_reason=none`、`junit_status=not_applicable`；
- summary 中为 `memory_high=21G`、`memory_max=22G`、`swap_max=5G`、
  `project_stop_bytes=255000000000`、`project_max_bytes=260000000000`；
- wrapper 源码中的 `project_warn_bytes=240000000000` 经静态复核；
- summary 记录的本轮 unit 结束后不再 active/failed；不对其它 unit 作任何断言。

这一步不执行 Cargo、Docker、模型、API，也不宣称验证它们。

### 7.4 完成条件

- 上述静态检查、聚焦单测和真实 scope 全部通过；未运行项如实记录。
- diff 只包含第 3.1 节列出的文件，且没有生成来源不明资产。
- 当前维护文档与生产默认一致，历史证据仍保留旧值和原哈希。
- 用户授权范围包含交付时，完成提交、main 合并、push 和 `zz-done/*` 分支收口；否则停在已验证的 061 worktree。

## 8. 回滚

本任务没有数据迁移。回滚只需在 061 提交范围内把 wrapper 的五个变化值、runtime bridge 两个常量、
测试期望和三份当前文档恢复为旧值，然后重跑同一组轻量门禁。不得改写历史结果或删除其它任务资产。

## 9. 当前状态

### 已完成

- 已只读核对当前 wrapper、runtime bridge、Publication Critic 冻结证据、聚焦测试和当前文档。
- 已确认当前项目约 119 GB、Windows `C:` 可用约 196 GB、WSL `MemTotal` 约 27.4 GiB。
- 已确认 060、062 均有并行任务修改；本任务均未触碰，交付前重新记录它们的实际状态。
- 已按用户最新决策撤销 frozen binary 去重、动态比例内存、summary v2、容量探针等旧方案。
- 已将 Plan 061 重写为固定门线调整合同。
- 已把 wrapper 默认调整为 `21G/22G/5G` 与十进制 `240/255/260GB`，同步 runtime bridge、
  参数化 drift 测试和三份当前文档；未改变 override 机制或其它看门狗控制流。
- `bash -n`、`git diff --check`、runtime bridge `6/6` 和 Plan 054 v4 旧证据精确测试 `1/1` 通过。
- 最终单次真实 scope `rondo-build-1000-20260823220746-3339026.scope` 通过：production lease 前后有效，
  cgroup 精确为 `22548578304/23622320128/5368709120 B`，summary 为 complete/0/none，unit 已不再 active/failed。
- 最终 ignored metrics 目录只包含一轮 summary；项目本轮采样峰值为 `139975536640 B`，低于新告警线。

### 当前工作

- 实施与任务内验收已完成，正在完成提交、main 合并、push 与分支收口。

### 本任务剩余步骤

- 完成交付检查、提交、main 合并、push 和 `zz-done/*` 分支重命名。

### 阻塞项

- 无。

### 当前验收状态

- 任务内完成条件全部通过。未运行 Cargo、Docker、模型、API 或全量测试，且不作相关通过声明。

### 交接边界

- Plan 061 完成后冻结本计划；不在本计划中安排 binary 去重或其它资源优化后续任务。

## 10. 关键决策记录

| 编号 | 决策 | 原因 | 影响范围 | 状态 |
|---|---|---|---|---|
| 001 | 放弃 frozen binary 去重 | 当前收益不值得引入对象库、迁移和恢复复杂度 | 删除旧 Plan 061 的全部存储设计 | 已采纳 |
| 002 | 使用固定 `21G/22G/5G` | 精确落实 high +2G、max +1G、swap 不变 | wrapper、runtime bridge、测试、文档 | 已采纳 |
| 003 | 项目三线固定为 `240/255/260GB` | 精确落实相对当前值统一增加 60GB | wrapper、当前文档 | 已采纳 |
| 004 | 不新增共享 policy/summary 设施 | 当前只有两个实时默认值消费者，抽象收益不足 | 保持现有架构和最小改动 | 已采纳 |
| 005 | Plan 054 v4 evidence 保留旧值并收窄为历史验证 | 它仍是活动调用代码，但新 summary 不再符合其冻结合同 | 旧工件可验证；v4 不再重新执行，新 campaign 另升版本 | 已采纳 |
| 006 | 验收限于轻量单测与约两秒真实 scope | 足以验证固定默认和 live cgroup，不需要重型构建 | 无 Cargo、Docker、模型或 API | 已采纳 |
