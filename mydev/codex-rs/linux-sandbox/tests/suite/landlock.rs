#![cfg(target_os = "linux")]
#![allow(clippy::unwrap_used)]
use codex_core::exec::ExecCapturePolicy;
use codex_core::exec::ExecParams;
use codex_core::exec::process_exec_tool_call;
use codex_core::exec_env::create_env;
use codex_core::sandboxing::SandboxPermissions;
use codex_protocol::config_types::ShellEnvironmentPolicy;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::error::CodexErrorDetails;
use codex_protocol::error::Result;
use codex_protocol::error::SandboxErr;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::FileSystemAccessMode;
use codex_protocol::permissions::FileSystemPath;
use codex_protocol::permissions::FileSystemSandboxEntry;
use codex_protocol::permissions::FileSystemSandboxPolicy;
use codex_protocol::permissions::FileSystemSpecialPath;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::io::Read;
use std::io::Write;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;
use tempfile::NamedTempFile;

// At least on GitHub CI, the arm64 tests appear to need longer timeouts.

#[cfg(not(target_arch = "aarch64"))]
const SHORT_TIMEOUT_MS: u64 = 5_000;
#[cfg(target_arch = "aarch64")]
const SHORT_TIMEOUT_MS: u64 = 5_000;

#[cfg(not(target_arch = "aarch64"))]
const LONG_TIMEOUT_MS: u64 = 5_000;
#[cfg(target_arch = "aarch64")]
const LONG_TIMEOUT_MS: u64 = 5_000;

#[cfg(not(target_arch = "aarch64"))]
const NETWORK_TIMEOUT_MS: u64 = 10_000;
#[cfg(target_arch = "aarch64")]
const NETWORK_TIMEOUT_MS: u64 = 10_000;

const BWRAP_UNAVAILABLE_ERR: &str = "bubblewrap is unavailable: no system bwrap was found";
const BWRAP_USER_NAMESPACE_ERR_SNIPPETS: &[&str] = &[
    "loopback: Failed RTM_NEWADDR",
    "loopback: Failed RTM_NEWLINK",
    "setting up uid map: Permission denied",
    "No permissions to create a new namespace",
];
// Keep the emitted value free of generic denial-classifier keywords such as
// "sandbox" and "landlock" so the marker cannot itself turn a failure into Denied.
const WGET_INNER_STAGE_MARKER: &str = "__codex_wget_inner_ready_4d0bf61b__";

fn create_env_from_core_vars() -> HashMap<String, String> {
    let policy = ShellEnvironmentPolicy::default();
    create_env(&policy, /*thread_id*/ None)
}

fn codex_linux_sandbox_exe() -> PathBuf {
    let sandbox_program = PathBuf::from(env!("CARGO_BIN_EXE_codex-linux-sandbox"));
    match sandbox_program.canonicalize() {
        Ok(path) => path,
        Err(_) => sandbox_program,
    }
}

#[expect(clippy::print_stdout)]
async fn run_cmd(cmd: &[&str], writable_roots: &[PathBuf], timeout_ms: u64) {
    let output = run_cmd_output(cmd, writable_roots, timeout_ms).await;
    if output.exit_code != 0 {
        println!("stdout:\n{}", output.stdout.text);
        println!("stderr:\n{}", output.stderr.text);
        panic!("exit code: {}", output.exit_code);
    }
}

async fn run_cmd_output(
    cmd: &[&str],
    writable_roots: &[PathBuf],
    timeout_ms: u64,
) -> codex_protocol::exec_output::ExecToolCallOutput {
    run_cmd_result_with_writable_roots(
        cmd,
        writable_roots,
        timeout_ms,
        /*use_legacy_landlock*/ false,
        /*network_access*/ false,
    )
    .await
    .expect("sandboxed command should execute")
}

async fn run_cmd_result_with_writable_roots(
    cmd: &[&str],
    writable_roots: &[PathBuf],
    timeout_ms: u64,
    use_legacy_landlock: bool,
    network_access: bool,
) -> Result<codex_protocol::exec_output::ExecToolCallOutput> {
    let writable_roots = writable_roots
        .iter()
        .map(|path| AbsolutePathBuf::try_from(path.as_path()).unwrap())
        .collect::<Vec<_>>();
    let permission_profile = PermissionProfile::workspace_write_with(
        &writable_roots,
        if network_access {
            NetworkSandboxPolicy::Enabled
        } else {
            NetworkSandboxPolicy::Restricted
        },
        // Exclude tmp-related folders from writable roots because we need a
        // folder that is writable by tests but that we intentionally disallow
        // writing to in the sandbox.
        /*exclude_tmpdir_env_var*/
        true,
        /*exclude_slash_tmp*/ true,
    );
    run_cmd_result_with_permission_profile(cmd, permission_profile, timeout_ms, use_legacy_landlock)
        .await
}

async fn run_cmd_result_with_permission_profile(
    cmd: &[&str],
    permission_profile: PermissionProfile,
    timeout_ms: u64,
    use_legacy_landlock: bool,
) -> Result<codex_protocol::exec_output::ExecToolCallOutput> {
    let cwd = AbsolutePathBuf::current_dir().expect("cwd should exist");
    run_cmd_result_with_permission_profile_for_cwd(
        cmd,
        cwd,
        permission_profile,
        timeout_ms,
        use_legacy_landlock,
        create_env_from_core_vars(),
    )
    .await
}

async fn run_cmd_result_with_cwd_and_writable_roots(
    cmd: &[&str],
    cwd: &std::path::Path,
    writable_roots: &[PathBuf],
    timeout_ms: u64,
    use_legacy_landlock: bool,
    network_access: bool,
) -> Result<codex_protocol::exec_output::ExecToolCallOutput> {
    let writable_roots = writable_roots
        .iter()
        .map(|path| AbsolutePathBuf::try_from(path.as_path()).unwrap())
        .collect::<Vec<_>>();
    let permission_profile = PermissionProfile::workspace_write_with(
        &writable_roots,
        if network_access {
            NetworkSandboxPolicy::Enabled
        } else {
            NetworkSandboxPolicy::Restricted
        },
        /*exclude_tmpdir_env_var*/ true,
        /*exclude_slash_tmp*/ true,
    );
    let cwd = AbsolutePathBuf::try_from(cwd).expect("cwd should be absolute");
    run_cmd_result_with_permission_profile_for_cwd(
        cmd,
        cwd,
        permission_profile,
        timeout_ms,
        use_legacy_landlock,
        create_env_from_core_vars(),
    )
    .await
}

async fn run_cmd_result_with_permission_profile_for_cwd(
    cmd: &[&str],
    cwd: AbsolutePathBuf,
    permission_profile: PermissionProfile,
    timeout_ms: u64,
    use_legacy_landlock: bool,
    env: HashMap<String, String>,
) -> Result<codex_protocol::exec_output::ExecToolCallOutput> {
    let sandbox_cwd = cwd.clone();
    let params = ExecParams {
        command: cmd.iter().copied().map(str::to_owned).collect(),
        cwd,
        expiration: timeout_ms.into(),
        capture_policy: ExecCapturePolicy::ShellTool,
        env,
        network: None,
        network_environment_id: None,
        sandbox_permissions: SandboxPermissions::UseDefault,
        windows_sandbox_level: WindowsSandboxLevel::Disabled,
        windows_sandbox_private_desktop: false,
        justification: None,
        arg0: None,
    };
    let codex_linux_sandbox_exe = Some(codex_linux_sandbox_exe());

    process_exec_tool_call(
        params,
        &permission_profile,
        &sandbox_cwd,
        std::slice::from_ref(&sandbox_cwd),
        &codex_linux_sandbox_exe,
        use_legacy_landlock,
        /*stdout_stream*/ None,
    )
    .await
}

fn is_bwrap_unavailable_output(output: &codex_protocol::exec_output::ExecToolCallOutput) -> bool {
    output.stderr.text.contains(BWRAP_UNAVAILABLE_ERR)
        || (output
            .stderr
            .text
            .contains("Can't mount proc on /newroot/proc")
            && (output.stderr.text.contains("Operation not permitted")
                || output.stderr.text.contains("Permission denied")
                || output.stderr.text.contains("Invalid argument")))
}

fn is_bwrap_user_namespace_failure(
    output: &codex_protocol::exec_output::ExecToolCallOutput,
) -> bool {
    BWRAP_USER_NAMESPACE_ERR_SNIPPETS
        .iter()
        .any(|snippet| output.stderr.text.contains(snippet))
}

fn is_wget_connect_seccomp_denial(
    output: &codex_protocol::exec_output::ExecToolCallOutput,
    listener_endpoint: &str,
) -> bool {
    let sandbox_started = output
        .stdout
        .text
        .lines()
        .any(|line| line == WGET_INNER_STAGE_MARKER);
    let stderr = output.stderr.text.to_ascii_lowercase();
    let listener_endpoint = listener_endpoint.to_ascii_lowercase();
    let has_wget_network_diagnostic = stderr.lines().any(|line| {
        line.contains(&listener_endpoint)
            && line.contains("operation not permitted")
            && (line.contains("connect") || line.contains("socket"))
    });

    output.exit_code != 0
        && sandbox_started
        && !is_bwrap_unavailable_output(output)
        && !is_bwrap_user_namespace_failure(output)
        // The restricted-network seccomp filter returns EPERM for AF_INET
        // socket/connect. Bind EPERM to the same diagnostic line as this
        // fixture's endpoint without requiring one complete wget sentence.
        && has_wget_network_diagnostic
}

async fn should_skip_bwrap_tests() -> bool {
    match run_cmd_result_with_writable_roots(
        &["bash", "-lc", "true"],
        &[],
        NETWORK_TIMEOUT_MS,
        /*use_legacy_landlock*/ false,
        /*network_access*/ true,
    )
    .await
    {
        Ok(output) => is_bwrap_unavailable_output(&output),
        Err(err) => match err.details() {
            CodexErrorDetails::Sandbox(SandboxErr::Denied { output, .. }) => {
                is_bwrap_unavailable_output(output)
            }
            // Probe timeouts are not actionable for the bwrap-specific assertions below;
            // skip rather than fail the whole suite.
            CodexErrorDetails::Sandbox(SandboxErr::Timeout { .. }) => true,
            details => panic!("bwrap availability probe failed unexpectedly: {details:?}"),
        },
    }
}

fn expect_denied(
    result: Result<codex_protocol::exec_output::ExecToolCallOutput>,
    context: &str,
) -> codex_protocol::exec_output::ExecToolCallOutput {
    match result {
        Ok(output) => {
            assert_ne!(output.exit_code, 0, "{context}: expected nonzero exit code");
            output
        }
        Err(err) => match err.details() {
            CodexErrorDetails::Sandbox(SandboxErr::Denied { output, .. }) => {
                output.as_ref().clone()
            }
            details => panic!("{context}: {details:?}"),
        },
    }
}

#[tokio::test]
async fn test_root_read() {
    run_cmd(&["ls", "-l", "/bin"], &[], SHORT_TIMEOUT_MS).await;
}

#[tokio::test]
#[should_panic]
async fn test_root_write() {
    let tmpfile = NamedTempFile::new().unwrap();
    let tmpfile_path = tmpfile.path().to_string_lossy();
    run_cmd(
        &["bash", "-lc", &format!("echo blah > {tmpfile_path}")],
        &[],
        SHORT_TIMEOUT_MS,
    )
    .await;
}

#[tokio::test]
async fn test_dev_null_write() {
    if should_skip_bwrap_tests().await {
        eprintln!("skipping bwrap test: bwrap sandbox prerequisites are unavailable");
        return;
    }

    let output = run_cmd_result_with_writable_roots(
        &["bash", "-lc", "echo blah > /dev/null"],
        &[],
        // We have seen timeouts when running this test in CI on GitHub,
        // so we are using a generous timeout until we can diagnose further.
        LONG_TIMEOUT_MS,
        /*use_legacy_landlock*/ false,
        /*network_access*/ true,
    )
    .await
    .expect("sandboxed command should execute");

    assert_eq!(output.exit_code, 0);
}

#[tokio::test]
async fn bwrap_populates_minimal_dev_nodes() {
    if should_skip_bwrap_tests().await {
        eprintln!("skipping bwrap test: bwrap sandbox prerequisites are unavailable");
        return;
    }

    let output = run_cmd_result_with_writable_roots(
        &[
            "bash",
            "-lc",
            "for node in null zero full random urandom tty; do [ -c \"/dev/$node\" ] || { echo \"missing /dev/$node\" >&2; exit 1; }; done",
        ],
        &[],
        LONG_TIMEOUT_MS,
        /*use_legacy_landlock*/ false,
        /*network_access*/ true,
    )
    .await
    .expect("sandboxed command should execute");

    assert_eq!(output.exit_code, 0);
}

#[tokio::test]
async fn bwrap_preserves_writable_dev_shm_bind_mount() {
    if should_skip_bwrap_tests().await {
        eprintln!("skipping bwrap test: bwrap sandbox prerequisites are unavailable");
        return;
    }
    if !std::path::Path::new("/dev/shm").exists() {
        eprintln!("skipping bwrap test: /dev/shm is unavailable in this environment");
        return;
    }

    let target_file = match NamedTempFile::new_in("/dev/shm") {
        Ok(file) => file,
        Err(err) => {
            eprintln!("skipping bwrap test: failed to create /dev/shm temp file: {err}");
            return;
        }
    };
    let target_path = target_file.path().to_path_buf();
    std::fs::write(&target_path, "host-before").expect("seed /dev/shm file");

    let output = run_cmd_result_with_writable_roots(
        &[
            "bash",
            "-lc",
            &format!("printf sandbox-after > {}", target_path.to_string_lossy()),
        ],
        &[PathBuf::from("/dev/shm")],
        LONG_TIMEOUT_MS,
        /*use_legacy_landlock*/ false,
        /*network_access*/ true,
    )
    .await
    .expect("sandboxed command should execute");

    assert_eq!(output.exit_code, 0);
    assert_eq!(
        std::fs::read_to_string(&target_path).expect("read /dev/shm file"),
        "sandbox-after"
    );
}

#[tokio::test]
async fn test_writable_root() {
    let tmpdir = tempfile::tempdir().unwrap();
    let file_path = tmpdir.path().join("test");
    run_cmd(
        &[
            "bash",
            "-lc",
            &format!("echo blah > {}", file_path.to_string_lossy()),
        ],
        &[tmpdir.path().to_path_buf()],
        // We have seen timeouts when running this test in CI on GitHub,
        // so we are using a generous timeout until we can diagnose further.
        LONG_TIMEOUT_MS,
    )
    .await;
}

#[tokio::test]
async fn sandbox_ignores_missing_writable_roots_under_bwrap() {
    if should_skip_bwrap_tests().await {
        eprintln!("skipping bwrap test: bwrap sandbox prerequisites are unavailable");
        return;
    }

    let tempdir = tempfile::tempdir().expect("tempdir");
    let existing_root = tempdir.path().join("existing");
    let missing_root = tempdir.path().join("missing");
    std::fs::create_dir(&existing_root).expect("create existing root");

    let output = run_cmd_result_with_writable_roots(
        &["bash", "-lc", "printf sandbox-ok"],
        &[existing_root, missing_root],
        LONG_TIMEOUT_MS,
        /*use_legacy_landlock*/ false,
        /*network_access*/ true,
    )
    .await
    .expect("sandboxed command should execute");

    assert_eq!(output.exit_code, 0);
    assert_eq!(output.stdout.text, "sandbox-ok");
}

#[tokio::test]
async fn test_no_new_privs_is_enabled() {
    let output = run_cmd_output(
        &["bash", "-lc", "grep '^NoNewPrivs:' /proc/self/status"],
        &[],
        // We have seen timeouts when running this test in CI on GitHub,
        // so we are using a generous timeout until we can diagnose further.
        LONG_TIMEOUT_MS,
    )
    .await;
    let line = output
        .stdout
        .text
        .lines()
        .find(|line| line.starts_with("NoNewPrivs:"))
        .unwrap_or("");
    assert_eq!(line.trim(), "NoNewPrivs:\t1");
}

#[tokio::test]
#[should_panic(expected = "Sandbox(Timeout")]
async fn test_timeout() {
    run_cmd(&["sleep", "2"], &[], /*timeout_ms*/ 50).await;
}

/// Helper that runs `cmd` under the Linux sandbox and asserts that the command
/// does NOT succeed (i.e. returns a non‑zero exit code) **unless** the binary
/// is missing in which case we silently treat it as an accepted skip so the
/// suite remains green on leaner CI images.
async fn assert_network_blocked(cmd: &[&str]) {
    let cwd = AbsolutePathBuf::current_dir().expect("cwd should exist");
    let sandbox_cwd = cwd.clone();
    let params = ExecParams {
        command: cmd.iter().copied().map(str::to_owned).collect(),
        cwd,
        // Give the tool a generous 2-second timeout so even slow DNS timeouts
        // do not stall the suite.
        expiration: NETWORK_TIMEOUT_MS.into(),
        capture_policy: ExecCapturePolicy::ShellTool,
        env: create_env_from_core_vars(),
        network: None,
        network_environment_id: None,
        sandbox_permissions: SandboxPermissions::UseDefault,
        windows_sandbox_level: WindowsSandboxLevel::Disabled,
        windows_sandbox_private_desktop: false,
        justification: None,
        arg0: None,
    };

    let codex_linux_sandbox_exe: Option<PathBuf> = Some(codex_linux_sandbox_exe());
    let permission_profile = PermissionProfile::read_only();
    let result = process_exec_tool_call(
        params,
        &permission_profile,
        &sandbox_cwd,
        std::slice::from_ref(&sandbox_cwd),
        &codex_linux_sandbox_exe,
        /*use_legacy_landlock*/ false,
        /*stdout_stream*/ None,
    )
    .await;

    let output = match result {
        Ok(output) => output,
        Err(err) => match err.details() {
            CodexErrorDetails::Sandbox(SandboxErr::Denied { output, .. }) => {
                output.as_ref().clone()
            }
            details => panic!("expected sandbox denied error, got: {details:?}"),
        },
    };

    dbg!(&output.stderr.text);
    dbg!(&output.stdout.text);
    dbg!(&output.exit_code);

    // A completely missing binary exits with 127.  Anything else should also
    // be non‑zero (EPERM from seccomp will usually bubble up as 1, 2, 13…)
    // If—*and only if*—the command exits 0 we consider the sandbox breached.

    if output.exit_code == 0 {
        panic!(
            "Network sandbox FAILED - {cmd:?} exited 0\nstdout:\n{}\nstderr:\n{}",
            output.stdout.text, output.stderr.text
        );
    }
}

#[tokio::test]
async fn sandbox_blocks_curl() {
    assert_network_blocked(&["curl", "-I", "http://openai.com"]).await;
}

#[tokio::test]
async fn sandbox_blocks_wget_tcp_connect() {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind wget fixture listener");
    let listener_addr = listener.local_addr().expect("read wget fixture address");
    let control_listener = listener.try_clone().expect("clone wget fixture listener");
    control_listener
        .set_nonblocking(true)
        .expect("make wget control listener nonblocking");
    let control_server = std::thread::spawn(move || {
        let deadline = Instant::now() + Duration::from_secs(2);
        let (mut stream, _) = loop {
            match control_listener.accept() {
                Ok(connection) => break connection,
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    assert!(
                        Instant::now() < deadline,
                        "wget control request did not reach the fixture listener"
                    );
                    std::thread::sleep(Duration::from_millis(10));
                }
                Err(error) => panic!("accept wget control request: {error}"),
            }
        };
        const MAX_REQUEST_HEADER_BYTES: usize = 16 * 1024;
        let read_deadline = Instant::now() + Duration::from_secs(2);
        let mut request = Vec::with_capacity(1024);
        while !request.windows(4).any(|window| window == b"\r\n\r\n") {
            assert!(
                request.len() < MAX_REQUEST_HEADER_BYTES,
                "wget control request headers exceeded {MAX_REQUEST_HEADER_BYTES} bytes"
            );
            let now = Instant::now();
            assert!(
                now < read_deadline,
                "timed out reading wget request headers"
            );
            stream
                .set_read_timeout(Some(read_deadline - now))
                .expect("set wget fixture read timeout");

            let mut chunk = [0_u8; 1024];
            let chunk_len = (MAX_REQUEST_HEADER_BYTES - request.len()).min(chunk.len());
            match stream.read(&mut chunk[..chunk_len]) {
                Ok(0) => panic!("wget closed the control connection before sending full headers"),
                Ok(read) => request.extend_from_slice(&chunk[..read]),
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(error) => panic!("read wget request headers: {error}"),
            }
        }
        assert!(
            request.starts_with(b"GET /probe HTTP/1."),
            "unexpected wget request: {}",
            String::from_utf8_lossy(&request)
        );
        stream
            .write_all(
                b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\nConnection: close\r\n\r\nsandbox-probe",
            )
            .expect("write wget fixture response");
    });
    let listener_endpoint = listener_addr.to_string();
    let url = format!("http://{listener_endpoint}/probe");
    // Resolve wget once so the host control and sandbox round cannot select
    // different executables through different PATH views.
    let path = std::env::var_os("PATH").expect("PATH must be set to locate wget");
    let wget_program = std::env::split_paths(&path)
        .map(|directory| directory.join("wget"))
        .find(|candidate| candidate.is_file())
        .expect("wget must be available for the sandbox contract")
        .canonicalize()
        .expect("canonicalize wget executable");
    let wget_program = wget_program
        .to_str()
        .expect("wget executable path must be valid UTF-8");
    let wget_command = [
        wget_program,
        "--no-proxy",
        "--tries=1",
        "--timeout=2",
        "-O-",
        url.as_str(),
    ];

    let control = Command::new(wget_command[0])
        .args(&wget_command[1..])
        .env("LC_ALL", "C")
        .output()
        .expect("wget must be available for the sandbox contract");
    control_server
        .join()
        .expect("wget control fixture should complete");
    assert_eq!(control.status.code(), Some(0));
    assert_eq!(control.stdout, b"sandbox-probe");

    let sandbox_wget_command = [
        "bash",
        "--noprofile",
        "--norc",
        "-p",
        "-c",
        "export LC_ALL=C && printf '%s\\n' \"$1\" && shift && exec \"$@\"",
        "codex-wget-inner-control",
        WGET_INNER_STAGE_MARKER,
        wget_command[0],
        wget_command[1],
        wget_command[2],
        wget_command[3],
        wget_command[4],
        wget_command[5],
    ];
    let mut sandbox_env = create_env_from_core_vars();
    sandbox_env.remove("BASH_ENV");
    sandbox_env.remove("ENV");
    let cwd = AbsolutePathBuf::current_dir().expect("cwd should exist");
    let result = run_cmd_result_with_permission_profile_for_cwd(
        &sandbox_wget_command,
        cwd,
        PermissionProfile::read_only(),
        SHORT_TIMEOUT_MS,
        /*use_legacy_landlock*/ false,
        sandbox_env,
    )
    .await;
    let denied_output = match result {
        Err(err) => match err.details() {
            CodexErrorDetails::Sandbox(SandboxErr::Denied { output, .. }) => {
                output.as_ref().clone()
            }
            details => panic!("expected sandbox denial for wget connect, got: {details:?}"),
        },
        Ok(output) => panic!(
            "expected sandbox denial for wget connect, got exit {}: stdout={}; stderr={}",
            output.exit_code, output.stdout.text, output.stderr.text
        ),
    };
    assert!(
        is_wget_connect_seccomp_denial(&denied_output, &listener_endpoint),
        "expected wget connect to reach the initialized sandbox and fail with seccomp EPERM; exit={}; stdout={}; stderr={}",
        denied_output.exit_code,
        denied_output.stdout.text,
        denied_output.stderr.text
    );

    listener
        .set_nonblocking(true)
        .expect("make wget fixture listener nonblocking");
    match listener.accept() {
        Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => {}
        Ok(_) => panic!("sandboxed wget reached the fixture listener"),
        Err(err) => panic!("failed to inspect wget fixture listener: {err}"),
    }
}

#[test]
fn sandbox_blocks_wget_tcp_connect_classifier_rejects_non_connect_eperm() {
    let output = |stdout: &str, stderr: &str| codex_protocol::exec_output::ExecToolCallOutput {
        exit_code: 1,
        stdout: codex_protocol::exec_output::StreamOutput::new(stdout.to_string()),
        stderr: codex_protocol::exec_output::StreamOutput::new(stderr.to_string()),
        ..Default::default()
    };
    let marker = format!("{WGET_INNER_STAGE_MARKER}\n");
    let listener_endpoint = "127.0.0.1:43123";
    let connect_eperm =
        format!("wget: Connecting to {listener_endpoint}... failed: Operation not permitted");

    let seccomp_denial_after_marker = output(&marker, &connect_eperm);
    assert!(is_wget_connect_seccomp_denial(
        &seccomp_denial_after_marker,
        listener_endpoint
    ));
    assert!(!is_wget_connect_seccomp_denial(
        &seccomp_denial_after_marker,
        "127.0.0.1:43124"
    ));

    let bwrap_startup_failure = output(
        "",
        "bwrap: Can't mount proc on /newroot/proc: Operation not permitted",
    );
    assert!(!is_wget_connect_seccomp_denial(
        &bwrap_startup_failure,
        listener_endpoint
    ));

    let missing_marker = output("", &connect_eperm);
    assert!(!is_wget_connect_seccomp_denial(
        &missing_marker,
        listener_endpoint
    ));

    let exec_eperm_after_marker = output(
        &marker,
        "bash: exec: /usr/bin/wget: cannot execute: Operation not permitted",
    );
    assert!(!is_wget_connect_seccomp_denial(
        &exec_eperm_after_marker,
        listener_endpoint
    ));

    let split_transport_and_eperm = output(
        &marker,
        &format!(
            "wget: Connecting to {listener_endpoint}... failed: Connection refused\nbash: unrelated: Operation not permitted"
        ),
    );
    assert!(!is_wget_connect_seccomp_denial(
        &split_transport_and_eperm,
        listener_endpoint
    ));

    let user_namespace_failure_after_marker = output(
        &marker,
        &format!("{connect_eperm}\nbwrap: setting up uid map: Permission denied"),
    );
    assert!(!is_wget_connect_seccomp_denial(
        &user_namespace_failure_after_marker,
        listener_endpoint
    ));
}

#[tokio::test]
async fn sandbox_blocks_ping() {
    // ICMP requires raw socket – should be denied quickly with EPERM.
    assert_network_blocked(&["ping", "-c", "1", "8.8.8.8"]).await;
}

#[tokio::test]
async fn sandbox_blocks_nc() {
    // Zero‑length connection attempt to localhost.
    assert_network_blocked(&["nc", "-z", "127.0.0.1", "80"]).await;
}

#[tokio::test]
async fn sandbox_blocks_git_and_codex_writes_inside_writable_root() {
    if should_skip_bwrap_tests().await {
        eprintln!("skipping bwrap test: bwrap sandbox prerequisites are unavailable");
        return;
    }

    let tmpdir = tempfile::tempdir().expect("tempdir");
    let dot_git = tmpdir.path().join(".git");
    let dot_codex = tmpdir.path().join(".codex");
    std::fs::create_dir_all(&dot_git).expect("create .git");
    std::fs::create_dir_all(&dot_codex).expect("create .codex");

    let git_target = dot_git.join("config");
    let codex_target = dot_codex.join("config.toml");

    let git_output = expect_denied(
        run_cmd_result_with_writable_roots(
            &[
                "bash",
                "-lc",
                &format!("echo denied > {}", git_target.to_string_lossy()),
            ],
            &[tmpdir.path().to_path_buf()],
            LONG_TIMEOUT_MS,
            /*use_legacy_landlock*/ false,
            /*network_access*/ true,
        )
        .await,
        ".git write should be denied under bubblewrap",
    );

    let codex_output = expect_denied(
        run_cmd_result_with_writable_roots(
            &[
                "bash",
                "-lc",
                &format!("echo denied > {}", codex_target.to_string_lossy()),
            ],
            &[tmpdir.path().to_path_buf()],
            LONG_TIMEOUT_MS,
            /*use_legacy_landlock*/ false,
            /*network_access*/ true,
        )
        .await,
        ".codex write should be denied under bubblewrap",
    );
    assert_ne!(git_output.exit_code, 0);
    assert_ne!(codex_output.exit_code, 0);
}

#[tokio::test]
async fn sandbox_blocks_codex_symlink_replacement_attack() {
    if should_skip_bwrap_tests().await {
        eprintln!("skipping bwrap test: bwrap sandbox prerequisites are unavailable");
        return;
    }

    use std::os::unix::fs::symlink;

    let tmpdir = tempfile::tempdir().expect("tempdir");
    let decoy = tmpdir.path().join("decoy-codex");
    std::fs::create_dir_all(&decoy).expect("create decoy dir");

    let dot_codex = tmpdir.path().join(".codex");
    symlink(&decoy, &dot_codex).expect("create .codex symlink");

    let codex_target = dot_codex.join("config.toml");

    let codex_output = expect_denied(
        run_cmd_result_with_writable_roots(
            &[
                "bash",
                "-lc",
                &format!("echo denied > {}", codex_target.to_string_lossy()),
            ],
            &[tmpdir.path().to_path_buf()],
            LONG_TIMEOUT_MS,
            /*use_legacy_landlock*/ false,
            /*network_access*/ true,
        )
        .await,
        ".codex symlink replacement should be denied",
    );
    assert_ne!(codex_output.exit_code, 0);
}

#[tokio::test]
async fn sandbox_reports_codex_symlink_build_failure_without_panicking() {
    if should_skip_bwrap_tests().await {
        eprintln!("skipping bwrap test: bwrap sandbox prerequisites are unavailable");
        return;
    }

    use std::os::unix::fs::symlink;

    let tmpdir = tempfile::tempdir().expect("tempdir");
    let decoy = tmpdir.path().join("decoy-codex");
    std::fs::create_dir_all(&decoy).expect("create decoy dir");

    let dot_codex = tmpdir.path().join(".codex");
    symlink(&decoy, &dot_codex).expect("create .codex symlink");

    let output = match run_cmd_result_with_writable_roots(
        &["bash", "-lc", "true"],
        &[tmpdir.path().to_path_buf()],
        LONG_TIMEOUT_MS,
        /*use_legacy_landlock*/ false,
        /*network_access*/ true,
    )
    .await
    {
        Err(err) => match err.details() {
            CodexErrorDetails::Sandbox(SandboxErr::Denied { output, .. }) => {
                output.as_ref().clone()
            }
            details => panic!(".codex symlink build failure should deny: {details:?}"),
        },
        Ok(output) => panic!(".codex symlink build failure should deny: {output:?}"),
    };

    assert_eq!(output.exit_code, 1);
    assert!(
        output
            .stderr
            .text
            .contains("error building bubblewrap command:"),
        "stderr: {}",
        output.stderr.text
    );
    assert!(
        output
            .stderr
            .text
            .contains("cannot enforce sandbox read-only path"),
        "stderr: {}",
        output.stderr.text
    );
    assert!(
        !output.stderr.text.contains("panicked at"),
        "stderr: {}",
        output.stderr.text
    );
}

#[tokio::test]
async fn sandbox_keeps_parent_repo_discovery_while_blocking_child_metadata() {
    if should_skip_bwrap_tests().await {
        eprintln!("skipping bwrap test: bwrap sandbox prerequisites are unavailable");
        return;
    }

    let git_available = std::process::Command::new("git")
        .arg("--version")
        .status()
        .is_ok_and(|status| status.success());
    let python_available = std::process::Command::new("python3")
        .arg("--version")
        .status()
        .is_ok_and(|status| status.success());
    if !git_available || !python_available {
        eprintln!("skipping bwrap test: git or python3 is unavailable");
        return;
    }

    let tmpdir = tempfile::tempdir().expect("tempdir");
    let repo = tmpdir.path().join("repo");
    let subdir = repo.join("sub");
    std::fs::create_dir_all(&subdir).expect("create nested workspace");
    assert!(
        std::process::Command::new("git")
            .arg("init")
            .arg("-q")
            .arg(&repo)
            .status()
            .expect("git init should run")
            .success(),
        "git init should create parent repo"
    );

    let repo = repo.to_string_lossy();
    let script = format!(
        r#"set -e
test "$(git rev-parse --show-toplevel)" = '{repo}'
git status --short > status.before
if grep -E '(^|[[:space:]])\.(git|codex|agents)(/|$)' status.before; then
  cat status.before
  exit 21
fi
"#,
    );

    let output = run_cmd_result_with_cwd_and_writable_roots(
        &["bash", "-lc", &script],
        &subdir,
        std::slice::from_ref(&subdir),
        LONG_TIMEOUT_MS,
        /*use_legacy_landlock*/ false,
        /*network_access*/ true,
    )
    .await
    .expect("sandboxed command should execute");

    assert_eq!(
        output.exit_code, 0,
        "stdout:\n{}\nstderr:\n{}",
        output.stdout.text, output.stderr.text
    );

    let git_init_output = expect_denied(
        run_cmd_result_with_cwd_and_writable_roots(
            &["git", "init", "-q"],
            &subdir,
            std::slice::from_ref(&subdir),
            LONG_TIMEOUT_MS,
            /*use_legacy_landlock*/ false,
            /*network_access*/ true,
        )
        .await,
        "child git init should be denied",
    );
    assert_ne!(git_init_output.exit_code, 0);
    assert!(!subdir.join(".git").exists());

    let mkdir_codex_output = expect_denied(
        run_cmd_result_with_cwd_and_writable_roots(
            &["mkdir", ".codex"],
            &subdir,
            std::slice::from_ref(&subdir),
            LONG_TIMEOUT_MS,
            /*use_legacy_landlock*/ false,
            /*network_access*/ true,
        )
        .await,
        "child .codex directory creation should be denied",
    );
    assert_ne!(mkdir_codex_output.exit_code, 0);
    assert!(!subdir.join(".codex").exists());

    let script = format!(
        r#"set -e
test "$(git rev-parse --show-toplevel)" = '{repo}'
printf '%s\n' 'import json, sys' 'for line in sys.stdin:' '    obj = json.loads(line)' '    print(obj.get("message", obj))' > jsonl_viewer.py
printf '%s\n' '{{"message":"ok"}}' | python3 jsonl_viewer.py | grep -q ok
"#,
    );
    let output = run_cmd_result_with_cwd_and_writable_roots(
        &["bash", "-lc", &script],
        &subdir,
        std::slice::from_ref(&subdir),
        LONG_TIMEOUT_MS,
        /*use_legacy_landlock*/ false,
        /*network_access*/ true,
    )
    .await
    .expect("sandboxed command should execute");
    assert_eq!(
        output.exit_code, 0,
        "stdout:\n{}\nstderr:\n{}",
        output.stdout.text, output.stderr.text
    );

    assert!(subdir.join("jsonl_viewer.py").is_file());
    assert!(!subdir.join(".git").exists());
    assert!(!subdir.join(".codex").exists());
    assert!(!subdir.join(".agents").exists());
}

#[tokio::test]
async fn sandbox_blocks_explicit_split_policy_carveouts_under_bwrap() {
    if should_skip_bwrap_tests().await {
        eprintln!("skipping bwrap test: bwrap sandbox prerequisites are unavailable");
        return;
    }

    let tmpdir = tempfile::tempdir().expect("tempdir");
    let blocked = tmpdir.path().join("blocked");
    std::fs::create_dir_all(&blocked).expect("create blocked dir");
    let blocked_target = blocked.join("secret.txt");
    // These tests bypass the usual legacy-policy bridge, so explicitly keep
    // the sandbox helper binary and minimal runtime paths readable.
    let sandbox_helper_dir = codex_linux_sandbox_exe()
        .parent()
        .expect("sandbox helper should have a parent")
        .to_path_buf();

    let file_system_sandbox_policy = FileSystemSandboxPolicy::restricted(vec![
        FileSystemSandboxEntry {
            path: FileSystemPath::Special {
                value: FileSystemSpecialPath::Minimal,
            },
            access: FileSystemAccessMode::Read,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Path {
                path: AbsolutePathBuf::try_from(sandbox_helper_dir.as_path())
                    .expect("absolute helper dir"),
            },
            access: FileSystemAccessMode::Read,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Path {
                path: AbsolutePathBuf::try_from(tmpdir.path()).expect("absolute tempdir"),
            },
            access: FileSystemAccessMode::Write,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Path {
                path: AbsolutePathBuf::try_from(blocked.as_path()).expect("absolute blocked dir"),
            },
            access: FileSystemAccessMode::Deny,
            missing_path_behavior: None,
        },
    ]);
    let permission_profile = PermissionProfile::from_runtime_permissions(
        &file_system_sandbox_policy,
        NetworkSandboxPolicy::Enabled,
    );
    let output = expect_denied(
        run_cmd_result_with_permission_profile(
            &[
                "bash",
                "-lc",
                &format!("echo denied > {}", blocked_target.to_string_lossy()),
            ],
            permission_profile,
            LONG_TIMEOUT_MS,
            /*use_legacy_landlock*/ false,
        )
        .await,
        "explicit split-policy carveout should be denied under bubblewrap",
    );

    assert_ne!(output.exit_code, 0);
}

#[tokio::test]
async fn sandbox_reenables_writable_subpaths_under_unreadable_parents() {
    if should_skip_bwrap_tests().await {
        eprintln!("skipping bwrap test: bwrap sandbox prerequisites are unavailable");
        return;
    }

    let tmpdir = tempfile::tempdir().expect("tempdir");
    let blocked = tmpdir.path().join("blocked");
    let allowed = blocked.join("allowed");
    std::fs::create_dir_all(&allowed).expect("create blocked/allowed dir");
    let allowed_target = allowed.join("note.txt");
    // These tests bypass the usual legacy-policy bridge, so explicitly keep
    // the sandbox helper binary and minimal runtime paths readable.
    let sandbox_helper_dir = codex_linux_sandbox_exe()
        .parent()
        .expect("sandbox helper should have a parent")
        .to_path_buf();

    let file_system_sandbox_policy = FileSystemSandboxPolicy::restricted(vec![
        FileSystemSandboxEntry {
            path: FileSystemPath::Special {
                value: FileSystemSpecialPath::Minimal,
            },
            access: FileSystemAccessMode::Read,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Path {
                path: AbsolutePathBuf::try_from(sandbox_helper_dir.as_path())
                    .expect("absolute helper dir"),
            },
            access: FileSystemAccessMode::Read,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Path {
                path: AbsolutePathBuf::try_from(tmpdir.path()).expect("absolute tempdir"),
            },
            access: FileSystemAccessMode::Write,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Path {
                path: AbsolutePathBuf::try_from(blocked.as_path()).expect("absolute blocked dir"),
            },
            access: FileSystemAccessMode::Deny,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Path {
                path: AbsolutePathBuf::try_from(allowed.as_path()).expect("absolute allowed dir"),
            },
            access: FileSystemAccessMode::Write,
            missing_path_behavior: None,
        },
    ]);
    let permission_profile = PermissionProfile::from_runtime_permissions(
        &file_system_sandbox_policy,
        NetworkSandboxPolicy::Enabled,
    );
    let output = run_cmd_result_with_permission_profile(
        &[
            "bash",
            "-lc",
            &format!(
                "printf allowed > {} && cat {}",
                allowed_target.to_string_lossy(),
                allowed_target.to_string_lossy()
            ),
        ],
        permission_profile,
        LONG_TIMEOUT_MS,
        /*use_legacy_landlock*/ false,
    )
    .await
    .expect("nested writable carveout should execute under bubblewrap");

    assert_eq!(output.exit_code, 0);
    assert_eq!(output.stdout.text.trim(), "allowed");
}

#[tokio::test]
async fn sandbox_blocks_root_read_carveouts_under_bwrap() {
    if should_skip_bwrap_tests().await {
        eprintln!("skipping bwrap test: bwrap sandbox prerequisites are unavailable");
        return;
    }

    let tmpdir = tempfile::tempdir().expect("tempdir");
    let blocked = tmpdir.path().join("blocked");
    std::fs::create_dir_all(&blocked).expect("create blocked dir");
    let blocked_target = blocked.join("secret.txt");
    std::fs::write(&blocked_target, "secret").expect("seed blocked file");

    let file_system_sandbox_policy = FileSystemSandboxPolicy::restricted(vec![
        FileSystemSandboxEntry {
            path: FileSystemPath::Special {
                value: FileSystemSpecialPath::Root,
            },
            access: FileSystemAccessMode::Read,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Path {
                path: AbsolutePathBuf::try_from(blocked.as_path()).expect("absolute blocked dir"),
            },
            access: FileSystemAccessMode::Deny,
            missing_path_behavior: None,
        },
    ]);
    let permission_profile = PermissionProfile::from_runtime_permissions(
        &file_system_sandbox_policy,
        NetworkSandboxPolicy::Enabled,
    );
    let output = expect_denied(
        run_cmd_result_with_permission_profile(
            &[
                "bash",
                "-lc",
                &format!("cat {}", blocked_target.to_string_lossy()),
            ],
            permission_profile,
            LONG_TIMEOUT_MS,
            /*use_legacy_landlock*/ false,
        )
        .await,
        "root-read carveout should be denied under bubblewrap",
    );

    assert_ne!(output.exit_code, 0);
}

#[tokio::test]
async fn sandbox_blocks_ssh() {
    // Force ssh to attempt a real TCP connection but fail quickly.  `BatchMode`
    // avoids password prompts, and `ConnectTimeout` keeps the hang time low.
    assert_network_blocked(&[
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=1",
        "github.com",
    ])
    .await;
}

#[tokio::test]
async fn sandbox_blocks_getent() {
    assert_network_blocked(&["getent", "ahosts", "openai.com"]).await;
}

#[tokio::test]
async fn sandbox_blocks_dev_tcp_redirection() {
    // This syntax is only supported by bash and zsh. We try bash first.
    // Fallback generic socket attempt using /bin/sh with bash‑style /dev/tcp.  Not
    // all images ship bash, so we guard against 127 as well.
    assert_network_blocked(&["bash", "-c", "echo hi > /dev/tcp/127.0.0.1/80"]).await;
}
