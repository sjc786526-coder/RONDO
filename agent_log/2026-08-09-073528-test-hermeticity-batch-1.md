# 全量失败测试 hermetic 化（第一批）

日期：2026-08-09
工作树：`.claude/worktrees/005-test-hermetic`，分支 `fix/005-test-hermetic`，起点 `58cc429`
边界：未改产品行为、未改宿主网络与 `/tmp` 标记、未删除或弱化任何断言、未跑真实 API/Docker，未合并、未推送。

## 背景

`agent_log/2026-08-09-020200-baseline-p0-test-audit.md` 把 81 项全量失败归了类，结论是绝大多数为
测试非 hermetic，应修测试而不是改产品或改宿主环境。本批处理其中三个类别。

## 改动

### 看门狗：rustc 诊断被吞（既有缺陷）

`.cargo/rustc-throttle.sh` 里 `exec 8>"$slot_dir/$i" 2>/dev/null` 的重定向会永久作用于本 shell，
随后 `exec "$@"` 起的 rustc 继承 `/dev/null`，编译错误与 clippy 警告全部不可见（cargo 也是从 rustc
stderr 读 JSON 诊断的）。改为 `{ exec 8>"$slot_dir/$i"; } 2>/dev/null`，把静音限制在这次打开动作内。

实测：修复前 `throttle rustc ... p.rs` 无任何输出；修复后正常打印 `unused variable`。
本批新增代码引入的 `unused_doc_comments` 警告就是靠它暴露并修掉的。

### 版本快照（27 项）

`CARGO_PKG_VERSION` 随发布 tag 变化，上游把 `0.0.0` 时期的快照带进了 tag，导致产品正确输出
`0.147.0` 反而对不上。

- 新增 `tui/src/test_support.rs::sanitize_cli_version`：把版本替换为 `[[version]]`，并按原始显示宽度
  重建尾部边框前的留白，边框不会错位。状态卡走 `sanitize_snapshot`（目录 + 版本），
  `history_cell` 的三个更新提示与 session tooltip 单独套用。
- `mcp-server` 的 `serverInfo.version` 期望值从写死的 `0.0.0` 改为复用同一处
  `env!("CARGO_PKG_VERSION")`；断言强度不变，只是不再每次升级批量改数字。

### `/tmp` 祖先项目标记（11项）

宿主 `/tmp` 下残留沙箱建的空 `.git`/`.codex`/`.agents`，祖先游走会把 `/tmp` 当项目根。

- `chatwidget` fixture 的 cwd 是**从不落盘的合成路径**，因此不存在可推断的项目根。改为直接预置
  `status_line_project_root_name_cache` 为 `None`，不再走真实文件系统。10项测试恢复，且既有快照零改动。
- `ext/skills` 的 `repo_ancestry_without_project_marker_does_not_walk_parents` 本批曾传空marker；后续复核确认
  这会短路祖先遍历，当前维护批次已改为非空且确定不存在的fixture marker，保留原测试分支。

### WSL 快捷键快照（2 项）

`footer_props()` 实时探测 WSL，WSL 下粘贴提示是 `ctrl + ⌥ + v`，其他平台是 `ctrl + v`，同一份快照
在两类机器上都合法。`clipboard_paste` 增加 `#[cfg(test)]` 的线程局部 `is_probably_wsl` 覆盖，
两个既有测试钉成非 WSL（快照回到上游值、未改动），另补
`shortcut_overlay_footer_uses_wsl_paste_chord_under_wsl` 覆盖 WSL 变体。

### 家目录 skill 泄漏（2 项）

`HostSkillsService` 经 `resolve_skill_roots` 读真实 `~/.agents/skills`，把开发者本机装的 skill 带进
fixture。`resolve_skill_roots` 增加 `home_dir_override` 参数，service 增加 `#[cfg(test)]` 的
`set_home_dir_override`，两个测试指向空临时 home。

## 验收

- `just test -p codex-tui -p codex-skills-extension -p codex-mcp-server`：**3,547 项运行，3,547 通过，
  4 跳过**（当时覆盖42个历史失败名；ancestry用例随后补强fixture分支）。
- `just clippy` 同三包：退出 0；`just fmt-check`：通过。
- 全部经 `with-build-lock.sh`，一次一组重型任务，各轮 `stop_reason=none/cleanup_reason=none`，
  13轮 `summary.env` 的跨轮最高值为内存 `20,403,429,376` B、swap `141,979,648` B，项目占用
  `70,293,745,664` B（告警线180GB）。

## 未做

- 严格清单机械剩余39项，另有external migration历史偶发与OAuth浏览器副作用2个附加事项；最终分族与
  实施入口见 `plan/004-remaining-test-failures-investigation.md`。
- 未清理宿主 `/tmp` 下的残留 marker；本批修法均不依赖它们是否存在。
