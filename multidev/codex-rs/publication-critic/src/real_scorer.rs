use crate::ModelIdentity;
use crate::PublicationPacket;
use crate::PublicationScorer;
use crate::RawScorerOutput;
use crate::ScorerError;
use crate::ScorerProjection;
use crate::ScorerStatus;
use crate::ScoringContract;
use crate::ServiceDescriptor;
use crate::transport::ReadFrameError;
use crate::transport::read_frame;
use crate::transport::write_frame;
use serde::Deserialize;
use serde::Serialize;
use std::ffi::OsString;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::RwLock;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use thiserror::Error;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::ChildStdin;
use tokio::process::ChildStdout;
use tokio::process::Command;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

pub const WORKER_PROTOCOL: &str = "rondo-publication-critic-worker-v1";
const WORKER_FRAME_BYTES: u32 = 1024 * 1024;
const WORKER_COMMAND_CAPACITY: usize = 8;
const MAX_WORKER_TIMEOUT: Duration = Duration::from_secs(5 * 60);
const ADOPTED_CONTEXT_WINDOW: u32 = 16_384;
const MAX_OMITTED_PUBLICATIONS: u32 = 4;
const PROJECTION_TOLERANCE: f64 = 1e-12;
const MAX_OBJECT_ID_BYTES: usize = 128;

/// Frozen worker identity shared by the launcher, scorer, and Python worker.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RealScorerDescriptor {
    worker_protocol: String,
    object_id: String,
    deployment_artifact_sha256: String,
    qualification_freeze_sha256: String,
    service_descriptor: ServiceDescriptor,
}

impl RealScorerDescriptor {
    pub fn validate(&self) -> Result<(), RealScorerConfigError> {
        if self.worker_protocol != WORKER_PROTOCOL
            || !is_artifact_object_id(&self.object_id)
            || !is_sha256(&self.deployment_artifact_sha256)
            || !is_sha256(&self.qualification_freeze_sha256)
            || self.service_descriptor.validate().is_err()
        {
            return Err(RealScorerConfigError::InvalidDescriptor);
        }
        Ok(())
    }

    pub fn service_descriptor(&self) -> &ServiceDescriptor {
        &self.service_descriptor
    }
}

fn is_artifact_object_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= MAX_OBJECT_ID_BYTES
        && bytes[0].is_ascii_alphanumeric()
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum RealScorerConfigError {
    #[error("publication critic real scorer descriptor is invalid")]
    InvalidDescriptor,
    #[error("publication critic real scorer process configuration is invalid")]
    InvalidProcess,
}

/// Bounded process configuration for the private Python inference worker.
pub struct RealScorerConfig {
    program: PathBuf,
    arguments: Vec<OsString>,
    descriptor: RealScorerDescriptor,
    startup_timeout: Duration,
    io_timeout: Duration,
    shutdown_timeout: Duration,
}

impl RealScorerConfig {
    pub fn new(
        program: PathBuf,
        arguments: Vec<OsString>,
        descriptor: RealScorerDescriptor,
        startup_timeout: Duration,
        io_timeout: Duration,
        shutdown_timeout: Duration,
    ) -> Result<Self, RealScorerConfigError> {
        descriptor.validate()?;
        if program.as_os_str().is_empty()
            || arguments.len() > 64
            || !bounded_timeout(startup_timeout)
            || !bounded_timeout(io_timeout)
            || !bounded_timeout(shutdown_timeout)
        {
            return Err(RealScorerConfigError::InvalidProcess);
        }
        Ok(Self {
            program,
            arguments,
            descriptor,
            startup_timeout,
            io_timeout,
            shutdown_timeout,
        })
    }
}

fn bounded_timeout(value: Duration) -> bool {
    !value.is_zero() && value <= MAX_WORKER_TIMEOUT
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum RealScorerShutdownError {
    #[error("publication critic real scorer supervisor is unavailable")]
    SupervisorUnavailable,
    #[error("publication critic real scorer shutdown timed out")]
    ShutdownTimeout,
}

struct RealScorerInner {
    commands: mpsc::Sender<SupervisorCommand>,
    status: Arc<RwLock<ScorerStatus>>,
    next_request_id: AtomicU64,
    shutdown_timeout: Duration,
}

/// Process-backed scorer that keeps exactly one bounded Python worker alive.
#[derive(Clone)]
pub struct RealPublicationScorer {
    inner: Arc<RealScorerInner>,
}

impl RealPublicationScorer {
    pub fn launch(config: RealScorerConfig) -> Self {
        let supervisor_shutdown_timeout = config
            .startup_timeout
            .saturating_add(config.shutdown_timeout);
        let status = Arc::new(RwLock::new(ScorerStatus::Loading));
        let (commands, receiver) = mpsc::channel(WORKER_COMMAND_CAPACITY);
        let supervisor_status = Arc::clone(&status);
        tokio::spawn(async move {
            supervise_worker(config, receiver, supervisor_status).await;
        });
        Self {
            inner: Arc::new(RealScorerInner {
                commands,
                status,
                next_request_id: AtomicU64::new(1),
                shutdown_timeout: supervisor_shutdown_timeout,
            }),
        }
    }

    pub async fn shutdown(&self) -> Result<(), RealScorerShutdownError> {
        let (reply, completion) = oneshot::channel();
        timeout(
            self.inner.shutdown_timeout,
            self.inner
                .commands
                .send(SupervisorCommand::Shutdown { reply }),
        )
        .await
        .map_err(|_| RealScorerShutdownError::ShutdownTimeout)?
        .map_err(|_| RealScorerShutdownError::SupervisorUnavailable)?;
        timeout(self.inner.shutdown_timeout, completion)
            .await
            .map_err(|_| RealScorerShutdownError::ShutdownTimeout)?
            .map_err(|_| RealScorerShutdownError::SupervisorUnavailable)
    }
}

impl PublicationScorer for RealPublicationScorer {
    fn status(&self) -> ScorerStatus {
        self.inner
            .status
            .read()
            .map_or(ScorerStatus::Failed, |status| status.clone())
    }

    async fn score(
        &self,
        packet: PublicationPacket,
        cancellation: CancellationToken,
    ) -> Result<RawScorerOutput, ScorerError> {
        if cancellation.is_cancelled() {
            return Err(ScorerError::BackendUnavailable);
        }
        let request_id = format!(
            "{:016x}",
            self.inner.next_request_id.fetch_add(1, Ordering::Relaxed)
        );
        let (reply, result) = oneshot::channel();
        let command = SupervisorCommand::Score {
            request_id,
            packet: Box::new(packet),
            cancellation: cancellation.clone(),
            reply,
        };
        tokio::select! {
            biased;
            _ = cancellation.cancelled() => return Err(ScorerError::BackendUnavailable),
            sent = self.inner.commands.send(command) => {
                sent.map_err(|_| ScorerError::BackendUnavailable)?;
            }
        }
        tokio::select! {
            biased;
            _ = cancellation.cancelled() => Err(ScorerError::BackendUnavailable),
            result = result => result.unwrap_or(Err(ScorerError::BackendUnavailable)),
        }
    }
}

enum SupervisorCommand {
    Score {
        request_id: String,
        packet: Box<PublicationPacket>,
        cancellation: CancellationToken,
        reply: oneshot::Sender<Result<RawScorerOutput, ScorerError>>,
    },
    Shutdown {
        reply: oneshot::Sender<()>,
    },
}

async fn supervise_worker(
    config: RealScorerConfig,
    mut commands: mpsc::Receiver<SupervisorCommand>,
    status: Arc<RwLock<ScorerStatus>>,
) {
    let mut worker = start_worker(&config, &status).await;
    while let Some(command) = commands.recv().await {
        match command {
            SupervisorCommand::Score {
                request_id,
                packet,
                cancellation,
                reply,
            } => {
                let Some(mut active) = worker.take() else {
                    let _ = reply.send(Err(ScorerError::BackendUnavailable));
                    continue;
                };
                match active.score(request_id, *packet, &cancellation).await {
                    Ok(output) => {
                        worker = Some(active);
                        let _ = reply.send(Ok(output));
                    }
                    Err(_) => {
                        set_status(&status, ScorerStatus::Loading);
                        active.force_stop(config.shutdown_timeout).await;
                        worker = start_worker(&config, &status).await;
                        let _ = reply.send(Err(ScorerError::BackendUnavailable));
                    }
                }
            }
            SupervisorCommand::Shutdown { reply } => {
                if let Some(active) = worker.take() {
                    active.graceful_shutdown(&config).await;
                }
                set_status(&status, ScorerStatus::Failed);
                let _ = reply.send(());
                return;
            }
        }
    }
    if let Some(active) = worker {
        active.force_stop(config.shutdown_timeout).await;
    }
    set_status(&status, ScorerStatus::Failed);
}

async fn start_worker(
    config: &RealScorerConfig,
    status: &Arc<RwLock<ScorerStatus>>,
) -> Option<WorkerProcess> {
    set_status(status, ScorerStatus::Loading);
    let (mut worker, observed) = match WorkerProcess::spawn(config).await {
        Ok(started) => started,
        Err(_) => {
            set_status(status, ScorerStatus::Failed);
            return None;
        }
    };
    if observed != config.descriptor {
        let expected_service = config.descriptor.service_descriptor();
        let observed_service = observed.service_descriptor();
        if observed_service.identity.model != expected_service.identity.model
            || observed_service.identity.scoring != expected_service.identity.scoring
        {
            // Preserve the observed service identity so the existing service layer can return
            // its precise typed identity-mismatch failure without trusting the announcement.
            set_status(status, ready_status(observed_service));
        } else {
            // A worker-side artifact/freeze mismatch has no product-wire identity field. Keep the
            // scorer closed instead of advertising a ready worker that was already reaped.
            set_status(status, ScorerStatus::Failed);
        }
        worker.force_stop(config.shutdown_timeout).await;
        return None;
    }
    if worker.check_status(config.io_timeout).await.is_err() {
        worker.force_stop(config.shutdown_timeout).await;
        set_status(status, ScorerStatus::Failed);
        return None;
    }
    set_status(status, ready_status(config.descriptor.service_descriptor()));
    Some(worker)
}

fn ready_status(descriptor: &ServiceDescriptor) -> ScorerStatus {
    ScorerStatus::Ready {
        model: descriptor.identity.model.clone(),
        scoring: Box::new(descriptor.identity.scoring.clone()),
    }
}

fn set_status(status: &RwLock<ScorerStatus>, value: ScorerStatus) {
    if let Ok(mut status) = status.write() {
        *status = value;
    }
}

struct WorkerProcess {
    child: Child,
    stdin: Option<ChildStdin>,
    stdout: Option<BufReader<ChildStdout>>,
    model: ModelIdentity,
    scoring: ScoringContract,
    io_timeout: Duration,
}

impl WorkerProcess {
    async fn spawn(
        config: &RealScorerConfig,
    ) -> Result<(Self, RealScorerDescriptor), WorkerFailure> {
        let mut command = Command::new(&config.program);
        command
            .args(&config.arguments)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .kill_on_drop(true);
        let mut child = command.spawn().map_err(|_| WorkerFailure::Unavailable)?;
        let stdin = child.stdin.take().ok_or(WorkerFailure::Unavailable)?;
        let stdout = child.stdout.take().ok_or(WorkerFailure::Unavailable)?;
        let service_descriptor = config.descriptor.service_descriptor();
        let mut worker = Self {
            child,
            stdin: Some(stdin),
            stdout: Some(BufReader::new(stdout)),
            model: service_descriptor.identity.model.clone(),
            scoring: service_descriptor.identity.scoring.clone(),
            io_timeout: config.io_timeout,
        };
        let response: DescriptorResponse = worker
            .control_exchange(
                &DescriptorRequest { op: "descriptor" },
                config.startup_timeout,
            )
            .await?;
        if !response.ok {
            return Err(WorkerFailure::Protocol);
        }
        response
            .descriptor
            .validate()
            .map_err(|_| WorkerFailure::Protocol)?;
        worker.model = response
            .descriptor
            .service_descriptor
            .identity
            .model
            .clone();
        worker.scoring = response
            .descriptor
            .service_descriptor
            .identity
            .scoring
            .clone();
        Ok((worker, response.descriptor))
    }

    async fn check_status(&mut self, io_timeout: Duration) -> Result<(), WorkerFailure> {
        let response: StatusResponse = self
            .control_exchange(&StatusRequest { op: "status" }, io_timeout)
            .await?;
        if !response.ok
            || response.state != "ready"
            || !response.load_seconds.is_finite()
            || response.load_seconds < 0.0
        {
            return Err(WorkerFailure::Protocol);
        }
        response.resources.validate()
    }

    async fn score(
        &mut self,
        request_id: String,
        packet: PublicationPacket,
        cancellation: &CancellationToken,
    ) -> Result<RawScorerOutput, WorkerFailure> {
        let request = ScoreRequest {
            op: "score",
            request_id: request_id.clone(),
            packet,
        };
        self.write_request(&request, self.io_timeout, Some(cancellation))
            .await?;
        let response: ScoreResponse = self
            .read_response(self.io_timeout, Some(cancellation))
            .await?;
        if !response.ok
            || response.request_id != request_id
            || !response.raw_logit.is_finite()
            || !response.projected_score.is_finite()
            || !(0.0..=1.0).contains(&response.projected_score)
            || response.token_count == 0
            || response.token_count > ADOPTED_CONTEXT_WINDOW
            || response.dropped_oldest_publications > MAX_OMITTED_PUBLICATIONS
            || !response.model_elapsed_ms.is_finite()
            || response.model_elapsed_ms < 0.0
            || (stable_sigmoid(response.raw_logit) - response.projected_score).abs()
                > PROJECTION_TOLERANCE
        {
            return Err(WorkerFailure::Protocol);
        }
        Ok(RawScorerOutput {
            model: self.model.clone(),
            scoring: self.scoring.clone(),
            projection: ScorerProjection::Scalar {
                scores: vec![response.projected_score],
            },
        })
    }

    async fn control_exchange<Request, Response>(
        &mut self,
        request: &Request,
        operation_timeout: Duration,
    ) -> Result<Response, WorkerFailure>
    where
        Request: Serialize,
        Response: for<'de> Deserialize<'de>,
    {
        self.write_request(request, operation_timeout, None).await?;
        self.read_response(operation_timeout, None).await
    }

    async fn write_request<Request>(
        &mut self,
        request: &Request,
        operation_timeout: Duration,
        cancellation: Option<&CancellationToken>,
    ) -> Result<(), WorkerFailure>
    where
        Request: Serialize,
    {
        let body = serde_json::to_vec(request).map_err(|_| WorkerFailure::Protocol)?;
        if body.is_empty() || body.len() > WORKER_FRAME_BYTES as usize {
            return Err(WorkerFailure::Protocol);
        }
        let stdin = self.stdin.as_mut().ok_or(WorkerFailure::Unavailable)?;
        let operation = timeout(operation_timeout, write_frame(stdin, &body));
        if let Some(cancellation) = cancellation {
            tokio::select! {
                biased;
                _ = cancellation.cancelled() => Err(WorkerFailure::Cancelled),
                result = operation => match result {
                    Ok(Ok(())) => Ok(()),
                    Ok(Err(_)) | Err(_) => Err(WorkerFailure::Unavailable),
                }
            }
        } else {
            match operation.await {
                Ok(Ok(())) => Ok(()),
                Ok(Err(_)) | Err(_) => Err(WorkerFailure::Unavailable),
            }
        }
    }

    async fn read_response<Response>(
        &mut self,
        operation_timeout: Duration,
        cancellation: Option<&CancellationToken>,
    ) -> Result<Response, WorkerFailure>
    where
        Response: for<'de> Deserialize<'de>,
    {
        let stdout = self.stdout.as_mut().ok_or(WorkerFailure::Unavailable)?;
        let operation = timeout(operation_timeout, read_frame(stdout, WORKER_FRAME_BYTES));
        let body = if let Some(cancellation) = cancellation {
            tokio::select! {
                biased;
                _ = cancellation.cancelled() => return Err(WorkerFailure::Cancelled),
                result = operation => match result {
                    Ok(Ok(body)) => body,
                    Ok(Err(ReadFrameError::TooLarge | ReadFrameError::Io)) | Err(_) => {
                        return Err(WorkerFailure::Unavailable);
                    }
                }
            }
        } else {
            match operation.await {
                Ok(Ok(body)) => body,
                Ok(Err(ReadFrameError::TooLarge | ReadFrameError::Io)) | Err(_) => {
                    return Err(WorkerFailure::Unavailable);
                }
            }
        };
        let value: serde_json::Value =
            serde_json::from_slice(&body).map_err(|_| WorkerFailure::Protocol)?;
        if value.get("ok") == Some(&serde_json::Value::Bool(false)) {
            let failure: FailureResponse =
                serde_json::from_value(value).map_err(|_| WorkerFailure::Protocol)?;
            if failure.ok
                || failure.failure.failure_kind.is_empty()
                || failure.failure.failure_kind.len() > 128
                || failure.failure.message.is_empty()
                || failure.failure.message.len() > 512
            {
                return Err(WorkerFailure::Protocol);
            }
            return Err(WorkerFailure::Rejected);
        }
        serde_json::from_value(value).map_err(|_| WorkerFailure::Protocol)
    }

    async fn graceful_shutdown(mut self, config: &RealScorerConfig) {
        let response = self
            .control_exchange::<_, ShutdownResponse>(
                &ShutdownRequest { op: "shutdown" },
                config.io_timeout,
            )
            .await;
        if !matches!(response, Ok(ShutdownResponse { ok: true, state }) if state == "stopped") {
            self.force_stop(config.shutdown_timeout).await;
            return;
        }
        self.close_pipes();
        if !matches!(
            timeout(config.shutdown_timeout, self.child.wait()).await,
            Ok(Ok(_))
        ) {
            self.kill_and_reap(config.shutdown_timeout).await;
        }
    }

    async fn force_stop(mut self, shutdown_timeout: Duration) {
        self.close_pipes();
        self.kill_and_reap(shutdown_timeout).await;
    }

    fn close_pipes(&mut self) {
        self.stdin.take();
        self.stdout.take();
    }

    async fn kill_and_reap(&mut self, shutdown_timeout: Duration) {
        if let Ok(Some(_)) = self.child.try_wait() {
            return;
        }
        let _ = self.child.start_kill();
        if timeout(shutdown_timeout, self.child.wait()).await.is_err() {
            let _ = self.child.kill().await;
        }
    }
}

fn stable_sigmoid(value: f64) -> f64 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exponential = value.exp();
        exponential / (1.0 + exponential)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum WorkerFailure {
    Cancelled,
    Protocol,
    Rejected,
    Unavailable,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct DescriptorRequest {
    op: &'static str,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DescriptorResponse {
    ok: bool,
    descriptor: RealScorerDescriptor,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct StatusRequest {
    op: &'static str,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StatusResponse {
    ok: bool,
    state: String,
    load_seconds: f64,
    resources: WorkerResources,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WorkerResources {
    process_rss_bytes: u64,
    process_peak_rss_bytes: u64,
    cuda: Option<WorkerCudaResources>,
}

impl WorkerResources {
    fn validate(&self) -> Result<(), WorkerFailure> {
        if self.process_rss_bytes == 0 || self.process_peak_rss_bytes == 0 {
            return Err(WorkerFailure::Protocol);
        }
        if let Some(cuda) = &self.cuda {
            cuda.validate()?;
        }
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WorkerCudaResources {
    allocated_bytes: u64,
    reserved_bytes: u64,
    max_allocated_bytes: u64,
    max_reserved_bytes: u64,
}

impl WorkerCudaResources {
    fn validate(&self) -> Result<(), WorkerFailure> {
        if self.allocated_bytes > self.reserved_bytes
            || self.max_allocated_bytes > self.max_reserved_bytes
            || self.allocated_bytes > self.max_allocated_bytes
            || self.reserved_bytes > self.max_reserved_bytes
        {
            return Err(WorkerFailure::Protocol);
        }
        Ok(())
    }
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct ScoreRequest {
    op: &'static str,
    request_id: String,
    packet: PublicationPacket,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ScoreResponse {
    ok: bool,
    request_id: String,
    raw_logit: f64,
    projected_score: f64,
    token_count: u32,
    dropped_oldest_publications: u32,
    model_elapsed_ms: f64,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct ShutdownRequest {
    op: &'static str,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ShutdownResponse {
    ok: bool,
    state: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FailureResponse {
    ok: bool,
    failure: WorkerFailureBody,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WorkerFailureBody {
    failure_kind: String,
    message: String,
}

#[cfg(test)]
#[path = "real_scorer_tests.rs"]
mod tests;
