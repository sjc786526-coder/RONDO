# P0 严格验收补强与受控全量复核

## 结论

- 004 独立方案指出的两个产品边界合理，已落地并通过测试：permission hook 在 Guardian 前直接
  resolve 时不产证据；关闭 evidence 时捕获路径只做一次原子读取，不取全局锁、不分配、不序列化。
- 证据写入失败不改变 Guardian 决策的边界也新增了直接回归。
- **P0 严格验收通过。** `just test -p codex-core` 的字面整包全绿要求经实际运行证明不是有效的
  hermetic 门禁：package-only 构建缺少 workspace helper binaries，且把受监控项目根作为临时目录时
  会把根 `AGENTS.md` 注入 fixture。验收改以 P0 边界精确测试加完整 workspace 全量为准，不修改产品
  或快照去迎合错误环境。
- 未运行 Bazel 与 `just argument-comment-lint`（本机未装 Bazel）；没有调用真实模型 API、Docker
  或外发 `E_final`。

## 补强内容

1. `capture_final_request` 增加全局活动绑定原子标志。关闭或没有活动 Guardian 轮时，一次原子读取后
   立即返回；绑定与解绑测试锁定完整生命周期，避免每个主 Agent 请求进入 capture registry。
2. 新增 `permission_hook_resolution_writes_no_guardian_evidence` 集成测试：trusted allow hook 直接
   resolve 后，只出现父 Agent 请求，hook marker 存在，证据目录不存在。
3. 新增证据目录写失败回归，确认 I/O 错误被吞并为告警，不传播到审批主链。
4. 看门狗短命 scope 的最终采样先检查 counter 可读性，正常 teardown 不再泄漏
   `memory.current: No such file` 一类噪声。

新增三项精确测试 3/3 通过；此前 P0 8/8、Guardian/auto-review 10/10、config/schema 6/6 及
Guardian/MCP 慢测 1/1 的证据继续成立。完整 workspace 本轮也执行了全部新增测试，失败清单中没有
上述能力。

## 门禁执行与非产品故障

- `UV_CACHE_DIR=.uv-cache just fmt`：通过。首次未指定 `UV_CACHE_DIR` 时只因沙箱不可写
  `~/.cache/uv` 退出，未触及源码。
- `just fix -p codex-core`：通过，约 2 分 34 秒。
- 首次精确测试把 `TMPDIR` 指到了尚未创建的 worktree `.codex/tmp`，nextest 在测试启动前返回 104；
  创建正确目录后同一过滤器 3/3 通过。该次不是代码或测试失败。
- 诊断性 `just test -p codex-core`：3,306 run，3,090 passed，216 failed，8 skipped。主要原因是
  package-only 构建不产生 `codex`、`test_stdio_server`、`codex-code-mode-runtime` 等 workspace helper
  binaries，以及项目内 `TMPDIR` 让 root `AGENTS.md` 进入 fixture；这条结果只用于否定字面门禁，
  不作为 P0 回归证据。
- 首次完整 workspace 启动按 fail-closed 退出，因为当前开发沙箱不能访问 systemd user bus；以已授权
  宿主权限重启后看门狗正常附着。
- 完整 workspace 首轮编译在 `v8 150.4.0` 默认 denoland sandbox archive URL 得到 404。按仓库
  `.github/actions/setup-rusty-v8/action.yml` 下载 OpenAI `rusty-v8-v150.4.0` archive、binding 与两行
  SHA-256 清单，两项校验均为 OK；设置官方两个 override 后继续成功。没有降级 V8 feature，也没有
  从源码编译 V8。

## 完整 workspace 结果

JUnit run id：`bdd2bc4a-a3c6-4a6c-955c-20e3e3a72684`。

- 14,077 tests run；13,996 passed；81 failed；0 timed out；23 skipped；27 项首轮失败后重试通过。
- 测试阶段 396.500 秒；含增量编译、枚举与测试的受监督命令共约 744 秒。
- 相对上一次 RONDO 全量的 76 个终态未通过项：72 个共同，新增 9 个，不再失败 4 个。
- 新增 9 项中，API/doctor/managed proxy/plugin transport/exec logging/http client/landlock 共 7 项已在
  纯上游 0.147.0 参照中失败；另外 2 项分别是 realtime 尾部事件等待和 WireMock truncated replay，
  属本轮全量并发波动。没有 P0 文件或 Guardian evidence/override 失败。
- 不再失败的 4 项包括此前 Guardian/MCP 47 秒慢测、两个 realtime connect-failure 和 external-agent
  migration。后者这次没有遗留 scope 进程。
- managed OAuth 测试调用了系统默认浏览器，打开本机临时 `127.0.0.1` authorize/callback 页面；没有
  访问真实外部 OAuth 服务，但说明完整全量并非完全无交互，后续应给浏览器调用注入 stub。

### 81 项归因

| 分类 | 数量 | 内容与判断 |
| --- | ---: | --- |
| release fixture / TUI snapshot | 27 | 4 个 MCP server version fixture 与 23 个 TUI version snapshot 仍是 `0.0.0` 对 `0.147.0` 的发布 lock 规范化差异。 |
| 代理 / 网络环境 | 28 | 20 个 network-proxy 加 8 个 API、doctor、session、plugin transport、exec/http client 与 landlock 用例；均可由纯上游参照解释。 |
| cwd / `/tmp` 项目标记 | 18 | config、git root、realtime context、exec roots、secrets、skills ancestry 与 TUI title/status fixture 继承本机 `/tmp` 项目标记。 |
| 快捷键 snapshot | 2 | `ctrl + v` 与当前 `ctrl + option + v` 等本机 chord 差异。 |
| 本机 skill 泄漏 | 2 | fixture 发现项目外 `kimi-webbridge`，与 P0 无关。 |
| V8 feature / archive | 1 | sandbox release archive 报 sandbox=true，而独立 `codex-v8-poc` 默认 feature 断言 false。 |
| 全量并发波动 | 2 | realtime 尾事件等待与 WireMock truncated replay；未在前两次同环境结果中稳定出现。 |
| shell safe-command 断言 | 1 | 与上游相同源码在本机仍断言失败，不在 P0 改动路径。 |

### 81 个终态失败完整清单

```text
codex-api files::tests::upload_openai_file_reports_blob_transport_diagnostics_without_sas
codex-cli::bin/codex doctor::tests::mcp_check_warns_for_optional_http_reachability
codex-core config::config_loader_tests::codex_home_is_not_loaded_as_project_layer_from_home_dir
codex-core config::config_loader_tests::project_layers_disabled_when_untrusted_or_unknown
codex-core git_info_tests::resolve_root_git_project_for_trust_returns_none_outside_repo
codex-core realtime_context::tests::recent_work_section_groups_threads_by_cwd
codex-core realtime_context::tests::workspace_section_requires_meaningful_structure
codex-core session::tests::managed_network_proxy_decider_survives_full_access_start
codex-core session::tests::user_shell_commands_do_not_inherit_managed_network_proxy
codex-core tools::handlers::shell::tests::commands_generated_by_shell_command_handler_can_be_matched_by_is_known_safe_command
codex-core::all suite::realtime_conversation::conversation_close_routes_only_remaining_transcript_tail_once
codex-core::all suite::unified_exec_process_events::exec_command_consumes_pushed_remote_process_events::truncated_event_replay
codex-core-plugins remote::search::tests::search_remote_plugins_redacts_sensitive_parameters_from_transport_errors
codex-exec-server::exec_process remote_process_preserves_empty_workspace_roots
codex-exec-server::http_request_logging delegated_http_failure_warning_redacts_request_url
codex-http-client route_aware_client_pool::tests::without_url_redacts_transport_error_urls
codex-linux-sandbox::all suite::landlock::sandbox_blocks_wget
codex-mcp-server::all suite::codex_tool::test_patch_approval_triggers_elicitation
codex-mcp-server::all suite::codex_tool::test_shell_command_approval_triggers_elicitation
codex-mcp-server::all suite::codex_tool::test_codex_tool_forwards_skills_extension_warnings
codex-mcp-server::all suite::codex_tool::test_codex_tool_passes_base_instructions
codex-network-proxy http_proxy::tests::http_connect_accept_blocks_in_limited_mode
codex-network-proxy http_proxy::tests::http_connect_accept_blocks_hooked_host_in_full_mode_without_mitm_state
codex-network-proxy http_proxy::tests::http_connect_accept_passes_environment_id_to_decider
codex-network-proxy http_proxy::tests::http_connect_accept_defers_brokered_host_mitm_until_protocol_detection
codex-network-proxy mitm::tests::mitm_policy_blocks_disallowed_method_and_records_telemetry
codex-network-proxy mitm::tests::mitm_policy_allows_matching_hooked_write_in_full_mode
codex-network-proxy mitm::tests::mitm_policy_blocks_hook_miss_for_hooked_host_and_records_telemetry_in_full_mode
codex-network-proxy mitm::tests::mitm_policy_blocks_matching_hooked_write_in_limited_mode
codex-network-proxy network_policy::tests::evaluate_host_policy_emits_domain_event_for_decider_ask
codex-network-proxy network_policy::tests::evaluate_host_policy_emits_domain_event_for_decider_allow_override
codex-network-proxy network_policy::tests::evaluate_host_policy_emits_execution_id_for_baseline_allow
codex-network-proxy runtime::tests::add_allowed_domain_removes_matching_deny_entry
codex-network-proxy runtime::tests::host_blocked_global_wildcard_allowlist_allows_public_hosts_except_denylist
codex-network-proxy runtime::tests::host_blocked_requires_allowlist_match
codex-network-proxy runtime::tests::host_blocked_subdomain_wildcards_exclude_apex
codex-network-proxy socks5::tests::handle_socks5_tcp_blocks_limited_mode_without_mitm_state
codex-network-proxy socks5::tests::handle_socks5_tcp_blocks_hooked_non_https_host_in_full_mode
codex-network-proxy socks5::tests::handle_socks5_tcp_uses_mitm_for_hooked_host_in_full_mode
codex-network-proxy socks5::tests::handle_socks5_tcp_detects_tls_for_brokered_nonstandard_port_in_full_mode
codex-network-proxy socks5::tests::handle_socks5_tcp_uses_mitm_in_limited_mode
codex-secrets tests::environment_id_fallback_has_cwd_prefix
codex-skills-extension host_roots::tests::repo_ancestry_without_project_marker_does_not_walk_parents
codex-skills-extension host_service::tests::snapshot_for_config_merges_extension_host_and_legacy_plugin_roots
codex-skills-extension host_service::tests::snapshot_for_config_preserves_host_precedence_for_symlinked_plugin_root
codex-tui bottom_pane::chat_composer::tests::footer_mode_snapshots
codex-tui bottom_pane::chat_composer::tests::shortcut_footer_displays_configured_chords
codex-tui chatwidget::tests::status_surface_previews::missing_project_root_uses_different_status_and_title_preview_sources
codex-tui chatwidget::tests::status_surface_previews::status_line_setup_popup_mixed_snapshot
codex-tui chatwidget::tests::status_surface_previews::status_line_setup_popup_hardcoded_only_snapshot
codex-tui chatwidget::tests::status_surface_previews::status_surface_preview_lines_hardcoded_only_snapshot
codex-tui chatwidget::tests::status_surface_previews::status_surface_preview_lines_mixed_snapshot
codex-tui chatwidget::tests::status_surface_previews::terminal_title_setup_popup_mixed_snapshot
codex-tui chatwidget::tests::terminal_title::terminal_title_activity_indicators_do_not_animate_when_animations_are_disabled
codex-tui chatwidget::tests::terminal_title::terminal_title_action_required_respects_spinner_setting
codex-tui chatwidget::tests::terminal_title::terminal_title_action_required_blinks_when_animations_are_enabled
codex-tui chatwidget::tests::terminal_title::terminal_title_shows_action_required_while_exec_approval_is_pending
codex-tui history_cell::tests::pnpm_update_available_history_cell_snapshot
codex-tui history_cell::tests::session_info_availability_nux_tooltip_snapshot
codex-tui history_cell::tests::standalone_unix_update_available_history_cell_snapshot
codex-tui history_cell::tests::standalone_windows_update_available_history_cell_snapshot
codex-tui status::tests::status_snapshot_includes_forked_from
codex-tui status::tests::status_snapshot_includes_enterprise_monthly_credit_limit
codex-tui status::tests::status_snapshot_cached_limits_hide_credits_without_flag
codex-tui status::tests::status_snapshot_includes_credits_and_limits
codex-tui status::tests::status_snapshot_includes_reasoning_details
codex-tui status::tests::status_snapshot_includes_monthly_limit
codex-tui status::tests::status_snapshot_shows_active_user_defined_profile
codex-tui status::tests::status_snapshot_shows_auto_review_permissions
codex-tui status::tests::status_snapshot_shows_missing_limits_message
codex-tui status::tests::status_snapshot_shows_refreshing_limits_notice
codex-tui status::tests::status_snapshot_shows_stale_limits_message
codex-tui status::tests::status_snapshot_shows_unavailable_limits_message
codex-tui status::tests::status_snapshot_treats_refreshing_empty_limits_as_unavailable
codex-tui status::tests::status_snapshot_uses_default_reasoning_when_config_empty
codex-tui status::tests::status_snapshot_truncates_halfwidth_kana_in_narrow_terminal
codex-tui status::tests::status_snapshot_truncates_in_narrow_terminal
codex-tui status::tests::status_snapshot_uses_generic_limit_labels_for_unsupported_windows
codex-tui status::tests::transcript_overlay_remeasures_status_after_rate_limit_refresh
codex-tui status::tests::status_snapshot_shows_chatgpt_plan_without_email
codex-v8-poc tests::sandbox_feature_matches_linked_v8
```

## 资源峰值与清理边界

- 本轮最终项目/target：121,624,457,216 B / 119,968,636,928 B；项目采样峰值
  121,622,646,784 B。完整 0.147.0 历史最大仍约 127.4GB。
- cgroup 总内存峰值 20,406,243,328 B；匿名+内核不可回收峰值 12,224,589,824 B；swap 峰值
  391,446,528 B；宿主最低 `MemAvailable` 11,036,488 KiB。
- cgroup/宿主 full PSI avg10 瞬时峰值 15.27%/16.87%，没有持续 20 秒，未触发停止；
  `stop_reason=none`、`cleanup_reason=none`。
- 因此 19G high / 21G max / 5G swap 与 180/195/200GB 磁盘线在 26GB RAM + 10GB swap 的 WSL
  上既允许真实峰值，也保留明确硬边界。验收冻结后通过同一看门狗清理本 worktree 的精确 target：
  删除 86,873 个可重建文件，Cargo 报告回收 120.3GiB，项目降至 1,655,726,080 B。
