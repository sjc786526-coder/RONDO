//! Identities for a live team instance.
//!
//! Every externally visible reference (`EventId`, `VersionId`, projection headers, query
//! arguments) carries the tag of the team instance that minted it. A reference minted by a
//! previous instance therefore cannot silently resolve against the current one: the store
//! compares tags and reports an explicit reset instead.

use serde::Deserialize;
use serde::Serialize;
use std::fmt;
use std::str::FromStr;
use uuid::Uuid;

/// The instance tag carries the whole UUID, not a prefix of it.
///
/// A shorter tag would make "does this reference belong to the current instance?" a probabilistic
/// question, and the answer has to be exact: an old reference must never resolve against a new
/// instance just because their prefixes happened to agree.
const INSTANCE_TAG_LEN: usize = 32;

/// Identity of one live team instance.
///
/// A new instance is opened when a root tree starts, or when a team reference cannot be matched
/// to a surviving `TeamState`. Members unloaded and reloaded inside the same live root tree keep
/// the original instance.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
pub struct TeamInstanceId(Uuid);

impl TeamInstanceId {
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }

    pub fn tag(&self) -> InstanceTag {
        let hex = self.0.simple().to_string();
        let mut bytes = [0u8; INSTANCE_TAG_LEN];
        bytes.copy_from_slice(hex.as_bytes());
        InstanceTag(bytes)
    }
}

impl Default for TeamInstanceId {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for TeamInstanceId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.tag())
    }
}

/// Printable form of a [`TeamInstanceId`], embedded in every reference string so that instance
/// membership is checkable from the reference alone.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
pub struct InstanceTag([u8; INSTANCE_TAG_LEN]);

impl fmt::Display for InstanceTag {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // The bytes always come from a hex rendering of a UUID, so they are valid ASCII.
        f.write_str(std::str::from_utf8(&self.0).unwrap_or("<invalid instance tag>"))
    }
}

impl FromStr for InstanceTag {
    type Err = ReferenceParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let bytes = value.as_bytes();
        if bytes.len() != INSTANCE_TAG_LEN || !value.chars().all(|c| c.is_ascii_hexdigit()) {
            return Err(ReferenceParseError);
        }
        let mut tag = [0u8; INSTANCE_TAG_LEN];
        tag.copy_from_slice(bytes);
        Ok(Self(tag))
    }
}

/// Monotonic version counter for the whole team state.
///
/// Every committed mutation bumps it. Submissions echo the revision their view was built from so
/// the store can tell a fresh append from one authored against a stale view.
#[derive(Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
pub struct TeamRevision(u64);

impl TeamRevision {
    pub const INITIAL: Self = Self(0);

    pub fn get(&self) -> u64 {
        self.0
    }

    pub fn from_raw(raw: u64) -> Self {
        Self(raw)
    }

    pub(crate) fn next(self) -> Self {
        Self(self.0.saturating_add(1))
    }
}

impl fmt::Display for TeamRevision {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// Team-level identity for one thing the team keeps track of.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
pub struct EventId {
    instance: InstanceTag,
    ordinal: u32,
}

impl EventId {
    pub(crate) fn new(instance: InstanceTag, ordinal: u32) -> Self {
        Self { instance, ordinal }
    }

    pub fn instance(&self) -> InstanceTag {
        self.instance
    }

    pub(crate) fn ordinal(&self) -> u32 {
        self.ordinal
    }
}

impl fmt::Display for EventId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let Self { instance, ordinal } = self;
        write!(f, "evt-{ordinal}-{instance}")
    }
}

impl FromStr for EventId {
    type Err = ReferenceParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let rest = value.strip_prefix("evt-").ok_or(ReferenceParseError)?;
        let (ordinal, instance) = rest.split_once('-').ok_or(ReferenceParseError)?;
        Ok(Self {
            instance: instance.parse()?,
            ordinal: ordinal.parse().map_err(|_| ReferenceParseError)?,
        })
    }
}

/// Identity of one immutable authored entry under an [`EventId`].
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
pub struct VersionId {
    instance: InstanceTag,
    event_ordinal: u32,
    ordinal: u32,
}

impl VersionId {
    pub(crate) fn new(instance: InstanceTag, event_ordinal: u32, ordinal: u32) -> Self {
        Self {
            instance,
            event_ordinal,
            ordinal,
        }
    }

    pub fn instance(&self) -> InstanceTag {
        self.instance
    }

    pub fn event_id(&self) -> EventId {
        EventId::new(self.instance, self.event_ordinal)
    }

    pub(crate) fn ordinal(&self) -> u32 {
        self.ordinal
    }
}

impl fmt::Display for VersionId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let Self {
            instance,
            event_ordinal,
            ordinal,
        } = self;
        write!(f, "ver-{event_ordinal}.{ordinal}-{instance}")
    }
}

impl FromStr for VersionId {
    type Err = ReferenceParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let rest = value.strip_prefix("ver-").ok_or(ReferenceParseError)?;
        let (ordinals, instance) = rest.split_once('-').ok_or(ReferenceParseError)?;
        let (event_ordinal, ordinal) = ordinals.split_once('.').ok_or(ReferenceParseError)?;
        Ok(Self {
            instance: instance.parse()?,
            event_ordinal: event_ordinal.parse().map_err(|_| ReferenceParseError)?,
            ordinal: ordinal.parse().map_err(|_| ReferenceParseError)?,
        })
    }
}

/// Identity of one route grant under an [`EventId`].
///
/// A route is minted per event, so its reference carries the event it belongs to and cannot be
/// confused with a version of the same event.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
pub struct RouteId {
    instance: InstanceTag,
    event_ordinal: u32,
    ordinal: u32,
}

impl RouteId {
    pub(crate) fn new(instance: InstanceTag, event_ordinal: u32, ordinal: u32) -> Self {
        Self {
            instance,
            event_ordinal,
            ordinal,
        }
    }

    pub fn instance(&self) -> InstanceTag {
        self.instance
    }

    pub fn event_id(&self) -> EventId {
        EventId::new(self.instance, self.event_ordinal)
    }
}

impl fmt::Display for RouteId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let Self {
            instance,
            event_ordinal,
            ordinal,
        } = self;
        write!(f, "rte-{event_ordinal}.{ordinal}-{instance}")
    }
}

impl FromStr for RouteId {
    type Err = ReferenceParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let rest = value.strip_prefix("rte-").ok_or(ReferenceParseError)?;
        let (ordinals, instance) = rest.split_once('-').ok_or(ReferenceParseError)?;
        let (event_ordinal, ordinal) = ordinals.split_once('.').ok_or(ReferenceParseError)?;
        Ok(Self {
            instance: instance.parse()?,
            event_ordinal: event_ordinal.parse().map_err(|_| ReferenceParseError)?,
            ordinal: ordinal.parse().map_err(|_| ReferenceParseError)?,
        })
    }
}

/// A reference string that is not a well-formed team reference at all.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReferenceParseError;

impl fmt::Display for ReferenceParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("not a valid team reference")
    }
}

impl std::error::Error for ReferenceParseError {}

#[cfg(test)]
#[path = "ids_tests.rs"]
mod tests;
