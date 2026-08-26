use super::*;
use crate::config::test_config;
use codex_protocol::models::PermissionProfile;
use pretty_assertions::assert_eq;
use std::fs;
use std::path::Path;
use std::process::Command;
use tempfile::TempDir;

const LOCAL_EXECUTION_ENVIRONMENT: &str = "local-w0";

struct GitWorktreeFixture {
    _owner: TempDir,
    primary: AbsolutePathBuf,
    writer_a: AbsolutePathBuf,
    writer_b: AbsolutePathBuf,
}

impl GitWorktreeFixture {
    fn new() -> Self {
        let owner = TempDir::new().expect("create task-owned Git fixture");
        let primary = absolute(owner.path().join("repository"));
        let writer_a = absolute(owner.path().join("writer-a"));
        let writer_b = absolute(owner.path().join("writer-b"));
        fs::create_dir(&primary).expect("create primary repository directory");
        run_git(&primary, &["init", "-q", "-b", "main"]);
        fs::write(primary.join("marker.txt"), "base\n").expect("write initial marker");
        run_git(&primary, &["add", "marker.txt"]);
        run_git(
            &primary,
            &[
                "-c",
                "user.name=Plan 084",
                "-c",
                "user.email=plan084@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-q",
                "-m",
                "initial",
            ],
        );
        run_git(&primary, &["branch", "writer-a"]);
        run_git(&primary, &["branch", "writer-b"]);
        run_git(
            &primary,
            &[
                "worktree",
                "add",
                "-q",
                writer_a.as_path().to_str().expect("UTF-8 worktree path"),
                "writer-a",
            ],
        );
        run_git(
            &primary,
            &[
                "worktree",
                "add",
                "-q",
                writer_b.as_path().to_str().expect("UTF-8 worktree path"),
                "writer-b",
            ],
        );
        commit_writer_identity(&writer_a, "writer-a");
        commit_writer_identity(&writer_b, "writer-b");
        Self {
            _owner: owner,
            primary,
            writer_a,
            writer_b,
        }
    }

    async fn authorized_config(&self) -> Config {
        let mut config = test_config().await;
        config.cwd = self.primary.clone();
        config.workspace_roots = vec![self.writer_a.clone(), self.writer_b.clone()];
        config.workspace_roots_explicit = true;
        config
            .permissions
            .set_permission_profile(PermissionProfile::workspace_write())
            .expect("workspace-write profile should be allowed in tests");
        config
            .permissions
            .set_workspace_roots(config.workspace_roots.clone());
        config
    }
}

#[tokio::test]
async fn baseline_and_binding_candidate_use_the_same_two_writer_actions() {
    let fixture = GitWorktreeFixture::new();
    let caller_config = fixture.authorized_config().await;
    let task_a =
        NaturalLanguageWriterTask::prepare(&fixture.writer_a, "writer-a\n", "writer-output.txt")
            .expect("prepare writer A task text, Git facts, and fake action");
    let task_b =
        NaturalLanguageWriterTask::prepare(&fixture.writer_b, "writer-b\n", "writer-output.txt")
            .expect("prepare writer B task text, Git facts, and fake action");
    assert!(
        task_a
            .instruction
            .contains(fixture.writer_a.as_path().to_str().expect("UTF-8 path"))
    );
    assert!(
        task_b
            .instruction
            .contains(fixture.writer_b.as_path().to_str().expect("UTF-8 path"))
    );
    assert!(task_a.instruction.contains("git status/diff"));
    assert_eq!(task_a.git_facts.branch, "writer-a");
    assert_eq!(task_b.git_facts.branch, "writer-b");
    assert_ne!(task_a.git_facts.head, task_b.git_facts.head);
    assert!(task_a.git_facts.status.is_empty());
    assert!(task_b.git_facts.diff.is_empty());

    // The existing flow works when each initiating turn already has the intended context. The
    // task text, Git facts, and fake action therefore remain a fair cooperative baseline before
    // context drift. Deterministic execution does not claim a model-compliance frequency.
    let cooperative_a = caller_context_for(&caller_config, &fixture.writer_a);
    let cooperative_b = caller_context_for(&caller_config, &fixture.writer_b);
    let baseline_cooperative_a = task_a
        .execute_baseline(&cooperative_a)
        .expect("cooperative baseline action A");
    let baseline_cooperative_b = task_b
        .execute_baseline(&cooperative_b)
        .expect("cooperative baseline action B");
    assert_eq!(baseline_cooperative_a.effective_cwd, fixture.writer_a);
    assert_eq!(baseline_cooperative_b.effective_cwd, fixture.writer_b);
    fs::remove_file(baseline_cooperative_a.output_path)
        .expect("remove task-owned cooperative output A");
    fs::remove_file(baseline_cooperative_b.output_path)
        .expect("remove task-owned cooperative output B");

    // Current V2 spawn/resume builds each child from the initiating turn. Natural-language target
    // and Git facts remain available, but the execution context itself is still caller-relative.
    let baseline_a = task_a
        .execute_baseline(&caller_config)
        .expect("baseline fake action A");
    let baseline_b = task_b
        .execute_baseline(&caller_config)
        .expect("baseline fake action B");
    assert_eq!(baseline_a.effective_cwd, fixture.primary);
    assert_eq!(baseline_b.effective_cwd, fixture.primary);
    assert_eq!(baseline_a.output_path, baseline_b.output_path);
    assert_eq!(
        fs::read_to_string(&baseline_b.output_path).expect("read colliding baseline output"),
        "writer-b\n"
    );
    fs::remove_file(&baseline_b.output_path).expect("remove task-owned baseline output");

    let writer_a = bind_slot(&caller_config, &fixture.writer_a);
    let writer_b = bind_slot(&caller_config, &fixture.writer_b);
    let candidate_a = writer_a
        .runtime
        .run(&task_a.action)
        .expect("candidate action A");
    let candidate_b = writer_b
        .runtime
        .run(&task_b.action)
        .expect("candidate action B");

    assert_eq!(candidate_a.effective_cwd, fixture.writer_a);
    assert_eq!(candidate_b.effective_cwd, fixture.writer_b);
    assert_ne!(candidate_a.output_path, candidate_b.output_path);
    assert_eq!(
        fs::read_to_string(candidate_a.output_path).expect("read writer A output"),
        "writer-a\n"
    );
    assert_eq!(
        fs::read_to_string(candidate_b.output_path).expect("read writer B output"),
        "writer-b\n"
    );
}

#[tokio::test]
async fn cold_reload_revalidates_binding_instead_of_using_caller_cwd() {
    let fixture = GitWorktreeFixture::new();
    let caller_config = fixture.authorized_config().await;
    let initial = bind_runtime(&caller_config, &fixture.writer_a);
    let persisted_binding = initial.binding.clone();
    drop(initial);

    let mut different_caller = caller_config;
    different_caller.cwd = fixture.primary.clone();
    let parked = fixture
        .writer_a
        .parent()
        .expect("fixture parent")
        .join("writer-a-cold-missing");
    fs::rename(&fixture.writer_a, &parked).expect("park writer A before cold reload");
    let invalidated = BoundWriterRuntime::reload(
        persisted_binding.clone(),
        &different_caller,
        LOCAL_EXECUTION_ENVIRONMENT,
    )
    .expect_err("cold reload must re-read and reject the missing worktree");
    assert_eq!(invalidated.failure, BindingFailure::WorktreeMissing);
    assert!(!parked.join("writer-output.txt").exists());

    fs::rename(&parked, &fixture.writer_a).expect("restore writer A after failed cold reload");
    let reloaded = BoundWriterRuntime::reload(
        persisted_binding,
        &different_caller,
        LOCAL_EXECUTION_ENVIRONMENT,
    )
    .expect("cold reload should rebuild and revalidate the binding");
    let observation = reloaded
        .run(&action(
            &fixture.writer_a,
            "reloaded\n",
            "writer-output.txt",
        ))
        .expect("first action after reload");

    assert_eq!(observation.effective_cwd, fixture.writer_a);
    assert_eq!(
        different_caller.cwd, fixture.primary,
        "the caller context is not rewritten or treated as the writer binding"
    );
}

#[tokio::test]
async fn missing_worktree_failure_isolated_and_blocks_the_writer_action() {
    let fixture = GitWorktreeFixture::new();
    let caller_config = fixture.authorized_config().await;
    let writer_a = bind_slot(&caller_config, &fixture.writer_a);
    let writer_b = bind_slot(&caller_config, &fixture.writer_b);
    let parked = fixture
        .writer_a
        .parent()
        .expect("fixture parent")
        .join("writer-a-missing");
    fs::rename(&fixture.writer_a, &parked).expect("park task-owned writer A worktree");

    let failed_action = action(&fixture.writer_a, "must-not-run\n", "writer-output.txt");
    let error = writer_a
        .runtime
        .run(&failed_action)
        .expect_err("missing binding must fail before the action");
    assert_eq!(error.failure, BindingFailure::WorktreeMissing);
    assert!(error.detail.contains("unavailable"));
    assert!(!fixture.writer_a.join("writer-output.txt").exists());

    let unaffected = writer_b
        .runtime
        .run(&action(
            &fixture.writer_b,
            "writer-b\n",
            "writer-output.txt",
        ))
        .expect("writer B remains usable");
    assert_eq!(unaffected.effective_cwd, fixture.writer_b);
}

#[tokio::test]
async fn repository_permission_and_execution_context_mismatches_fail_closed() {
    let fixture = GitWorktreeFixture::new();
    let caller_config = fixture.authorized_config().await;
    let runtime = bind_runtime(&caller_config, &fixture.writer_a);
    let writer_b = bind_slot(&caller_config, &fixture.writer_b);
    let parked = fixture
        .writer_a
        .parent()
        .expect("fixture parent")
        .join("writer-a-original");
    fs::rename(&fixture.writer_a, &parked).expect("park original linked worktree");
    fs::create_dir(&fixture.writer_a).expect("create imposter repository directory");
    run_git(&fixture.writer_a, &["init", "-q", "-b", "imposter"]);

    let repository_error = runtime
        .run(&action(
            &fixture.writer_a,
            "must-not-run\n",
            "writer-output.txt",
        ))
        .expect_err("same path backed by another repository must fail");
    assert_eq!(repository_error.failure, BindingFailure::RepositoryMismatch);
    assert!(!fixture.writer_a.join("writer-output.txt").exists());
    assert_writer_usable(
        &writer_b,
        &fixture.writer_b,
        "after-repository-mismatch.txt",
    );

    let fresh_fixture = GitWorktreeFixture::new();
    let authorized = fresh_fixture.authorized_config().await;
    let runtime = bind_runtime(&authorized, &fresh_fixture.writer_a);
    let writer_b = bind_slot(&authorized, &fresh_fixture.writer_b);

    let unauthorized = fresh_fixture
        .primary
        .parent()
        .expect("fixture parent")
        .join("unauthorized-and-absent");
    let admission_error =
        BoundWriterRuntime::bind(&authorized, unauthorized, LOCAL_EXECUTION_ENVIRONMENT)
            .expect_err("authorization must reject before inspecting the absent target");
    assert_eq!(
        admission_error.failure,
        BindingFailure::WorkspaceRootsIncompatible
    );
    assert_writer_usable(
        &writer_b,
        &fresh_fixture.writer_b,
        "after-admission-mismatch.txt",
    );

    let parent_escape = runtime
        .run(&action(
            &fresh_fixture.writer_a,
            "must-not-run\n",
            "../writer-b/marker.txt",
        ))
        .expect_err("parent traversal must not escape the bound root");
    assert_eq!(
        parent_escape.failure,
        BindingFailure::ActionTargetOutsideBinding
    );
    let absolute_escape = runtime
        .run(&action(
            &fresh_fixture.writer_a,
            "must-not-run\n",
            fresh_fixture.writer_b.join("marker.txt"),
        ))
        .expect_err("absolute output must not escape the bound root");
    assert_eq!(
        absolute_escape.failure,
        BindingFailure::ActionTargetOutsideBinding
    );
    assert_eq!(
        fs::read_to_string(fresh_fixture.writer_b.join("marker.txt"))
            .expect("read untouched writer B marker"),
        "base\n"
    );

    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(
            &fresh_fixture.writer_b,
            fresh_fixture.writer_a.join("writer-b-link"),
        )
        .expect("create task-owned escape symlink");
        let symlink_escape = runtime
            .run(&action(
                &fresh_fixture.writer_a,
                "must-not-run\n",
                "writer-b-link/marker.txt",
            ))
            .expect_err("symlink traversal must not escape the bound root");
        assert_eq!(
            symlink_escape.failure,
            BindingFailure::ActionTargetOutsideBinding
        );
        assert_eq!(
            fs::read_to_string(fresh_fixture.writer_b.join("marker.txt"))
                .expect("read writer B marker after symlink rejection"),
            "base\n"
        );
    }

    let binding = WriterWorkspaceBinding::capture(
        fresh_fixture.writer_a.clone(),
        LOCAL_EXECUTION_ENVIRONMENT,
    )
    .expect("capture binding");
    let mut read_only = authorized.clone();
    read_only
        .permissions
        .set_permission_profile(PermissionProfile::read_only())
        .expect("read-only profile should be allowed in tests");
    let permission_error =
        BoundWriterRuntime::reload(binding.clone(), &read_only, LOCAL_EXECUTION_ENVIRONMENT)
            .expect_err("binding must not enlarge read-only permission");
    assert_eq!(
        permission_error.failure,
        BindingFailure::PermissionIncompatible
    );
    assert_writer_usable(
        &writer_b,
        &fresh_fixture.writer_b,
        "after-permission-mismatch.txt",
    );

    let context_error = BoundWriterRuntime::reload(binding, &authorized, "remote-w0")
        .expect_err("incompatible execution environment must fail");
    assert_eq!(
        context_error.failure,
        BindingFailure::ExecutionContextMismatch
    );
    assert_writer_usable(
        &writer_b,
        &fresh_fixture.writer_b,
        "after-execution-context-mismatch.txt",
    );

    let binding = WriterWorkspaceBinding::capture(
        fresh_fixture.writer_a.clone(),
        LOCAL_EXECUTION_ENVIRONMENT,
    )
    .expect("capture binding for root mismatch");
    let wrong_roots = caller_context_for(&authorized, &fresh_fixture.writer_b);
    let roots_error =
        BoundWriterRuntime::reload(binding, &wrong_roots, LOCAL_EXECUTION_ENVIRONMENT)
            .expect_err("writer A cannot inherit writer B workspace roots");
    assert_eq!(
        roots_error.failure,
        BindingFailure::WorkspaceRootsIncompatible
    );
    assert_writer_usable(
        &writer_b,
        &fresh_fixture.writer_b,
        "after-roots-mismatch.txt",
    );
}

#[tokio::test]
async fn replacement_is_transactional_and_natural_language_git_handoff_is_sufficient() {
    let fixture = GitWorktreeFixture::new();
    let caller_config = fixture.authorized_config().await;
    let mut slot = bind_slot(&caller_config, &fixture.writer_a);
    slot.runtime
        .run(&action(
            &fixture.writer_a,
            "writer-a change\n",
            "marker.txt",
        ))
        .expect("write tracked result in writer A");
    let old_binding = slot.runtime.binding.clone();

    let writer_a_only = caller_context_for(&caller_config, &fixture.writer_a);
    let failed_replacement = slot.replace(
        &writer_a_only,
        fixture.writer_b.clone(),
        LOCAL_EXECUTION_ENVIRONMENT,
    );
    assert_eq!(
        failed_replacement
            .expect_err("replacement context mismatch")
            .failure,
        BindingFailure::WorkspaceRootsIncompatible
    );
    assert_eq!(slot.runtime.binding, old_binding);

    slot.replace(
        &caller_config,
        fixture.writer_b.clone(),
        LOCAL_EXECUTION_ENVIRONMENT,
    )
    .expect("explicit replacement to writer B");
    slot.runtime
        .run(&action(
            &fixture.writer_b,
            "writer-b change\n",
            "marker.txt",
        ))
        .expect("write tracked result in replacement worktree");

    let handoff_note = format!(
        "Work remains in {}. Inspect git status --short, git diff, symbolic ref, and HEAD.",
        fixture.writer_a.display()
    );
    let old_facts = ObservedGitFacts::inspect(&fixture.writer_a)
        .expect("Git facts locate the unhanded-off writer A result");
    let new_facts = ObservedGitFacts::inspect(&fixture.writer_b)
        .expect("Git facts locate the replacement writer B result");
    assert!(handoff_note.contains(fixture.writer_a.as_path().to_str().expect("UTF-8 path")));
    assert_eq!(old_facts.branch, "writer-a");
    assert_eq!(new_facts.branch, "writer-b");
    assert!(old_facts.status.contains("M marker.txt"));
    assert!(new_facts.status.contains("M marker.txt"));
    assert!(old_facts.diff.contains("writer-a change"));
    assert!(new_facts.diff.contains("writer-b change"));
    assert_ne!(old_facts.head, new_facts.head);
}

fn action(
    intended_worktree: &AbsolutePathBuf,
    content: &'static str,
    relative_path: impl Into<PathBuf>,
) -> FakeWriterAction {
    FakeWriterAction {
        intended_worktree: intended_worktree.clone(),
        relative_path: relative_path.into(),
        content,
    }
}

fn assert_writer_usable(
    slot: &WriterSlot,
    worktree: &AbsolutePathBuf,
    relative_path: &'static str,
) {
    let observation = slot
        .runtime
        .run(&action(worktree, "writer remains usable\n", relative_path))
        .expect("unaffected writer remains usable");
    assert_eq!(observation.effective_cwd, *worktree);
    assert_eq!(observation.output_path, worktree.join(relative_path));
}

fn bind_runtime(config: &Config, worktree: &AbsolutePathBuf) -> BoundWriterRuntime {
    BoundWriterRuntime::bind(config, worktree.clone(), LOCAL_EXECUTION_ENVIRONMENT)
        .expect("bind writer runtime")
}

fn bind_slot(config: &Config, worktree: &AbsolutePathBuf) -> WriterSlot {
    WriterSlot {
        runtime: bind_runtime(config, worktree),
    }
}

fn caller_context_for(config: &Config, worktree: &AbsolutePathBuf) -> Config {
    let mut context = config.clone();
    context.cwd = worktree.clone();
    context.workspace_roots = vec![worktree.clone()];
    context
        .permissions
        .set_workspace_roots(context.workspace_roots.clone());
    context
}

fn commit_writer_identity(worktree: &AbsolutePathBuf, writer: &str) {
    fs::write(worktree.join("writer-id.txt"), format!("{writer}\n"))
        .expect("write writer identity");
    run_git(worktree, &["add", "writer-id.txt"]);
    run_git(
        worktree,
        &[
            "-c",
            "user.name=Plan 084",
            "-c",
            "user.email=plan084@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "writer identity",
        ],
    );
}

fn absolute(path: impl AsRef<Path>) -> AbsolutePathBuf {
    AbsolutePathBuf::try_from(path.as_ref().to_path_buf()).expect("fixture path should be absolute")
}

fn run_git(cwd: &AbsolutePathBuf, args: &[&str]) -> String {
    let output = Command::new("git")
        .args(args)
        .current_dir(cwd)
        .output()
        .unwrap_or_else(|error| panic!("run git {}: {error}", args.join(" ")));
    assert!(
        output.status.success(),
        "git {} failed in {}: {}",
        args.join(" "),
        cwd.display(),
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout)
        .expect("git output should be UTF-8")
        .trim()
        .to_string()
}
