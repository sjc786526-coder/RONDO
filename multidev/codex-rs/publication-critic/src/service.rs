use crate::ContractFailure;
use crate::ProtocolVersion;
use crate::PublicationScorer;
use crate::RawScorerOutput;
use crate::ScoreFailureKind;
use crate::ScorerError;
use crate::ServiceConfig;
use crate::ServiceDescriptor;
use crate::backend::BackendState;
use crate::backend::classify_backend;
use crate::transport::ReadFrameError;
use crate::transport::read_frame;
use crate::transport::write_frame;
use crate::wire::RequestEnvelope;
use crate::wire::RequestPayload;
use crate::wire::ResponseEnvelope;
use crate::wire::ResponsePayload;
use crate::wire::ServiceFailureCode;
use crate::wire::ServicePhase;
use crate::wire::ServiceStatus;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU16;
use std::sync::atomic::Ordering;
use thiserror::Error;
use tokio::io::AsyncReadExt;
use tokio::net::TcpListener;
use tokio::net::TcpStream;
use tokio::net::tcp::OwnedReadHalf;
use tokio::net::tcp::OwnedWriteHalf;
use tokio::sync::OwnedSemaphorePermit;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio::time::Instant;
use tokio::time::timeout;
use tokio::time::timeout_at;
use tokio_util::sync::CancellationToken;

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum ServiceRunError {
    #[error("publication critic service configuration is invalid")]
    InvalidConfiguration,
    #[error("publication critic listener is not loopback-only")]
    NonLoopbackListener,
    #[error("publication critic listener address is unavailable")]
    ListenerAddressUnavailable,
    #[error("publication critic listener accept failed")]
    ListenerAcceptFailed,
    #[error("publication critic forced shutdown timed out")]
    ForceShutdownTimeout,
}

struct ServerState<S> {
    descriptor: ServiceDescriptor,
    scorer: S,
    draining: AtomicBool,
    in_flight: AtomicU16,
    queued: AtomicU16,
    admitted: Arc<Semaphore>,
    execution: Arc<Semaphore>,
    drain_requested: CancellationToken,
    force_cancel: CancellationToken,
}

impl<S: PublicationScorer> ServerState<S> {
    fn backend_state(&self) -> BackendState {
        classify_backend(self.scorer.status(), &self.descriptor)
    }

    fn status(&self, backend: BackendState) -> ServiceStatus {
        let phase = if self.draining.load(Ordering::Acquire) {
            ServicePhase::Draining
        } else {
            match backend {
                BackendState::Loading => ServicePhase::Starting,
                BackendState::Ready => ServicePhase::Ready,
                BackendState::Failed(_) => ServicePhase::Failed,
            }
        };
        ServiceStatus {
            phase,
            in_flight: self.in_flight.load(Ordering::Acquire),
            queued: self.queued.load(Ordering::Acquire),
        }
    }
}

struct GaugeGuard<'a> {
    gauge: &'a AtomicU16,
}

impl<'a> GaugeGuard<'a> {
    fn increment(gauge: &'a AtomicU16) -> Self {
        gauge.fetch_add(1, Ordering::AcqRel);
        Self { gauge }
    }
}

impl Drop for GaugeGuard<'_> {
    fn drop(&mut self) {
        self.gauge.fetch_sub(1, Ordering::AcqRel);
    }
}

struct CancelOnDrop(CancellationToken);

impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        self.0.cancel();
    }
}

pub async fn serve<S>(
    listener: TcpListener,
    config: ServiceConfig,
    scorer: S,
) -> Result<(), ServiceRunError>
where
    S: PublicationScorer,
{
    config
        .validate()
        .map_err(|_| ServiceRunError::InvalidConfiguration)?;
    let local_addr = listener
        .local_addr()
        .map_err(|_| ServiceRunError::ListenerAddressUnavailable)?;
    if !local_addr.ip().is_loopback() {
        return Err(ServiceRunError::NonLoopbackListener);
    }

    let admission_capacity = config.descriptor.limits.admission_capacity();
    let max_concurrency = config.descriptor.limits.max_concurrency;
    let connection_capacity = admission_capacity.saturating_add(1);
    let state = Arc::new(ServerState {
        descriptor: config.descriptor,
        scorer,
        draining: AtomicBool::new(false),
        in_flight: AtomicU16::new(0),
        queued: AtomicU16::new(0),
        admitted: Arc::new(Semaphore::new(admission_capacity)),
        execution: Arc::new(Semaphore::new(usize::from(max_concurrency))),
        drain_requested: CancellationToken::new(),
        force_cancel: CancellationToken::new(),
    });
    let connections = Arc::new(Semaphore::new(connection_capacity));
    let mut tasks = JoinSet::new();

    loop {
        tokio::select! {
            biased;
            _ = state.drain_requested.cancelled() => break,
            completed = tasks.join_next(), if !tasks.is_empty() => {
                let _ = completed;
            }
            accepted = listener.accept() => {
                let (stream, peer) = accepted.map_err(|_| ServiceRunError::ListenerAcceptFailed)?;
                if !peer.ip().is_loopback() {
                    continue;
                }
                let Ok(connection_permit) = Arc::clone(&connections).try_acquire_owned() else {
                    write_early_failure(stream, &state, ServiceFailureCode::QueueFull).await;
                    continue;
                };
                let task_state = Arc::clone(&state);
                tasks.spawn(async move {
                    handle_connection(stream, task_state, connection_permit).await;
                });
            }
        }
    }

    state.draining.store(true, Ordering::Release);
    state.admitted.close();
    state.execution.close();
    drop(listener);

    let graceful = async { while tasks.join_next().await.is_some() {} };
    if timeout(config.graceful_shutdown_timeout, graceful)
        .await
        .is_err()
    {
        state.force_cancel.cancel();
        let forced = async { while tasks.join_next().await.is_some() {} };
        if timeout(config.force_shutdown_timeout, forced)
            .await
            .is_err()
        {
            tasks.abort_all();
            return Err(ServiceRunError::ForceShutdownTimeout);
        }
    }
    Ok(())
}

async fn write_early_failure<S>(stream: TcpStream, state: &ServerState<S>, code: ServiceFailureCode)
where
    S: PublicationScorer,
{
    let (_reader, mut writer) = stream.into_split();
    write_response(&mut writer, state, ResponsePayload::Failure { code }).await;
}

async fn handle_connection<S>(
    stream: TcpStream,
    state: Arc<ServerState<S>>,
    _connection_permit: OwnedSemaphorePermit,
) where
    S: PublicationScorer,
{
    let (mut reader, mut writer) = stream.into_split();
    let request = match timeout(
        state.descriptor.limits.io_timeout(),
        read_frame(&mut reader, state.descriptor.limits.request_bytes),
    )
    .await
    {
        Ok(Ok(body)) => match serde_json::from_slice::<RequestEnvelope>(&body) {
            Ok(request) => request,
            Err(_) => {
                write_response(
                    &mut writer,
                    &state,
                    ResponsePayload::Failure {
                        code: ServiceFailureCode::InvalidRequest,
                    },
                )
                .await;
                return;
            }
        },
        Ok(Err(ReadFrameError::TooLarge)) => {
            write_response(
                &mut writer,
                &state,
                ResponsePayload::Failure {
                    code: ServiceFailureCode::RequestTooLarge,
                },
            )
            .await;
            return;
        }
        Ok(Err(ReadFrameError::Io)) | Err(_) => return,
    };

    if request.protocol != ProtocolVersion::RondoPublicationCriticV1 {
        write_response(
            &mut writer,
            &state,
            ResponsePayload::Failure {
                code: ServiceFailureCode::InvalidRequest,
            },
        )
        .await;
        return;
    }

    match request.request {
        RequestPayload::Liveness => {
            let status = state.status(state.backend_state());
            write_response(&mut writer, &state, ResponsePayload::Liveness { status }).await;
        }
        RequestPayload::Readiness => {
            let backend = state.backend_state();
            let response = if !state.draining.load(Ordering::Acquire)
                && let BackendState::Failed(code) = backend
            {
                ResponsePayload::Failure { code }
            } else {
                ResponsePayload::Readiness {
                    status: state.status(backend),
                }
            };
            write_response(&mut writer, &state, response).await;
        }
        RequestPayload::Shutdown { expected } => {
            let identity_matches = *expected == state.descriptor;
            let response = if identity_matches {
                state.draining.store(true, Ordering::Release);
                ResponsePayload::ShutdownAccepted
            } else {
                ResponsePayload::Failure {
                    code: ServiceFailureCode::InvalidRequest,
                }
            };
            write_response(&mut writer, &state, response).await;
            if identity_matches {
                state.drain_requested.cancel();
            }
        }
        RequestPayload::Review { expected, packet } => {
            handle_review(reader, &mut writer, &state, *expected, *packet).await;
        }
    }
}

async fn handle_review<S>(
    mut reader: OwnedReadHalf,
    writer: &mut OwnedWriteHalf,
    state: &Arc<ServerState<S>>,
    expected: ServiceDescriptor,
    packet: crate::PublicationPacket,
) where
    S: PublicationScorer,
{
    if state.draining.load(Ordering::Acquire) {
        write_failure(writer, state, ServiceFailureCode::ShuttingDown).await;
        return;
    }
    if expected != state.descriptor
        || packet.validate().is_err()
        || packet.qualification != state.descriptor.identity.qualification
    {
        write_failure(writer, state, ServiceFailureCode::InvalidRequest).await;
        return;
    }
    match state.backend_state() {
        BackendState::Ready => {}
        BackendState::Loading => {
            write_failure(writer, state, ServiceFailureCode::NotReady).await;
            return;
        }
        BackendState::Failed(code) => {
            write_failure(writer, state, code).await;
            return;
        }
    }
    let Ok(admission_permit) = Arc::clone(&state.admitted).try_acquire_owned() else {
        write_failure(writer, state, ServiceFailureCode::QueueFull).await;
        return;
    };

    let deadline = Instant::now() + state.descriptor.limits.job_timeout();
    let execution_permit = match Arc::clone(&state.execution).try_acquire_owned() {
        Ok(permit) => permit,
        Err(_) => {
            let queued = GaugeGuard::increment(&state.queued);
            let wait_result = tokio::select! {
                biased;
                _ = peer_closed(&mut reader) => None,
                _ = state.force_cancel.cancelled() => {
                    Some(Err(ServiceFailureCode::ShuttingDown))
                }
                _ = tokio::time::sleep_until(deadline) => {
                    Some(Err(ServiceFailureCode::ExecutionTimeout))
                }
                permit = Arc::clone(&state.execution).acquire_owned() => {
                    Some(permit.map_err(|_| ServiceFailureCode::ShuttingDown))
                }
            };
            drop(queued);
            match wait_result {
                None => return,
                Some(Ok(permit)) => permit,
                Some(Err(code)) => {
                    drop(admission_permit);
                    write_failure(writer, state, code).await;
                    return;
                }
            }
        }
    };

    let response = {
        let _execution_permit = execution_permit;
        let _in_flight = GaugeGuard::increment(&state.in_flight);
        let request_cancel = CancellationToken::new();
        let _cancel_on_drop = CancelOnDrop(request_cancel.clone());
        let score = state.scorer.score(packet, request_cancel.clone());
        tokio::pin!(score);
        enum ScoreWaitResult<T> {
            Output(T),
            TimedOut,
            ShuttingDown,
        }

        let output = tokio::select! {
            biased;
            _ = peer_closed(&mut reader) => {
                request_cancel.cancel();
                return;
            }
            _ = state.force_cancel.cancelled() => {
                request_cancel.cancel();
                ScoreWaitResult::ShuttingDown
            }
            _ = tokio::time::sleep_until(deadline) => {
                request_cancel.cancel();
                ScoreWaitResult::TimedOut
            }
            output = &mut score => ScoreWaitResult::Output(output),
        };

        match output {
            ScoreWaitResult::ShuttingDown => ResponsePayload::Failure {
                code: ServiceFailureCode::ShuttingDown,
            },
            ScoreWaitResult::TimedOut => ResponsePayload::Failure {
                code: ServiceFailureCode::ExecutionTimeout,
            },
            ScoreWaitResult::Output(Err(ScorerError::BackendUnavailable)) => {
                ResponsePayload::Failure {
                    code: ServiceFailureCode::BackendFailed,
                }
            }
            ScoreWaitResult::Output(Ok(RawScorerOutput { model, .. }))
                if model != state.descriptor.identity.model =>
            {
                ResponsePayload::Failure {
                    code: ServiceFailureCode::BackendModelIdentityMismatch,
                }
            }
            ScoreWaitResult::Output(Ok(RawScorerOutput { scoring, .. }))
                if scoring != state.descriptor.identity.scoring =>
            {
                ResponsePayload::Failure {
                    code: ServiceFailureCode::BackendScoringIdentityMismatch,
                }
            }
            ScoreWaitResult::Output(Ok(output)) => match state
                .descriptor
                .identity
                .scoring
                .verdict_for_scores(&output.scores)
            {
                Ok(verdict) => ResponsePayload::Verdict { verdict },
                Err(ContractFailure::InvalidScore(ScoreFailureKind::Shape)) => {
                    ResponsePayload::Failure {
                        code: ServiceFailureCode::InvalidScoreShape,
                    }
                }
                Err(ContractFailure::InvalidScore(ScoreFailureKind::NonFinite)) => {
                    ResponsePayload::Failure {
                        code: ServiceFailureCode::NonFiniteScore,
                    }
                }
                Err(ContractFailure::InvalidScore(ScoreFailureKind::OutOfDomain)) => {
                    ResponsePayload::Failure {
                        code: ServiceFailureCode::ScoreOutOfDomain,
                    }
                }
                Err(_) => ResponsePayload::Failure {
                    code: ServiceFailureCode::BackendFailed,
                },
            },
        }
    };
    drop(admission_permit);
    write_response(writer, state, response).await;
}

async fn peer_closed(reader: &mut OwnedReadHalf) {
    let mut byte = [0_u8; 1];
    let _ = reader.read(&mut byte).await;
}

async fn write_failure<S>(
    writer: &mut OwnedWriteHalf,
    state: &ServerState<S>,
    code: ServiceFailureCode,
) where
    S: PublicationScorer,
{
    write_response(writer, state, ResponsePayload::Failure { code }).await;
}

async fn write_response<S>(
    writer: &mut OwnedWriteHalf,
    state: &ServerState<S>,
    response: ResponsePayload,
) where
    S: PublicationScorer,
{
    let envelope = ResponseEnvelope {
        protocol: ProtocolVersion::RondoPublicationCriticV1,
        descriptor: state.descriptor.clone(),
        response,
    };
    let Ok(body) = serde_json::to_vec(&envelope) else {
        return;
    };
    let Ok(response_len) = u32::try_from(body.len()) else {
        return;
    };
    if response_len > state.descriptor.limits.response_bytes {
        return;
    }
    let _ = timeout_at(
        Instant::now() + state.descriptor.limits.io_timeout(),
        write_frame(writer, &body),
    )
    .await;
}
