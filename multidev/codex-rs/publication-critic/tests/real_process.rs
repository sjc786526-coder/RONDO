#![cfg(target_os = "linux")]
#![allow(clippy::expect_used, clippy::unwrap_used)]

use codex_publication_critic::ActorRole;
use codex_publication_critic::ContinuityContext;
use codex_publication_critic::LocalScope;
use codex_publication_critic::PublicationCandidate;
use codex_publication_critic::PublicationPacket;
use codex_publication_critic::RuntimeLimits;
use codex_publication_critic::ServiceDescriptor;
use codex_publication_critic::StartupAnnouncement;
use codex_publication_critic::TargetKind;
use codex_publication_critic::controlled_test_descriptor;
use codex_utils_cargo_bin::cargo_bin;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::error::Error;
use std::path::Path;
use std::path::PathBuf;
use std::process::ExitStatus;
use std::process::Stdio;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::ChildStderr;
use tokio::process::ChildStdout;
use tokio::process::Command;
use tokio::time::timeout;

const BODY_SENTINEL: &str = "PLAN068_PRIVATE_PUBLICATION_BODY";
const PROCESS_TIMEOUT: Duration = Duration::from_secs(5);

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(1);

const FAKE_WORKER: &str = r#"
import copy
import json
import os
import struct
import sys
import time

descriptor_path, mode, state_dir = sys.argv[1:]
with open(descriptor_path, "r", encoding="utf-8") as handle:
    descriptor = json.load(handle)
count_path = os.path.join(state_dir, "spawn-count")
try:
    with open(count_path, "r", encoding="ascii") as handle:
        instance = int(handle.read()) + 1
except FileNotFoundError:
    instance = 1
with open(count_path, "w", encoding="ascii") as handle:
    handle.write(str(instance))
with open(os.path.join(state_dir, "pids"), "a", encoding="ascii") as handle:
    handle.write(str(os.getpid()) + "\n")

def read_exact(count):
    chunks = []
    remaining = count
    while remaining:
        chunk = sys.stdin.buffer.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

def receive():
    header = read_exact(4)
    if header is None:
        return None
    length = struct.unpack(">I", header)[0]
    if length == 0 or length > 1024 * 1024:
        raise SystemExit(70)
    body = read_exact(length)
    if body is None:
        raise SystemExit(70)
    return json.loads(body)

def send(value):
    body = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(struct.pack(">I", len(body)))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()

observed = copy.deepcopy(descriptor)
if mode == "identity_drift":
    observed["service_descriptor"]["identity"]["model"]["model"]["revision"] = "drift"
elif mode == "artifact_drift":
    observed["deployment_artifact_sha256"] = "c" * 64

while True:
    request = receive()
    if request is None:
        break
    operation = request.get("op")
    if operation == "descriptor" and set(request) == {"op"}:
        send({"ok": True, "descriptor": observed})
    elif operation == "status" and set(request) == {"op"}:
        send({
            "ok": True,
            "state": "ready",
            "load_seconds": 0.01,
            "resources": {
                "process_rss_bytes": 1,
                "process_peak_rss_bytes": 1,
                "cuda": None,
            },
        })
    elif operation == "score" and set(request) == {"op", "request_id", "packet"}:
        if mode == "block_first" and instance == 1:
            time.sleep(60)
        marker = os.path.join(state_dir, "failure-sent")
        if mode == "failure_first" and not os.path.exists(marker):
            with open(marker, "w", encoding="ascii") as handle:
                handle.write("1")
            send({
                "ok": False,
                "failure": {
                    "failure_kind": "InferenceError",
                    "message": "controlled backend failure",
                },
            })
            continue
        send({
            "ok": True,
            "request_id": request["request_id"],
            "raw_logit": 1.0986122886681098,
            "projected_score": 0.75,
            "token_count": 64,
            "dropped_oldest_publications": 0,
            "model_elapsed_ms": 1.0,
        })
    elif operation == "shutdown" and set(request) == {"op"}:
        send({"ok": True, "state": "stopped"})
        break
    else:
        send({
            "ok": False,
            "failure": {
                "failure_kind": "WorkerError",
                "message": "controlled request failure",
            },
        })
"#;

struct Fixture {
    root: PathBuf,
    descriptor: PathBuf,
    packet: PathBuf,
    worker: PathBuf,
}

impl Fixture {
    fn new() -> TestResult<Self> {
        let unique = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "rondo-plan068-real-scorer-{}-{unique}",
            std::process::id()
        ));
        std::fs::create_dir(&root)?;
        let descriptor = root.join("descriptor.json");
        let packet = root.join("packet.json");
        let worker = root.join("fake-worker.py");
        let service_descriptor = test_descriptor();
        let frozen = json!({
            "worker_protocol": "rondo-publication-critic-worker-v1",
            "object_id": "c1",
            "deployment_artifact_sha256": "a".repeat(64),
            "qualification_freeze_sha256": "b".repeat(64),
            "service_descriptor": service_descriptor,
        });
        std::fs::write(&descriptor, serde_json::to_vec(&frozen)?)?;
        std::fs::write(
            &packet,
            serde_json::to_vec(&test_packet(&service_descriptor))?,
        )?;
        std::fs::write(&worker, FAKE_WORKER)?;
        Ok(Self {
            root,
            descriptor,
            packet,
            worker,
        })
    }

    fn worker_pids(&self) -> TestResult<Vec<u32>> {
        let value = std::fs::read_to_string(self.root.join("pids"))?;
        value
            .lines()
            .map(|line| line.parse::<u32>().map_err(Into::into))
            .collect()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

struct CapturedProbe {
    status: ExitStatus,
    stdout: String,
    stderr: String,
}

struct ServiceProcess {
    child: Child,
    stdout: BufReader<ChildStdout>,
    stderr: ChildStderr,
    endpoint: std::net::SocketAddr,
    descriptor: PathBuf,
}

impl ServiceProcess {
    async fn spawn(fixture: &Fixture, mode: &str) -> TestResult<Self> {
        let mut command = Command::new(cargo_bin("codex-publication-critic-real-service")?);
        command
            .arg("--descriptor")
            .arg(&fixture.descriptor)
            .arg("--worker-program")
            .arg("python3")
            .arg("--worker-arg=-u")
            .arg(format!("--worker-arg={}", fixture.worker.display()))
            .arg(format!("--worker-arg={}", fixture.descriptor.display()))
            .arg(format!("--worker-arg={mode}"))
            .arg(format!("--worker-arg={}", fixture.root.display()))
            .arg("--worker-startup-timeout-ms")
            .arg("1500")
            .arg("--worker-io-timeout-ms")
            .arg("1000")
            .arg("--worker-shutdown-timeout-ms")
            .arg("1000")
            .arg("--graceful-shutdown-ms")
            .arg("500")
            .arg("--force-shutdown-ms")
            .arg("500")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        let mut child = command.spawn()?;
        let stdout = child.stdout.take().ok_or("service stdout was not piped")?;
        let stderr = child.stderr.take().ok_or("service stderr was not piped")?;
        let mut stdout = BufReader::new(stdout);
        let mut line = String::new();
        let read = timeout(PROCESS_TIMEOUT, stdout.read_line(&mut line))
            .await
            .map_err(|_| "service startup announcement timed out")??;
        if read == 0 {
            return Err("service exited before startup announcement".into());
        }
        let announcement: StartupAnnouncement = serde_json::from_str(line.trim_end())?;
        let expected: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&fixture.descriptor)?)?;
        let expected: ServiceDescriptor = serde_json::from_value(
            expected
                .get("service_descriptor")
                .cloned()
                .ok_or("frozen service descriptor is missing")?,
        )?;
        assert_eq!(announcement.descriptor, expected);
        assert!(announcement.endpoint.ip().is_loopback());
        Ok(Self {
            child,
            stdout,
            stderr,
            endpoint: announcement.endpoint,
            descriptor: fixture.descriptor.clone(),
        })
    }

    async fn probe(&self, command: &[&str]) -> TestResult<CapturedProbe> {
        let mut process = Command::new(cargo_bin("codex-publication-critic-probe")?);
        process
            .arg("--endpoint")
            .arg(self.endpoint.to_string())
            .arg("--expected-descriptor")
            .arg(&self.descriptor)
            .arg("--call-timeout-ms")
            .arg("1500")
            .arg("--startup-timeout-ms")
            .arg("3000")
            .args(command)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let output = timeout(PROCESS_TIMEOUT, process.output())
            .await
            .map_err(|_| "probe process timed out")??;
        Ok(CapturedProbe {
            status: output.status,
            stdout: String::from_utf8(output.stdout)?,
            stderr: String::from_utf8(output.stderr)?,
        })
    }

    async fn finish(mut self) -> TestResult<(ExitStatus, String, String)> {
        let status = timeout(PROCESS_TIMEOUT, self.child.wait())
            .await
            .map_err(|_| "real service shutdown timed out")??;
        let mut stdout = String::new();
        self.stdout.read_to_string(&mut stdout).await?;
        let mut stderr = String::new();
        self.stderr.read_to_string(&mut stderr).await?;
        Ok((status, stdout, stderr))
    }
}

#[tokio::test(flavor = "current_thread")]
async fn frozen_descriptor_real_service_and_typed_probe_complete_cleanly() -> TestResult {
    let fixture = Fixture::new()?;
    let service = ServiceProcess::spawn(&fixture, "normal").await?;
    assert_probe_success(service.probe(&["ready"]).await?, "\"result\":\"ready\"");
    assert_probe_success(
        service
            .probe(&["review", "--packet", path_text(&fixture.packet)?])
            .await?,
        "\"result\":\"pass\"",
    );
    assert_probe_success(
        service.probe(&["shutdown"]).await?,
        "\"result\":\"accepted\"",
    );
    let (status, stdout, stderr) = service.finish().await?;
    assert!(status.success(), "real service failed: {status}");
    assert!(
        stdout.is_empty(),
        "service emitted stdout after announcement"
    );
    assert!(stderr.contains("publication_critic_real_service_listening"));
    assert!(stderr.contains("publication_critic_real_service_stopped"));
    assert_redacted(&stdout, &stderr);
    assert_all_workers_gone(&fixture).await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn worker_identity_drift_cannot_become_ready_or_score() -> TestResult {
    let fixture = Fixture::new()?;
    let service = ServiceProcess::spawn(&fixture, "identity_drift").await?;
    let ready = service.probe(&["ready"]).await?;
    assert!(!ready.status.success());
    assert!(ready.stderr.contains("code=identity_mismatch"));
    assert_redacted(&ready.stdout, &ready.stderr);
    assert_probe_success(
        service.probe(&["shutdown"]).await?,
        "\"result\":\"accepted\"",
    );
    let (status, stdout, stderr) = service.finish().await?;
    assert!(status.success(), "real service failed: {status}");
    assert_redacted(&stdout, &stderr);
    assert_all_workers_gone(&fixture).await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn worker_artifact_drift_stays_failed_after_the_worker_is_reaped() -> TestResult {
    let fixture = Fixture::new()?;
    let service = ServiceProcess::spawn(&fixture, "artifact_drift").await?;
    let ready = service.probe(&["ready"]).await?;
    assert!(!ready.status.success());
    assert!(ready.stderr.contains("code=backend"));
    assert_redacted(&ready.stdout, &ready.stderr);
    assert_probe_success(
        service.probe(&["shutdown"]).await?,
        "\"result\":\"accepted\"",
    );
    let (status, stdout, stderr) = service.finish().await?;
    assert!(status.success(), "real service failed: {status}");
    assert_redacted(&stdout, &stderr);
    assert_all_workers_gone(&fixture).await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn cancellation_kills_reaps_and_restarts_the_worker() -> TestResult {
    let fixture = Fixture::new()?;
    let service = ServiceProcess::spawn(&fixture, "block_first").await?;
    assert_probe_success(service.probe(&["ready"]).await?, "\"result\":\"ready\"");
    let cancelled = service
        .probe(&[
            "cancel",
            "--packet",
            path_text(&fixture.packet)?,
            "--cancel-after-ms",
            "100",
        ])
        .await?;
    assert_probe_success(cancelled, "\"result\":\"cancelled\"");
    assert_probe_success(service.probe(&["ready"]).await?, "\"result\":\"ready\"");
    assert_probe_success(
        service
            .probe(&["review", "--packet", path_text(&fixture.packet)?])
            .await?,
        "\"result\":\"pass\"",
    );
    let pids = fixture.worker_pids()?;
    assert!(pids.len() >= 2, "worker was not restarted: {pids:?}");
    wait_until_process_gone(pids[0]).await?;
    assert_probe_success(
        service.probe(&["shutdown"]).await?,
        "\"result\":\"accepted\"",
    );
    let (status, stdout, stderr) = service.finish().await?;
    assert!(status.success(), "real service failed: {status}");
    assert_redacted(&stdout, &stderr);
    assert_all_workers_gone(&fixture).await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn typed_backend_failure_restarts_without_poisoning_the_next_call() -> TestResult {
    let fixture = Fixture::new()?;
    let service = ServiceProcess::spawn(&fixture, "failure_first").await?;
    assert_probe_success(service.probe(&["ready"]).await?, "\"result\":\"ready\"");
    let failed = service
        .probe(&["review", "--packet", path_text(&fixture.packet)?])
        .await?;
    assert!(!failed.status.success());
    assert!(failed.stderr.contains("code=backend"));
    assert_redacted(&failed.stdout, &failed.stderr);
    assert_probe_success(service.probe(&["ready"]).await?, "\"result\":\"ready\"");
    assert_probe_success(
        service
            .probe(&["review", "--packet", path_text(&fixture.packet)?])
            .await?,
        "\"result\":\"pass\"",
    );
    assert_probe_success(
        service.probe(&["shutdown"]).await?,
        "\"result\":\"accepted\"",
    );
    let (status, stdout, stderr) = service.finish().await?;
    assert!(status.success(), "real service failed: {status}");
    assert_redacted(&stdout, &stderr);
    assert_all_workers_gone(&fixture).await?;
    Ok(())
}

fn test_descriptor() -> ServiceDescriptor {
    controlled_test_descriptor(
        RuntimeLimits::new(
            32 * 1024,
            16 * 1024,
            /*max_concurrency*/ 1,
            /*queue_capacity*/ 4,
            Duration::from_secs(2),
            Duration::from_secs(1),
        )
        .expect("test runtime is valid"),
    )
}

fn test_packet(descriptor: &ServiceDescriptor) -> PublicationPacket {
    PublicationPacket::new(
        descriptor.identity.qualification.clone(),
        ActorRole::Root,
        TargetKind::NewEvent,
        LocalScope::new("Plan 068 local service").expect("test title is valid"),
        PublicationCandidate::new(format!("candidate {BODY_SENTINEL}"))
            .expect("test candidate is valid"),
        ContinuityContext::NotApplicable,
    )
    .expect("test packet is valid")
}

fn path_text(path: &Path) -> TestResult<&str> {
    path.to_str().ok_or_else(|| "test path is not UTF-8".into())
}

fn assert_probe_success(probe: CapturedProbe, expected: &str) {
    assert!(
        probe.status.success(),
        "probe failed: status={} stderr={}",
        probe.status,
        probe.stderr
    );
    assert!(
        probe.stdout.contains(expected),
        "probe output: {}",
        probe.stdout
    );
    assert_redacted(&probe.stdout, &probe.stderr);
}

fn assert_redacted(stdout: &str, stderr: &str) {
    assert!(
        !stdout.contains(BODY_SENTINEL),
        "stdout exposed packet body"
    );
    assert!(
        !stderr.contains(BODY_SENTINEL),
        "stderr exposed packet body"
    );
}

async fn assert_all_workers_gone(fixture: &Fixture) -> TestResult {
    for pid in fixture.worker_pids()? {
        wait_until_process_gone(pid).await?;
    }
    Ok(())
}

async fn wait_until_process_gone(pid: u32) -> TestResult {
    let process = PathBuf::from(format!("/proc/{pid}"));
    timeout(PROCESS_TIMEOUT, async {
        while process.exists() {
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .map_err(|_| format!("worker process {pid} was not reaped"))?;
    Ok(())
}
