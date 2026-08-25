# Plan 072 共享重型任务启动前冲突观察门

## 结论与实现

- 结论为 `STARTUP_GUARD_ADDED`。live wrapper 原先只有 canonical flock、启动前 Cargo 进程检查和运行期 watchdog，
  没有在 flock 成功后核对旧 RONDO heavy scope 的等强启动资格门。
- `build-watchdog-lib.sh` 现只读枚举当前用户 canonical scope，解析 systemd state/ControlGroup，并以 cgroup
  `populated` 作为当前活性事实；list/show/cgroup 不可可靠读取时返回 unknown。`with-build-lock.sh` 在 flock 成功后、
  watchdog-disabled 直通与正常 `systemd-run` 之前调用该 helper，冲突或 unknown 均以 `84` 拒绝 payload。
- 门禁没有等待、重试、kill、清理、接管或调度旧 scope，也没有增加 registry、daemon、数据库或第二套互斥体系。

## 调试、审查与正式验收

- 首次准备 fixture 时只读发现 069 正在运行 canonical Cargo scope，因此没有取得 lock、创建 fixture 或处理其现场；
  待用户报告释放后，主执行者在同一 FD 持有 canonical lock 时复核 active scope 为 0，再开始 072 动态验证。
- 第一版 clean-HEAD 正式轮虽通过 6/6，但独立审查复现 inactive/failed + 非空 `ControlGroup` + `populated=1`
  会被过早 clear，结论为 `CHANGES_REQUIRED`；该轮只保留为调试证据，不计最终结果。
- 整改提交 `c517896924977fe6f044fdc514edc83586294884` 要求非空 cgroup 无论 unit 是否 inactive/failed 都读取
  `cgroup.events`：1 仍冲突、0 才 gone、existing unreadable/malformed 为 unknown；只有空 ControlGroup，或路径已消失且
  终态复读一致时 clear。新增对应反例后 dirty 调试链 7/7 通过。
- 最终正式命令为
  `RONDO_PLAN072_SYSTEMD_FIXTURE=1 PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning -m unittest -v eval.tests.test_shared_heavy_startup_guard`。
  它从 clean `c517896…` 创建全新 task-owned unit/Description nonce/PID start ticks/marker，**7/7 通过，耗时 4.414 秒**。
  冲突 contender 返回 `84`、marker 不存在且旧 scope identity/population 不变；exact teardown 确认 gone 后，恢复 marker 正常完成。
- 既有 `mydev/.github/scripts/test_build_watchdog_lib.py` **9/9** 通过；`bash -n`、`git diff --check` 通过。
  最终独立复审为 `ACCEPT`、`remaining_findings=[]`。

## 边界与现场

- 未运行 Cargo、Docker、真实模型、GPU、API、训练、性能测评或全量测试；正式轮后无 active RONDO scope、无
  `/tmp/rondo-plan072-*` 残留。
- 没有创建主工作区 ignored 资产；fixture metrics/markers 全在自动清理的 task-owned `/tmp` 目录。
- 069 的已有修改与运行现场始终保留；071 和其它 worktree/分支未被修改、合并、推送、rebase、删除或重命名。
