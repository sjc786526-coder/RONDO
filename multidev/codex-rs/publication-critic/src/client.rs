use crate::ContractFailure;
use crate::CriticFailure;
use crate::IdentityField;
use crate::InfrastructureFailure;
use crate::ProtocolVersion;
use crate::PublicationPacket;
use crate::ScoreFailureKind;
use crate::ServiceDescriptor;
use crate::Verdict;
use crate::transport::ReadFrameError;
use crate::transport::read_frame;
use crate::transport::write_frame;
use crate::validate_expected_descriptor;
use crate::wire::RequestEnvelope;
use crate::wire::RequestPayload;
use crate::wire::ResponseEnvelope;
use crate::wire::ResponsePayload;
use crate::wire::ServiceFailureCode;
use crate::wire::ServicePhase;
use crate::wire::ServiceStatus;
use std::net::SocketAddr;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::net::TcpStream;
use tokio::time::Instant;
use tokio::time::sleep_until;
use tokio::time::timeout_at;
use tokio_util::sync::CancellationToken;

const READY_POLL_INTERVAL: Duration = Duration::from_millis(50);

#[derive(Clone, Debug)]
pub struct ClientConfig {
    pub endpoint: SocketAddr,
    pub expected: ServiceDescriptor,
    pub call_timeout: Duration,
    pub startup_timeout: Duration,
}

impl ClientConfig {
    pub fn production(
        endpoint: SocketAddr,
        expected: ServiceDescriptor,
    ) -> Result<Self, ContractFailure> {
        Self::new(
            endpoint,
            expected,
            crate::DEFAULT_CLIENT_TIMEOUT,
            crate::DEFAULT_STARTUP_TIMEOUT,
        )
    }

    pub fn new(
        endpoint: SocketAddr,
        expected: ServiceDescriptor,
        call_timeout: Duration,
        startup_timeout: Duration,
    ) -> Result<Self, ContractFailure> {
        if !endpoint.ip().is_loopback() {
            return Err(ContractFailure::InvalidResourceConfiguration);
        }
        expected.validate()?;
        if call_timeout.is_zero() || startup_timeout.is_zero() {
            return Err(ContractFailure::InvalidResourceConfiguration);
        }
        Ok(Self {
            endpoint,
            expected,
            call_timeout,
            startup_timeout,
        })
    }
}

struct ClientInner {
    config: ClientConfig,
    shutting_down: AtomicBool,
}

#[derive(Clone)]
pub struct PublicationCriticClient {
    inner: Arc<ClientInner>,
}

impl PublicationCriticClient {
    pub fn new(config: ClientConfig) -> Self {
        Self {
            inner: Arc::new(ClientInner {
                config,
                shutting_down: AtomicBool::new(false),
            }),
        }
    }

    pub fn expected_descriptor(&self) -> &ServiceDescriptor {
        &self.inner.config.expected
    }

    pub async fn liveness(&self) -> Result<ServiceStatus, CriticFailure> {
        let response = self
            .exchange(
                RequestPayload::Liveness,
                CancellationToken::new(),
                Instant::now() + self.inner.config.call_timeout,
            )
            .await?;
        match response {
            ResponsePayload::Liveness { status } => Ok(status),
            ResponsePayload::Failure { code } => Err(map_service_failure(code)),
            ResponsePayload::Readiness { .. }
            | ResponsePayload::Verdict { .. }
            | ResponsePayload::ShutdownAccepted => {
                Err(CriticFailure::Contract(ContractFailure::MalformedResponse))
            }
        }
    }

    pub async fn readiness(&self) -> Result<ServiceStatus, CriticFailure> {
        let response = self
            .exchange(
                RequestPayload::Readiness,
                CancellationToken::new(),
                Instant::now() + self.inner.config.call_timeout,
            )
            .await?;
        match response {
            ResponsePayload::Readiness { status } => Ok(status),
            ResponsePayload::Failure { code } => Err(map_service_failure(code)),
            ResponsePayload::Liveness { .. }
            | ResponsePayload::Verdict { .. }
            | ResponsePayload::ShutdownAccepted => {
                Err(CriticFailure::Contract(ContractFailure::MalformedResponse))
            }
        }
    }

    pub async fn wait_until_ready(
        &self,
        cancellation: CancellationToken,
    ) -> Result<(), CriticFailure> {
        let deadline = Instant::now() + self.inner.config.startup_timeout;
        loop {
            if cancellation.is_cancelled() {
                return Err(CriticFailure::Cancelled);
            }
            match self
                .exchange(RequestPayload::Readiness, cancellation.clone(), deadline)
                .await
            {
                Ok(ResponsePayload::Readiness { status })
                    if matches!(status.phase, ServicePhase::Ready) =>
                {
                    return Ok(());
                }
                Ok(ResponsePayload::Readiness { status })
                    if matches!(status.phase, ServicePhase::Draining) =>
                {
                    return Err(CriticFailure::Infrastructure(
                        InfrastructureFailure::ShuttingDown,
                    ));
                }
                Ok(ResponsePayload::Readiness { .. })
                | Err(CriticFailure::Infrastructure(InfrastructureFailure::Connect)) => {}
                Ok(ResponsePayload::Failure { code }) => {
                    let failure = map_service_failure(code);
                    if !matches!(
                        failure,
                        CriticFailure::Infrastructure(InfrastructureFailure::NotReady)
                    ) {
                        return Err(failure);
                    }
                }
                Ok(
                    ResponsePayload::Liveness { .. }
                    | ResponsePayload::Verdict { .. }
                    | ResponsePayload::ShutdownAccepted,
                ) => {
                    return Err(CriticFailure::Contract(ContractFailure::MalformedResponse));
                }
                Err(CriticFailure::Infrastructure(InfrastructureFailure::CallTimeout)) => {
                    return Err(CriticFailure::Infrastructure(
                        InfrastructureFailure::StartupTimeout,
                    ));
                }
                Err(failure) => return Err(failure),
            }
            let next_poll = (Instant::now() + READY_POLL_INTERVAL).min(deadline);
            tokio::select! {
                biased;
                _ = cancellation.cancelled() => return Err(CriticFailure::Cancelled),
                _ = sleep_until(next_poll) => {}
            }
            if Instant::now() >= deadline {
                return Err(CriticFailure::Infrastructure(
                    InfrastructureFailure::StartupTimeout,
                ));
            }
        }
    }

    pub async fn review(&self, packet: PublicationPacket) -> Result<Verdict, CriticFailure> {
        self.review_with_cancellation(packet, CancellationToken::new())
            .await
    }

    pub async fn review_with_cancellation(
        &self,
        packet: PublicationPacket,
        cancellation: CancellationToken,
    ) -> Result<Verdict, CriticFailure> {
        if self.inner.shutting_down.load(Ordering::Acquire) {
            return Err(CriticFailure::Infrastructure(
                InfrastructureFailure::ShuttingDown,
            ));
        }
        packet.validate().map_err(CriticFailure::Contract)?;
        if packet.qualification != self.inner.config.expected.identity.qualification {
            return Err(CriticFailure::Contract(ContractFailure::IdentityMismatch(
                IdentityField::Qualification,
            )));
        }
        let response = self
            .exchange(
                RequestPayload::Review {
                    expected: Box::new(self.inner.config.expected.clone()),
                    packet: Box::new(packet),
                },
                cancellation,
                Instant::now() + self.inner.config.call_timeout,
            )
            .await?;
        match response {
            ResponsePayload::Verdict { verdict } => Ok(verdict),
            ResponsePayload::Failure { code } => Err(map_service_failure(code)),
            ResponsePayload::Liveness { .. }
            | ResponsePayload::Readiness { .. }
            | ResponsePayload::ShutdownAccepted => {
                Err(CriticFailure::Contract(ContractFailure::MalformedResponse))
            }
        }
    }

    pub async fn shutdown(&self) -> Result<(), CriticFailure> {
        if self.inner.shutting_down.swap(true, Ordering::AcqRel) {
            return Err(CriticFailure::Infrastructure(
                InfrastructureFailure::ShuttingDown,
            ));
        }
        let response = self
            .exchange(
                RequestPayload::Shutdown {
                    expected: Box::new(self.inner.config.expected.clone()),
                },
                CancellationToken::new(),
                Instant::now() + self.inner.config.call_timeout,
            )
            .await?;
        match response {
            ResponsePayload::ShutdownAccepted => Ok(()),
            ResponsePayload::Failure { code } => Err(map_service_failure(code)),
            ResponsePayload::Liveness { .. }
            | ResponsePayload::Readiness { .. }
            | ResponsePayload::Verdict { .. } => {
                Err(CriticFailure::Contract(ContractFailure::MalformedResponse))
            }
        }
    }

    async fn exchange(
        &self,
        request: RequestPayload,
        cancellation: CancellationToken,
        deadline: Instant,
    ) -> Result<ResponsePayload, CriticFailure> {
        let envelope = RequestEnvelope {
            protocol: ProtocolVersion::RondoPublicationCriticV1,
            request,
        };
        let body = serde_json::to_vec(&envelope)
            .map_err(|_| CriticFailure::Contract(ContractFailure::InvalidPacket))?;
        let body_len = u32::try_from(body.len())
            .map_err(|_| CriticFailure::Contract(ContractFailure::RequestTooLarge))?;
        if body_len > self.inner.config.expected.limits.request_bytes {
            return Err(CriticFailure::Contract(ContractFailure::RequestTooLarge));
        }
        let operation = async {
            let mut stream = TcpStream::connect(self.inner.config.endpoint)
                .await
                .map_err(|_| CriticFailure::Infrastructure(InfrastructureFailure::Connect))?;
            write_frame(&mut stream, &body)
                .await
                .map_err(|_| CriticFailure::Infrastructure(InfrastructureFailure::Disconnected))?;
            let response_body = match read_frame(
                &mut stream,
                self.inner.config.expected.limits.response_bytes,
            )
            .await
            {
                Ok(body) => body,
                Err(ReadFrameError::TooLarge) => {
                    return Err(CriticFailure::Contract(ContractFailure::ResponseTooLarge));
                }
                Err(ReadFrameError::Io) => {
                    return Err(CriticFailure::Infrastructure(
                        InfrastructureFailure::Disconnected,
                    ));
                }
            };
            let response: ResponseEnvelope = serde_json::from_slice(&response_body)
                .map_err(|_| CriticFailure::Contract(ContractFailure::MalformedResponse))?;
            if response.protocol != ProtocolVersion::RondoPublicationCriticV1 {
                return Err(CriticFailure::Contract(
                    ContractFailure::UnsupportedProtocol,
                ));
            }
            validate_expected_descriptor(&self.inner.config.expected, &response.descriptor)
                .map_err(CriticFailure::Contract)?;
            Ok(response.response)
        };

        tokio::select! {
            biased;
            _ = cancellation.cancelled() => Err(CriticFailure::Cancelled),
            result = timeout_at(deadline, operation) => match result {
                Ok(result) => result,
                Err(_) => Err(CriticFailure::Infrastructure(
                    InfrastructureFailure::CallTimeout,
                )),
            }
        }
    }
}

fn map_service_failure(code: ServiceFailureCode) -> CriticFailure {
    match code {
        ServiceFailureCode::InvalidRequest => {
            CriticFailure::Contract(ContractFailure::RequestRejected)
        }
        ServiceFailureCode::RequestTooLarge => {
            CriticFailure::Contract(ContractFailure::RequestTooLarge)
        }
        ServiceFailureCode::NotReady => {
            CriticFailure::Infrastructure(InfrastructureFailure::NotReady)
        }
        ServiceFailureCode::ShuttingDown => {
            CriticFailure::Infrastructure(InfrastructureFailure::ShuttingDown)
        }
        ServiceFailureCode::QueueFull => {
            CriticFailure::Infrastructure(InfrastructureFailure::QueueFull)
        }
        ServiceFailureCode::BackendFailed => {
            CriticFailure::Infrastructure(InfrastructureFailure::Backend)
        }
        ServiceFailureCode::ExecutionTimeout => {
            CriticFailure::Infrastructure(InfrastructureFailure::CallTimeout)
        }
        ServiceFailureCode::InvalidScoreShape => {
            CriticFailure::Contract(ContractFailure::InvalidScore(ScoreFailureKind::Shape))
        }
        ServiceFailureCode::NonFiniteScore => {
            CriticFailure::Contract(ContractFailure::InvalidScore(ScoreFailureKind::NonFinite))
        }
        ServiceFailureCode::ScoreOutOfDomain => {
            CriticFailure::Contract(ContractFailure::InvalidScore(ScoreFailureKind::OutOfDomain))
        }
        ServiceFailureCode::BackendModelIdentityMismatch => {
            CriticFailure::Contract(ContractFailure::IdentityMismatch(IdentityField::Model))
        }
        ServiceFailureCode::BackendScoringIdentityMismatch => {
            CriticFailure::Contract(ContractFailure::IdentityMismatch(IdentityField::Scoring))
        }
    }
}
