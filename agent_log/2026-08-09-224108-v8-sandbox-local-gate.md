# V8 sandbox 本地资产接线与 Plan 004 门禁补验日志

- 执行时间：2026-08-09（Asia/Shanghai）
- 工作树：`.claude/worktrees/0809-v8-sandbox-local-gate`
- 分支：`0809-v8-sandbox-local-gate`
- 起点：`dd0ea98db6264c5a3991858692bfc7bb2c93f91f`
- 执行合同：`plan/007-v8-sandbox-local-gate.md`

## 范围与实现

本任务只补Plan 004被V8资产404阻断的本地门禁，不修改产品V8 feature、安全策略或中央build watchdog，
也不运行 `V8_FROM_SOURCE`。实现保持为两处薄接线：

1. `scripts/with_codex_v8_artifacts.py` 从 `rustc -vV` 解析本机target，调用既有
   `codex_package.v8.fetch_codex_v8_artifacts`，复用其lock版本解析、OpenAI release下载、两行manifest和
   archive/binding双SHA校验，再在child env中成对覆盖两个 `RUSTY_V8_*` 路径并exec原命令。
2. `just test-with-codex-v8` 复用 `just test` 的Nextest参数和环境，实际Cargo仍原样进入
   `scripts/with-build-lock.sh`，因此build lock、systemd cgroup、资源看门狗和逐run JUnit行为不变。

包装脚本另外拒绝任何已设置的 `V8_FROM_SOURCE`，打印非敏感的版本、target、cache状态、两项路径和实际SHA，
但不打印完整环境。没有复制下载器、checksum解析器或cache管理。

## 轻量验证

- `python3 scripts/test_with_codex_v8_artifacts.py`：5/5通过。覆盖命令分隔、GNU host选择、缺失/重复/未知host、
  source-build拒绝，以及对ambient archive/binding的成对覆盖且不修改parent mapping。
- `V8_FROM_SOURCE=0 python3 scripts/with_codex_v8_artifacts.py -- true`：按预期返回1并明确报告拒绝源码构建。
- 首次 `just fmt` 在运行格式器前因默认 `~/.cache/uv` 对当前沙箱只读而失败；未修改源码。
- 改用worktree内 `UV_CACHE_DIR=.uv-cache` 后，首次沙箱运行又因依赖下载网络策略失败；经已授权的普通依赖
  下载入口原样执行，`just fmt`、`just fmt-check` 和 `git diff --check` 均通过。

## 正式门禁

### OpenAI资产

- V8 crate：`150.4.0`；本机target：`x86_64-unknown-linux-gnu`；release tag：`rusty-v8-v150.4.0`。
- 首轮为 `downloaded_or_refreshed`，后续命中既有cache；两轮均重新下载并解析官方checksum manifest，artifact按
  既有helper的SHA规则复核。
- archive：`librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz`，实际SHA-256
  `a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583`。
- binding：`src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs`，实际SHA-256
  `7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506`。
- 独立读取官方两行manifest并用 `sha256sum` 复算，两项逐字一致。执行环境没有ambient V8 override，未使用
  `V8_FROM_SOURCE`。

### sandbox=true canary

```text
RONDO_V8_CANARY_EXPECT_SANDBOX=1 just test-with-codex-v8 \
  -p codex-v8-poc --no-default-features --features sandbox \
  --retries 0 --flaky-result fail \
  -E 'test(/sandbox_feature_matches_linked_v8/)'
```

- Nextest run：`5d886687-6e6a-47ee-a421-212d30930174`；实际执行1项，1 passed。
- watchdog run：`20260809-224201-1000-1688050`；`wrapper_status=complete`、`run_rc=final_rc=0`、
  `stop_reason=cleanup_reason=none`，峰值memory约1.34GB、swap 0。
- JUnit：`junit-local.xml`，SHA-256
  `f41e264ed064445b4c8726d452eddfae56da572a398efd2144c464a50b2c83c9`；独立XML解析为1 testcase、
  0 failure/error/skip。Nextest终端中的“6 skipped”是过滤器未选择同binary其他测试，不是JUnit testcase skip。
- 结论：显式sandbox feature与实际链接库的 `v8__V8__IsSandboxEnabled()` 探针均为true，Plan 004 G族
  `sandbox=true` 独占canary已取得真实当前树证据。

### 真实 Code Mode host smoke

```text
just test-with-codex-v8 \
  -p codex-code-mode-host --retries 0 --flaky-result fail \
  -E 'test(/remote_session_persists_values_forwards_delegates_and_controls_cells/)'
```

- Nextest run：`1e1b1a13-90a2-43fe-aef3-865bd43c341a`；实际执行1项，1 passed。
- watchdog run：`20260809-224242-1000-1692556`；`wrapper_status=complete`、`run_rc=final_rc=0`、
  `stop_reason=cleanup_reason=none`，峰值memory约5.35GB、swap 0。
- JUnit SHA-256：`69736b2056cde95a2eeb67a73366b53a37544fcc3149e7d01ad965aa3796f287`；独立XML解析为
  1 testcase、0 failure/error/skip。终端中的“38 skipped”同样只是过滤器未选择项。
- 该现有集成测试实际启动 `codex-code-mode-host`，执行JS、跨cell store/load、nested tool callback、yield/terminate
  与session shutdown；不是编译或假host证据。

### workspace前置资源边界

- host smoke结束后的watchdog采样为项目 `184,075,669,504` bytes，主动停线 `195,000,000,000`，只剩约
  10.9GB增长空间；本地文件系统仍有约687GB可用，约束来自RONDO项目级安全停线而非物理磁盘不足。
- 本任务worktree target约4.6GB；已完成的独立整改worktree target约53GB；用户要求保持不受影响的原Plan 004
  worktree target约114GB。后两者均为生成cache，不是源码修改，但当前计划和用户边界不允许擅自清理或写入。
- 历史完整workspace曾清理约129.8GiB target；因此从本任务target直接继续几乎必然在测试完成前被watchdog主动停止。
  本轮没有从小target浪费性冷启动，也没有绕过/抬高195/200GB安全线。

用户明确允许只复用原Plan 004 worktree的Cargo target后，执行：

```text
CARGO_TARGET_DIR=/home/sjc/desktop/RONDO/.claude/worktrees/0809-remaining-test-failures/mydev/codex-rs/target \
  just test-with-codex-v8 --retries 0 --flaky-result fail
```

- watchdog run：`20260809-224925-1000-1719696`。旧target复用有效，但main修订树仍需重编多个workspace crate；
  项目从 `184,075,689,984` 增至 `195,881,336,832` bytes，target增至 `133,493,284,864` bytes。
- 在编译 `codex-core` 及其依赖阶段，watchdog以 `project_reached_proactive_stop` 主动终止：
  `wrapper_status=proactive_stop`、`run_rc=137`、`final_rc=125`、`cleanup_reason=none`。
- 内存峰值约17.53GB，低于19G high/21G max，swap 0；终端末尾的通用“OOM-killed”提示由底层命令rc 137触发，
  本轮真实stop reason是项目存储主动停线，不是cgroup OOM。
- JUnit状态为`absent`，没有任何workspace testcase进入执行，因此不能表述为测试失败或通过。
- 为续跑提出只清理已完成 `zz-done/0809-plan004-independent-remediation` worktree的精确53GB可重建target；
  审批系统因用户尚未明确授权删除其他worktree cache而拒绝，未执行任何清理或变通操作。

### 获授权后的资源恢复与第二次编译停线

用户随后明确允许清理所有无害中间产物/target。只对已确认的可重建Cargo缓存执行精确操作：

- `cargo clean --target-dir .../0809-plan004-independent-remediation/mydev/codex-rs/target`：删除67,738个文件、
  56.1GiB；该整改分支此前已提交、合并和推送。
- `cargo clean --target-dir .../0809-v8-sandbox-local-gate/mydev/codex-rs/target`：删除8,504个文件、5.1GiB；
  本任务后续继续复用旧Plan 004 target。

原样执行同一workspace命令后，watchdog run `20260809-225450-1000-1750123`再次在测试前主动停止：

- 项目从`134,733,799,424`增至`195,355,611,136` bytes，旧target增至`194,115,031,040` bytes。
- `wrapper_status=proactive_stop`、`run_rc=137`、`final_rc=125`、
  `stop_reason=project_reached_proactive_stop`、`cleanup_reason=none`、JUnit absent。
- 内存峰值`20,235,628,544` bytes、不可回收峰值`11,443,040,256` bytes、swap峰值`341,929,984`
  bytes；仍是项目存储主动停线，不是OOM。

只读分解确认旧target的`debug/incremental`单项为66.7GB。用户的清理授权下，精确删除该目录，不删除
`debug/deps`或任何源码；项目回落到`128,610,578,432` bytes。这一步牺牲可重建增量缓存，换取在既有195GB
安全线内完成一次真实workspace执行，不提高阈值。

### workspace唯一实际测试执行

第三次仍使用原命令：

```text
CARGO_TARGET_DIR=/home/sjc/desktop/RONDO/.claude/worktrees/0809-remaining-test-failures/mydev/codex-rs/target \
  just test-with-codex-v8 --retries 0 --flaky-result fail
```

- Nextest run：`74ae9ba9-aa12-4566-9bbe-261d98d9f312`；231个binary，实际运行14,092项，用时381.828秒。
- 结果：14,060 passed、31 failed、1 timed out；Nextest另报23 skipped。由于前两次均在测试前停止且没有JUnit，
  本轮是本计划唯一一次实际workspace测试执行，不因无关失败重跑。
- watchdog run：`20260809-230044-1000-1795173`；`wrapper_status=complete`、`run_rc=final_rc=100`、
  `stop_reason=cleanup_reason=none`、`junit_status=retained`。
- 资源：项目`128,610,582,528`→`157,280,694,272` bytes；target峰值`156,036,870,144` bytes；
  memory峰值`18,961,829,888`、不可回收峰值`12,329,607,168`、swap峰值`189,157,376` bytes。看门狗未触发
  主动停机，也没有残留清理。
- JUnit：`.codex/build-watchdog/20260809-230044-1000-1795173/junit-local.xml`，SHA-256
  `31166103c1b000eb5c9b3e11677df79a49b7a3c6904fcbfb18394f8de66d0337`，与summary一致。独立XML解析为
  14,092 testcase、32 failure节点、0 error、0 testcase-level skipped；Nextest的1项timeout在JUnit中编码为
  failure，因此根节点`failures=32`。

32项终态未通过完整清单如下；均不属于V8 POC、Code Mode host/runtime或Plan 004 G族：

1. `codex-app-server::all::suite::v2::mcp_server_status::mcp_server_status_list_keeps_tools_for_sanitized_name_collisions`
2. `codex-app-server::all::suite::v2::turn_start::turn_start_sends_service_tier_id_to_model_request`
3. `codex-app-server::all::suite::v2::web_search::standalone_web_search_round_trips_output`
4. `codex-app-server-transport::transport::remote_control::websocket::refresh_tests::expired_token_refresh_failure_throttles_reconnect_without_websocket`
5. `codex-app-server-transport::transport::remote_control::websocket::refresh_tests::pairing_http_date_retry_after_throttles_websocket_refresh`
6. `codex-app-server-transport::transport::remote_control::websocket::refresh_tests::websocket_retry_after_throttles_pairing_refresh`
7. `codex-app-server-transport::transport::remote_control::websocket::tests::connect_remote_control_websocket_recovers_after_unauthorized_refresh`
8. `codex-core::all::suite::multi_agent_resume::cold_root_resume_restores_agent_identity_and_role_on_followup`
9. `codex-core::all::suite::personality::config_personality_some_sets_instructions_template`
10. `codex-core::all::suite::personality::user_turn_personality_none_does_not_add_update_message`
11. `codex-core::all::suite::remote_env::deferred_executor_promotes_primary_environment_when_startup_completes`
12. `codex-core::all::suite::plugins::explicit_plugin_mentions_keep_non_conflicting_mcp_for_chatgpt_auth`
13. `codex-core::all::suite::request_permissions::partial_request_permissions_grants_do_not_preapprove_new_permissions`
14. `codex-core::all::suite::request_permissions::request_permissions_grants_apply_to_later_exec_command_calls`
15. `codex-core::all::suite::request_plugin_install::endpoint_recommendation_adds_install_identity_only_to_elicitation_metadata`
16. `codex-core::all::suite::rollout_budget::exhausted_budget_fails_current_and_later_turns`
17. `codex-core::all::suite::request_plugin_install::endpoint_mode_injects_candidates_hides_list_and_rejects_invented_ids`
18. `codex-core::all::suite::unified_exec::unified_exec_defaults_to_pipe`
19. `codex-core::all::suite::search_tool::tool_search_matches_mcp_tools_by_distinct_name_description_and_schema_terms`
20. `codex-core::all::suite::search_tool::tool_search_returns_deferred_v1_multi_agent_tools`
21. `codex-core::all::suite::unified_exec::write_stdin_ctrl_c_default_interrupt_reports_130_for_non_tty_session`
22. `codex-core::all::suite::token_budget::token_budget_context_is_only_emitted_with_full_context`
23. `codex-exec::all::suite::resume::exec_resume_last_respects_cwd_filter_and_all_flag`（Nextest唯一timeout，60.005秒）
24. `codex-exec-server::http_client::http_response_body_streams_share_queued_byte_budget`
25. `codex-login::auth::manager::tests::auth_manager_rejects_stored_personal_access_token_workspace_mismatch`
26. `codex-otel::tests::suite::otlp_http_loopback::otlp_http_exporter_times_out_when_collector_stalls_during_bounded_shutdown`
27. `codex-rmcp-client::auth_status::tests::discover_streamable_http_oauth_returns_normalized_scopes`
28. `codex-rmcp-client::streamable_http_recovery::streamable_http_initialize_retries_transient_http_status`
29. `codex-rmcp-client::streamable_http_recovery::streamable_http_non_session_failure_does_not_trigger_recovery`
30. `codex-rmcp-client::streamable_http_recovery::streamable_http_retries_initialized_notification_status`
31. `codex-rmcp-client::streamable_http_recovery::streamable_http_tools_list_retries_transient_http_status`
32. `codex-rmcp-client::streamable_http_remote::streamable_http_remote_client_round_trips_through_exec_server`

多数失败是10/30秒事件等待或5秒HTTP超时聚类，另有remote-control时间窗口断言和一项plugin guidance断言；
本任务没有逐项根因化，更没有把它们误称为V8回归。按ExecPlan硬边界，全部留给独立测试维护任务。

### 23项ignored逐名审查

JUnit只编码实际执行的14,092项，不能给出额外23项ignored的名称。为完成逐名审查，复用同一已构建target运行
`cargo nextest list --message-format json`；它只查询测试元数据，不执行测试。watchdog run
`20260809-231250-1000-2201899`为rc 0、stop/cleanup none、内存峰值约394MB；输出保存在
`.codex/plan007-nextest-list.json`，SHA-256
`a2aaf52d3913e7dd80a70a4b6172a63902b609d546b26450e78b7e8c13006ab1`。机械对账为14,115 listed =
14,092实际执行 + 23 ignored。名称与审查如下：

- 已知flaky/待行为变更（4）：
  `review_start_exec_approval_item_id_matches_command_execution_item`、
  `manual_compact_non_context_failure_retries_then_emits_task_error`、
  `remote_compact_persists_replacement_history_in_rollout`、
  `injected_user_input_triggers_follow_up_request_with_deltas`。
- 显式人工/外部入口（6）：`write_schema_fixtures_from_env`、`live_create_file_hello_txt`、
  `live_print_working_directory`以及三项`tmux_*resize*`人工smoke。
- 目标平台专用（7）：Linux不支持的
  `code_mode_holds_yielded_result_during_permission_request`、macOS shell snapshot、Windows shell snapshot、
  两项Windows signal、Windows sandbox process write、Windows AltGr。这里的Code Mode项明确因Linux不支持
  request_permissions integration而ignore，不是V8或host链路。
- 只由绿色父测试带环境显式拉起的子进程helper（6）：OAuth store lock、三项OAuth startup、OAuth store
  pinning和removed-current-dir child。

23项完整原名为：

1. `codex-app-server::all::suite::v2::review::review_start_exec_approval_item_id_matches_command_execution_item`
2. `codex-app-server-protocol::schema_fixtures_tests::write_schema_fixtures_from_env`
3. `codex-core::all::suite::code_mode_elicitation::code_mode_holds_yielded_result_during_permission_request`
4. `codex-core::all::suite::compact::manual_compact_non_context_failure_retries_then_emits_task_error`
5. `codex-core::all::suite::compact_remote::remote_compact_persists_replacement_history_in_rollout`
6. `codex-core::all::suite::live_cli::live_create_file_hello_txt`
7. `codex-core::all::suite::live_cli::live_print_working_directory`
8. `codex-core::all::suite::pending_input::injected_user_input_triggers_follow_up_request_with_deltas`
9. `codex-core::all::suite::shell_snapshot::macos_unified_exec_uses_shell_snapshot`
10. `codex-core::all::suite::shell_snapshot::windows_unified_exec_uses_shell_snapshot`
11. `codex-exec-server::exec_process::exec_process_signal_terminates_on_windows::local`
12. `codex-exec-server::exec_process::exec_process_signal_terminates_on_windows::remote`
13. `codex-exec-server::exec_process::remote_windows_sandbox_process_accepts_process_write`
14. `codex-rmcp-client::oauth::store_lock::tests::store_lock_is_released_when_holder_process_exits_child`
15. `codex-rmcp-client::streamable_http_oauth_startup::expired_unrefreshable_startup_child`
16. `codex-rmcp-client::streamable_http_oauth_startup::oauth_startup_child`
17. `codex-rmcp-client::streamable_http_oauth_startup::persisted_credentials_auth_status_child`
18. `codex-rmcp-client::streamable_http_oauth_store_pinning::auto_store_remains_pinned_across_session_recovery_child`
19. `codex-tui::bottom_pane::textarea::tests::altgr_ctrl_alt_char_inserts_literal`
20. `codex-tui::all::suite::resize_reflow::tmux_repeated_resizes_do_not_push_composer_down`
21. `codex-tui::all::suite::resize_reflow::tmux_split_preserves_fresh_session_composer_row_after_resize_reflow`
22. `codex-tui::all::suite::resize_reflow::tmux_width_resize_restore_keeps_visible_content_anchored`
23. `codex-utils-absolute-path::tests::from_absolute_path_with_removed_current_dir_child`

严格目标没有被ignored：workspace中的`codex-v8-poc`为7/7，Code Mode专属crate合计167/167，均0 failure/error；
`sandbox_feature_matches_linked_v8`、`sandbox_expectation_rejects_non_unicode_values`和真实host smoke均在JUnit中实际通过。

### 最终缓存清理

正式Cargo验证结束后，按用户授权执行
`cargo clean --target-dir .../0809-remaining-test-failures/mydev/codex-rs/target`，删除52,616个文件、154.2GiB；
本任务target此前已清空。另删除一次被审批策略拒绝的项目外元数据输出留下的0字节临时文件。所有删除对象都是
可重建构建缓存/空临时文件；源码、计划、日志、worktree与`.codex`中的watchdog/JUnit证据均保留。

## 结论

OpenAI V8 sandbox资产并非缺失：通过既有helper的显式override与双SHA校验即可稳定用于本地Cargo门禁。因此本任务
只增加薄接线，无需修改V8/Code Mode Rust代码。G族sandbox=true和真实host链路已闭环；完整workspace也已从
“测试前404”推进为真实可审查结果，但其31失败+1超时使Plan 004整体仍不能宣称workspace全绿。Windows仍是原计划
必需的未运行目标平台；macOS继续是非阻断跨平台证据缺口。

## 最终轻量门禁与Git边界

- 收口后重新执行`python3 scripts/test_with_codex_v8_artifacts.py`：5/5通过。
- `UV_CACHE_DIR=.uv-cache just fmt`、`UV_CACHE_DIR=.uv-cache just fmt-check`、`git diff --check`通过。
- 没有修改Rust/Cargo manifest，且正式canary、host smoke和workspace已经完成实际编译，故不额外重复clippy或Cargo测试。
- 主工作区在本任务执行期间被并行工作更新到`a194ad84`（`docs: constrain Docker resource usage`）；本工作树保持
  从冻结起点`dd0ea98`开发，没有切换、合并、覆盖或提交主工作区的并行更改。本任务只提交自己的分支，是否合并/推送
  继续等待用户指示。

## 明确未做

未运行Bazel、Windows/macOS、Docker、真实API、真实浏览器、CI、PR、发布或V8源码构建；未修改其他worktree的
源码或分支，只按用户明确授权清理其中可重建Cargo target。
