use crate::ContractFailure;
use crate::IdentityField;
use crate::ServiceIdentity;
use crate::controlled_test_identity;
use serde::Deserialize;
use serde::Serialize;
use std::time::Duration;

pub const DEFAULT_REQUEST_BYTES: u32 = 128 * 1024;
pub const DEFAULT_RESPONSE_BYTES: u32 = 16 * 1024;
pub const MIN_PROTOCOL_FRAME_BYTES: u32 = 8 * 1024;
pub const DEFAULT_MAX_CONCURRENCY: u16 = 1;
pub const DEFAULT_QUEUE_CAPACITY: u16 = 4;
const DEFAULT_JOB_TIMEOUT_MS: u64 = 25_000;
const DEFAULT_IO_TIMEOUT_MS: u64 = 2_000;

pub const DEFAULT_JOB_TIMEOUT: Duration = Duration::from_millis(DEFAULT_JOB_TIMEOUT_MS);
pub const DEFAULT_CLIENT_TIMEOUT: Duration = Duration::from_secs(30);
pub const DEFAULT_STARTUP_TIMEOUT: Duration = Duration::from_secs(60);
pub const DEFAULT_IO_TIMEOUT: Duration = Duration::from_millis(DEFAULT_IO_TIMEOUT_MS);
pub const DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(3);
pub const DEFAULT_FORCE_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);

const MAX_FRAME_BYTES: u32 = 1024 * 1024;
const MAX_CONCURRENCY: u16 = 8;
const MAX_QUEUE_CAPACITY: u16 = 64;
const MAX_TIMEOUT_MS: u64 = 5 * 60 * 1_000;

#[derive(Clone, Debug)]
pub struct ServiceConfig {
    pub(crate) descriptor: ServiceDescriptor,
    pub(crate) graceful_shutdown_timeout: Duration,
    pub(crate) force_shutdown_timeout: Duration,
}

impl ServiceConfig {
    pub fn new(
        descriptor: ServiceDescriptor,
        graceful_shutdown_timeout: Duration,
        force_shutdown_timeout: Duration,
    ) -> Result<Self, ContractFailure> {
        let config = Self {
            descriptor,
            graceful_shutdown_timeout,
            force_shutdown_timeout,
        };
        config.validate()?;
        Ok(config)
    }

    pub(crate) fn validate(&self) -> Result<(), ContractFailure> {
        self.descriptor.validate()?;
        validate_bounded_timeout(self.graceful_shutdown_timeout)?;
        validate_bounded_timeout(self.force_shutdown_timeout)
    }

    pub fn descriptor(&self) -> &ServiceDescriptor {
        &self.descriptor
    }

    pub fn graceful_shutdown_timeout(&self) -> Duration {
        self.graceful_shutdown_timeout
    }

    pub fn force_shutdown_timeout(&self) -> Duration {
        self.force_shutdown_timeout
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeLimits {
    pub(crate) request_bytes: u32,
    pub(crate) response_bytes: u32,
    pub(crate) max_concurrency: u16,
    pub(crate) queue_capacity: u16,
    pub(crate) job_timeout_ms: u64,
    pub(crate) io_timeout_ms: u64,
}

impl RuntimeLimits {
    pub fn production() -> Self {
        Self {
            request_bytes: DEFAULT_REQUEST_BYTES,
            response_bytes: DEFAULT_RESPONSE_BYTES,
            max_concurrency: DEFAULT_MAX_CONCURRENCY,
            queue_capacity: DEFAULT_QUEUE_CAPACITY,
            job_timeout_ms: DEFAULT_JOB_TIMEOUT_MS,
            io_timeout_ms: DEFAULT_IO_TIMEOUT_MS,
        }
    }

    pub fn new(
        request_bytes: u32,
        response_bytes: u32,
        max_concurrency: u16,
        queue_capacity: u16,
        job_timeout: Duration,
        io_timeout: Duration,
    ) -> Result<Self, ContractFailure> {
        let limits = Self {
            request_bytes,
            response_bytes,
            max_concurrency,
            queue_capacity,
            job_timeout_ms: bounded_timeout_millis(job_timeout)?,
            io_timeout_ms: bounded_timeout_millis(io_timeout)?,
        };
        limits.validate()?;
        Ok(limits)
    }

    pub fn validate(&self) -> Result<(), ContractFailure> {
        if self.request_bytes < MIN_PROTOCOL_FRAME_BYTES
            || self.request_bytes > MAX_FRAME_BYTES
            || self.response_bytes < MIN_PROTOCOL_FRAME_BYTES
            || self.response_bytes > MAX_FRAME_BYTES
            || self.max_concurrency == 0
            || self.max_concurrency > MAX_CONCURRENCY
            || self.queue_capacity > MAX_QUEUE_CAPACITY
            || self.job_timeout_ms == 0
            || self.job_timeout_ms > MAX_TIMEOUT_MS
            || self.io_timeout_ms == 0
            || self.io_timeout_ms > MAX_TIMEOUT_MS
        {
            return Err(ContractFailure::InvalidResourceConfiguration);
        }
        let _ = self
            .max_concurrency
            .checked_add(self.queue_capacity)
            .ok_or(ContractFailure::InvalidResourceConfiguration)?;
        Ok(())
    }

    pub fn job_timeout(&self) -> Duration {
        Duration::from_millis(self.job_timeout_ms)
    }

    pub fn io_timeout(&self) -> Duration {
        Duration::from_millis(self.io_timeout_ms)
    }

    pub fn admission_capacity(&self) -> usize {
        usize::from(self.max_concurrency + self.queue_capacity)
    }

    pub fn request_bytes(&self) -> u32 {
        self.request_bytes
    }

    pub fn response_bytes(&self) -> u32 {
        self.response_bytes
    }

    pub fn max_concurrency(&self) -> u16 {
        self.max_concurrency
    }

    pub fn queue_capacity(&self) -> u16 {
        self.queue_capacity
    }

    pub fn job_timeout_ms(&self) -> u64 {
        self.job_timeout_ms
    }

    pub fn io_timeout_ms(&self) -> u64 {
        self.io_timeout_ms
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ServiceDescriptor {
    pub identity: ServiceIdentity,
    pub limits: RuntimeLimits,
}

impl ServiceDescriptor {
    pub fn new(identity: ServiceIdentity, limits: RuntimeLimits) -> Result<Self, ContractFailure> {
        let descriptor = Self { identity, limits };
        descriptor.validate()?;
        Ok(descriptor)
    }

    pub fn validate(&self) -> Result<(), ContractFailure> {
        self.identity.validate()?;
        self.limits.validate()
    }
}

pub fn controlled_test_descriptor(limits: RuntimeLimits) -> ServiceDescriptor {
    ServiceDescriptor {
        identity: controlled_test_identity(),
        limits,
    }
}

fn identity_mismatch(expected: &ServiceDescriptor, actual: &ServiceDescriptor) -> IdentityField {
    if expected.identity.protocol != actual.identity.protocol {
        IdentityField::Protocol
    } else if expected.identity.implementation != actual.identity.implementation {
        IdentityField::Service
    } else if expected.identity.qualification != actual.identity.qualification {
        IdentityField::Qualification
    } else if expected.identity.model != actual.identity.model {
        IdentityField::Model
    } else if expected.identity.scoring != actual.identity.scoring {
        IdentityField::Scoring
    } else {
        IdentityField::Resources
    }
}

pub fn validate_expected_descriptor(
    expected: &ServiceDescriptor,
    actual: &ServiceDescriptor,
) -> Result<(), ContractFailure> {
    expected.validate()?;
    actual.validate()?;
    if expected != actual {
        return Err(ContractFailure::IdentityMismatch(identity_mismatch(
            expected, actual,
        )));
    }
    Ok(())
}

pub(crate) fn validate_bounded_timeout(duration: Duration) -> Result<(), ContractFailure> {
    bounded_timeout_millis(duration).map(|_| ())
}

fn bounded_timeout_millis(duration: Duration) -> Result<u64, ContractFailure> {
    let millis = u64::try_from(duration.as_millis())
        .map_err(|_| ContractFailure::InvalidResourceConfiguration)?;
    if millis == 0 || millis > MAX_TIMEOUT_MS {
        return Err(ContractFailure::InvalidResourceConfiguration);
    }
    Ok(millis)
}
