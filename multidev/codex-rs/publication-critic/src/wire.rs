use crate::ProtocolVersion;
use crate::PublicationPacket;
use crate::ServiceDescriptor;
use crate::Verdict;
use serde::Deserialize;
use serde::Serialize;
use std::net::SocketAddr;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct StartupAnnouncement {
    pub protocol: ProtocolVersion,
    pub endpoint: SocketAddr,
    pub descriptor: ServiceDescriptor,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ServicePhase {
    Starting,
    Ready,
    Draining,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ServiceStatus {
    pub phase: ServicePhase,
    pub in_flight: u16,
    pub queued: u16,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RequestEnvelope {
    pub protocol: ProtocolVersion,
    pub request: RequestPayload,
}

#[derive(Deserialize, Serialize)]
#[serde(
    deny_unknown_fields,
    tag = "type",
    content = "data",
    rename_all = "snake_case"
)]
pub(crate) enum RequestPayload {
    Liveness,
    Readiness,
    Review {
        expected: Box<ServiceDescriptor>,
        packet: Box<PublicationPacket>,
    },
    Shutdown {
        expected: Box<ServiceDescriptor>,
    },
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ResponseEnvelope {
    pub protocol: ProtocolVersion,
    pub descriptor: ServiceDescriptor,
    pub response: ResponsePayload,
}

#[derive(Deserialize, Serialize)]
#[serde(
    deny_unknown_fields,
    tag = "type",
    content = "data",
    rename_all = "snake_case"
)]
pub(crate) enum ResponsePayload {
    Liveness { status: ServiceStatus },
    Readiness { status: ServiceStatus },
    Verdict { verdict: Verdict },
    ShutdownAccepted,
    Failure { code: ServiceFailureCode },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ServiceFailureCode {
    InvalidRequest,
    RequestTooLarge,
    NotReady,
    ShuttingDown,
    QueueFull,
    BackendFailed,
    ExecutionTimeout,
    InvalidScoreShape,
    NonFiniteScore,
    ScoreOutOfDomain,
    BackendModelIdentityMismatch,
    BackendScoringIdentityMismatch,
}
