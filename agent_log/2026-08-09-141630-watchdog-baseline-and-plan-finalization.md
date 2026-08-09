# 看门狗、基线事实源与剩余测试方案收口

日期：2026-08-09

工作树：`.claude/worktrees/0809-claude-fix-acceptance`，分支
`audit/0809-claude-fix-acceptance`，起点 `b9f724c`。未修改Claude工作树、main、宿主网络、`/tmp`
marker或上游只读快照；未合并、未推送。

## 实质修改

### 看门狗 F2/F7

- scope存活主判据改为cgroup v2 `cgroup.events: populated`，覆盖后代cgroup；`cgroup.procs`只报告根层
  direct members。`systemctl is-active` 不再参与主循环、异常收尾或终止确认，D-Bus错误不能伪装inactive。
- 终止改为约1秒kill round与无界外层监督，使用Bash `SECONDS` 按真实经过时间约每30秒报告。拿不到
  ControlGroup或必要计数器时，即使命令返回0也以81 fail-closed。
- 正式Nextest入口保持 `NEXTEST_PROFILE=local`，逐轮生成配置并把JUnit直接写到独占run directory；
  不再glob/copy `target` 历史报告。summary记录报告状态、路径和SHA，Nextest返回0但报告缺失/无效时以83失败。
- 新增7项轻量脚本回归，覆盖后代population、unknown/gone边界、同名local profile、旧配置冲突以及
  JUnit absent/invalid/retained+SHA。

### Guardian F3

- 新增受Git跟踪的 `core/upstream-source-baseline.toml`，唯一记录
  `rust-v0.147.0` 与 peeled commit `be6e8eac029b183056b7e4402879f15d2c85f61b`。
- evidence在编译期嵌入并严格解析该事实，meta保留 `guardian_source_baseline` tag并新增
  `guardian_source_commit`；解析失败只放弃该轮证据并告警，不改变审批结果。
- 新增独立基线升级脚本，核对manifest schema、workspace版本、`tag^{}`、snapshot HEAD、detached/clean与
  当前WBS/开发环境引用。普通Rust测试不依赖git-ignored快照。

### 第一批测试遗留

- skills ancestry从空marker改为非空且确定不存在的marker，恢复“遍历祖先均未命中后回退cwd”的原分支。
- skills home override改为构造期注入，消除可变setter与既有cache组合的隐患。
- TUI版本规范化只替换 `(v<version>)` 与 `<version> ->` 两种真实渲染结构，保留无关同串文本；补宽度回归。
- 第一批日志纠正为42个历史失败名、严格剩余39+2附加事项；13轮资源峰值纠正为
  memory `20,403,429,376` B、swap `141,979,648` B、project `70,293,745,664` B。

### 最终方案与文档

- `plan/004` 已从调查底稿重写为39个严格失败+2个附加事项的最终实施合同，冻结DNS21、ambient HTTP5、
  shell1、Landlock1、`/tmp`6、PowerShell1、V8 1、时序2、exec-server1的集合与逐族门禁。
- Landlock依据改为已证实的10秒 `Sandbox(Timeout)` 与seccomp无地址分支；不再声称代理是已证根因。
- V8采用full-workspace单向蕴含与独占default=false/sandbox=true双canary；时序项要求修改前后各做
  1线程/10线程200次，不以加timeout收口。
- WBS、开发环境、eval数据契约和P1草稿同步机器基线tag/commit及当前测试维护状态。

## 验证

- `python3 -m unittest discover -s mydev/.github/scripts -p 'test_*.py'`：42项通过。
- `bash -n`：`with-build-lock.sh` 与 `build-watchdog-lib.sh` 通过；`shellcheck` 当前未安装，未运行。
- `verify_upstream_source_baseline.py --snapshot /home/sjc/desktop/RONDO/codex-source-code`：通过，确认tag、
  commit、HEAD、detached与clean；未修改根目录快照。
- `cargo-nextest 0.9.140 show-config` 接受逐轮配置与同名 `local` profile。
- `just fmt`、`just fmt-check`、Python compileall、`git diff --check`：通过。
- 看门狗 `/bin/true` smoke：user D-Bus不可用，按预期返回81；summary为
  `wrapper_status=watchdog_attach_failed`、`junit_status=not_applicable`。
- 正式 `just test` ancestry定向入口同样在Cargo启动前返回81；summary为
  `wrapper_status=watchdog_attach_failed`、`junit_status=absent`，run directory只有metrics/config/summary，
  没有旧JUnit，且无cargo/rustc/nextest残留。

## 未运行与边界

宿主 `/run/user/1000/bus` 不存在且 `systemctl --user` 不可用。按仓库硬约束不能绕过看门狗，因此本轮
Rust定向测试、clippy和Bazel均未运行；不能把上述正式入口称为测试通过。Bazel本机原本也未安装。
代码已格式化并完成静态审查，但合并前仍需在user D-Bus恢复后依次补跑skills、TUI、core定向测试和相关clippy，
并核对Nextest `junit_status=retained` 与clippy `not_applicable`。
