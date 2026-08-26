use std::path::Path;
use std::process::Command;

use anyhow::Context;
use anyhow::Result;
use codex_config::Constrained;
use codex_core::WriterWorkspaceBindingRequest;
use codex_core::config::PermissionProfileSnapshot;
use codex_features::Feature;
use codex_protocol::models::ActivePermissionProfile;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::user_input::UserInput;
use codex_utils_absolute_path::AbsolutePathBuf;
use core_test_support::PathBufExt;
use core_test_support::responses::ev_apply_patch_custom_tool_call;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_function_call;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_sequence_without_request_count_expectation;
use core_test_support::responses::received_responses_request_count;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::skip_if_no_network;
use core_test_support::test_codex::TestCodex;
use core_test_support::test_codex::test_codex;
use serde_json::json;
use tempfile::TempDir;
use tokio::time::Duration;
use tokio::time::timeout;

const STAGE_TIMEOUT: Duration = Duration::from_secs(12);

fn run_git(repo: &Path, args: &[&str]) {
    let output = Command::new("git")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .args(args)
        .current_dir(repo)
        .output()
        .expect("run git");
    assert!(
        output.status.success(),
        "git {args:?} failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

fn repository_with_two_worktrees(
    temp: &TempDir,
) -> (AbsolutePathBuf, AbsolutePathBuf, AbsolutePathBuf) {
    let repository = temp.path().join("repository");
    let writer_a = temp.path().join("writer-a");
    let writer_b = temp.path().join("writer-b");
    std::fs::create_dir(&repository).expect("create repository");
    run_git(&repository, &["init"]);
    run_git(&repository, &["config", "user.name", "Writer Tool Test"]);
    run_git(
        &repository,
        &["config", "user.email", "writer-tool@example.invalid"],
    );
    std::fs::write(repository.join("README.md"), "seed\n").expect("write seed");
    run_git(&repository, &["add", "README.md"]);
    run_git(&repository, &["commit", "-m", "seed"]);
    let writer_a_arg = writer_a.to_string_lossy().into_owned();
    run_git(
        &repository,
        &["worktree", "add", "-b", "writer-a", &writer_a_arg],
    );
    let writer_b_arg = writer_b.to_string_lossy().into_owned();
    run_git(
        &repository,
        &["worktree", "add", "-b", "writer-b", &writer_b_arg],
    );
    (
        std::fs::canonicalize(repository)
            .expect("canonical repository")
            .abs(),
        std::fs::canonicalize(writer_a)
            .expect("canonical writer A")
            .abs(),
        std::fs::canonicalize(writer_b)
            .expect("canonical writer B")
            .abs(),
    )
}

async fn build_writer(
    server: &wiremock::MockServer,
    repository: AbsolutePathBuf,
    writer_a: AbsolutePathBuf,
    writer_b: AbsolutePathBuf,
    binding: AbsolutePathBuf,
) -> Result<TestCodex> {
    let roots = vec![repository.clone(), writer_a, writer_b];
    let mut builder = test_codex()
        .with_config(move |config| {
            config.cwd = repository;
            config.workspace_roots = roots;
            config.workspace_roots_explicit = true;
            config.ephemeral = false;
            config.permissions.approval_policy = Constrained::allow_any(AskForApproval::Never);
            config.permissions.network = None;
            config
                .permissions
                .replace_permission_profile_from_session_snapshot(
                    PermissionProfileSnapshot::active(
                        PermissionProfile::workspace_write_with(
                            &[],
                            NetworkSandboxPolicy::Enabled,
                            /*exclude_tmpdir_env_var*/ true,
                            /*exclude_slash_tmp*/ true,
                        ),
                        ActivePermissionProfile::new(":workspace"),
                    ),
                )
                .expect("install workspace profile");
            config.use_experimental_unified_exec_tool = true;
            config
                .features
                .enable(Feature::UnifiedExec)
                .expect("enable unified exec");
        })
        .with_writer_workspace_binding(WriterWorkspaceBindingRequest {
            worktree_root: binding,
            environment_id: None,
        });
    builder.build(server).await
}

fn exec_args(command: String) -> String {
    serde_json::to_string(&json!({
        "cmd": command,
        "shell": "bash",
        "login": false,
        "yield_time_ms": 5_000,
    }))
    .expect("serialize exec args")
}

async fn submit_writer_turn(test: &TestCodex, prompt: &str) -> Result<()> {
    test.codex
        .submit(Op::UserInput {
            items: vec![UserInput::Text {
                text: prompt.to_string(),
                text_elements: Vec::new(),
            }],
            final_output_json_schema: None,
            responsesapi_client_metadata: None,
            additional_context: Default::default(),
            thread_settings: ThreadSettingsOverrides::default(),
        })
        .await?;
    loop {
        let event = timeout(STAGE_TIMEOUT, test.codex.next_event())
            .await
            .with_context(|| format!("turn `{prompt}` produced no terminal event"))??;
        match event.msg {
            EventMsg::TurnComplete(_) => return Ok(()),
            EventMsg::Error(error) => {
                anyhow::bail!("turn `{prompt}` failed before completion: {error:?}")
            }
            EventMsg::TurnAborted(error) => {
                anyhow::bail!("turn `{prompt}` aborted before completion: {error:?}")
            }
            _ => {}
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn bound_writers_execute_only_inside_their_exact_worktrees() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let temp = TempDir::new()?;
    let (repository, writer_a, writer_b) = repository_with_two_worktrees(&temp);
    let server = start_mock_server().await;
    let calls = [
        (
            "writer-a-write",
            exec_args("printf writer-a > marker-a.txt".to_string()),
        ),
        (
            "writer-b-write",
            exec_args("printf writer-b > marker-b.txt".to_string()),
        ),
        (
            "writer-a-outside",
            exec_args(format!(
                "printf escaped > '{}'",
                writer_b.join("outside.txt").display()
            )),
        ),
        (
            "writer-a-escalated",
            serde_json::to_string(&json!({
                "cmd": "printf escalated > escalated.txt",
                "shell": "bash",
                "login": false,
                "sandbox_permissions": "require_escalated",
                "justification": "test writer binding bypass rejection",
            }))?,
        ),
    ];
    let _responses = mount_sse_sequence_without_request_count_expectation(
        &server,
        vec![
            sse(vec![
                ev_response_created("resp-a-write"),
                ev_function_call(calls[0].0, "exec_command", &calls[0].1),
                ev_completed("resp-a-write"),
            ]),
            sse(vec![
                ev_assistant_message("msg-a-write", "writer A done"),
                ev_completed("resp-a-write-done"),
            ]),
            sse(vec![
                ev_response_created("resp-b-write"),
                ev_function_call(calls[1].0, "exec_command", &calls[1].1),
                ev_completed("resp-b-write"),
            ]),
            sse(vec![
                ev_assistant_message("msg-b-write", "writer B done"),
                ev_completed("resp-b-write-done"),
            ]),
            sse(vec![
                ev_response_created("resp-a-outside"),
                ev_function_call(calls[2].0, "exec_command", &calls[2].1),
                ev_completed("resp-a-outside"),
            ]),
            sse(vec![
                ev_assistant_message("msg-a-outside", "outside write rejected"),
                ev_completed("resp-a-outside-done"),
            ]),
            sse(vec![
                ev_response_created("resp-a-escalated"),
                ev_function_call(calls[3].0, "exec_command", &calls[3].1),
                ev_completed("resp-a-escalated"),
            ]),
            sse(vec![
                ev_assistant_message("msg-a-escalated", "escalation rejected"),
                ev_completed("resp-a-escalated-done"),
            ]),
            sse(vec![
                ev_response_created("resp-a-patch"),
                ev_apply_patch_custom_tool_call(
                    "writer-a-patch",
                    "*** Begin Patch\n*** Add File: patch-a.txt\n+writer A patch\n*** End Patch",
                ),
                ev_completed("resp-a-patch"),
            ]),
            sse(vec![
                ev_assistant_message("msg-a-patch", "patch done"),
                ev_completed("resp-a-patch-done"),
            ]),
            sse(vec![
                ev_response_created("resp-a-patch-escape"),
                ev_apply_patch_custom_tool_call(
                    "writer-a-patch-escape",
                    "*** Begin Patch\n*** Add File: escape/patch-escape.txt\n+escaped patch\n*** End Patch",
                ),
                ev_completed("resp-a-patch-escape"),
            ]),
            sse(vec![
                ev_assistant_message("msg-a-patch-escape", "patch escape rejected"),
                ev_completed("resp-a-patch-escape-done"),
            ]),
        ],
    )
    .await;

    let writer_a_thread = timeout(
        STAGE_TIMEOUT,
        build_writer(
            &server,
            repository.clone(),
            writer_a.clone(),
            writer_b.clone(),
            writer_a.clone(),
        ),
    )
    .await
    .context("start writer A timed out")??;
    let writer_b_thread = timeout(
        STAGE_TIMEOUT,
        build_writer(
            &server,
            repository.clone(),
            writer_a.clone(),
            writer_b.clone(),
            writer_b.clone(),
        ),
    )
    .await
    .context("start writer B timed out")??;
    for writer in [&writer_a_thread, &writer_b_thread] {
        let binding = writer
            .codex
            .writer_workspace_binding()
            .await
            .expect("writer binding should remain present before first action");
        assert_eq!(
            binding.availability,
            codex_protocol::protocol::WriterWorkspaceBindingAvailability::Available
        );
    }

    submit_writer_turn(&writer_a_thread, "write writer A marker").await?;
    submit_writer_turn(&writer_b_thread, "write writer B marker").await?;
    assert_eq!(
        std::fs::read_to_string(writer_a.join("marker-a.txt"))?,
        "writer-a"
    );
    assert_eq!(
        std::fs::read_to_string(writer_b.join("marker-b.txt"))?,
        "writer-b"
    );
    assert!(!repository.join("marker-a.txt").exists());
    assert!(!repository.join("marker-b.txt").exists());
    assert!(!writer_a.join("marker-b.txt").exists());
    assert!(!writer_b.join("marker-a.txt").exists());

    submit_writer_turn(&writer_a_thread, "attempt outside writer A").await?;
    assert!(!writer_b.join("outside.txt").exists());

    submit_writer_turn(&writer_a_thread, "attempt escalation bypass").await?;
    assert!(!writer_a.join("escalated.txt").exists());

    submit_writer_turn(&writer_a_thread, "apply inside writer A").await?;
    assert_eq!(
        std::fs::read_to_string(writer_a.join("patch-a.txt"))?,
        "writer A patch\n"
    );

    std::os::unix::fs::symlink(&writer_b, writer_a.join("escape"))?;
    submit_writer_turn(
        &writer_a_thread,
        "attempt apply patch through escape symlink",
    )
    .await?;
    assert!(!writer_b.join("patch-escape.txt").exists());

    let user_shell_escape = writer_b.join("user-shell-escape.txt");
    writer_a_thread
        .codex
        .submit(Op::RunUserShellCommand {
            command: format!("printf escaped > '{}'", user_shell_escape.display()),
        })
        .await?;
    let mut saw_bound_shell_rejection = false;
    loop {
        let event = timeout(STAGE_TIMEOUT, writer_a_thread.codex.next_event()).await??;
        match event.msg {
            EventMsg::Error(error) => {
                saw_bound_shell_rejection |= error
                    .message
                    .contains("/shell is unavailable while a writer workspace binding is active");
            }
            EventMsg::TurnComplete(_) => break,
            EventMsg::TurnAborted(error) => {
                anyhow::bail!("bound /shell rejection turn aborted: {error:?}")
            }
            _ => {}
        }
    }
    assert!(saw_bound_shell_rejection);
    assert!(!user_shell_escape.exists());
    assert_eq!(received_responses_request_count(&server).await?, 12);

    writer_a_thread.codex.shutdown_and_wait().await?;
    writer_b_thread.codex.shutdown_and_wait().await?;
    Ok(())
}
