use thiserror::Error;

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum CriticFailure {
    #[error("publication critic contract failure: {0}")]
    Contract(ContractFailure),
    #[error("publication critic infrastructure failure: {0}")]
    Infrastructure(InfrastructureFailure),
    #[error("publication critic call cancelled")]
    Cancelled,
}

impl CriticFailure {
    pub fn log_code(self) -> &'static str {
        match self {
            Self::Contract(failure) => failure.log_code(),
            Self::Infrastructure(failure) => failure.log_code(),
            Self::Cancelled => "cancelled",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum ContractFailure {
    #[error("invalid publication packet")]
    InvalidPacket,
    #[error("invalid identity")]
    InvalidIdentity,
    #[error("invalid scoring configuration")]
    InvalidScoringConfiguration,
    #[error("invalid resource configuration")]
    InvalidResourceConfiguration,
    #[error("request exceeds configured byte limit")]
    RequestTooLarge,
    #[error("response exceeds configured byte limit")]
    ResponseTooLarge,
    #[error("malformed response")]
    MalformedResponse,
    #[error("unsupported protocol version")]
    UnsupportedProtocol,
    #[error("{0} identity mismatch")]
    IdentityMismatch(IdentityField),
    #[error("invalid scorer output: {0}")]
    InvalidScore(ScoreFailureKind),
    #[error("service rejected the request contract")]
    RequestRejected,
}

impl ContractFailure {
    pub fn log_code(self) -> &'static str {
        match self {
            Self::InvalidPacket => "invalid_packet",
            Self::InvalidIdentity => "invalid_identity",
            Self::InvalidScoringConfiguration => "invalid_scoring_configuration",
            Self::InvalidResourceConfiguration => "invalid_resource_configuration",
            Self::RequestTooLarge => "request_too_large",
            Self::ResponseTooLarge => "response_too_large",
            Self::MalformedResponse => "malformed_response",
            Self::UnsupportedProtocol => "unsupported_protocol",
            Self::IdentityMismatch(_) => "identity_mismatch",
            Self::InvalidScore(_) => "invalid_score",
            Self::RequestRejected => "request_rejected",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum IdentityField {
    #[error("protocol")]
    Protocol,
    #[error("service")]
    Service,
    #[error("qualification")]
    Qualification,
    #[error("model")]
    Model,
    #[error("scoring")]
    Scoring,
    #[error("resources")]
    Resources,
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum ScoreFailureKind {
    #[error("unexpected shape")]
    Shape,
    #[error("non-finite score")]
    NonFinite,
    #[error("score outside configured domain")]
    OutOfDomain,
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum InfrastructureFailure {
    #[error("service is not ready")]
    NotReady,
    #[error("service is shutting down")]
    ShuttingDown,
    #[error("service queue is full")]
    QueueFull,
    #[error("service connection failed")]
    Connect,
    #[error("service disconnected")]
    Disconnected,
    #[error("service call timed out")]
    CallTimeout,
    #[error("service startup timed out")]
    StartupTimeout,
    #[error("service I/O timed out")]
    IoTimeout,
    #[error("service backend failed")]
    Backend,
    #[error("service exited unexpectedly")]
    UnexpectedExit,
    #[error("service shutdown timed out")]
    ShutdownTimeout,
}

impl InfrastructureFailure {
    pub fn log_code(self) -> &'static str {
        match self {
            Self::NotReady => "not_ready",
            Self::ShuttingDown => "shutting_down",
            Self::QueueFull => "queue_full",
            Self::Connect => "connect",
            Self::Disconnected => "disconnected",
            Self::CallTimeout => "call_timeout",
            Self::StartupTimeout => "startup_timeout",
            Self::IoTimeout => "io_timeout",
            Self::Backend => "backend",
            Self::UnexpectedExit => "unexpected_exit",
            Self::ShutdownTimeout => "shutdown_timeout",
        }
    }
}
