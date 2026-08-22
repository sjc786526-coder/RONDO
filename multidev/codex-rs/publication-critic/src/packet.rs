use crate::ContractFailure;
use crate::QualificationIdentity;
use crate::contract::RequiredText;
use crate::contract::validate_text;
use serde::Deserialize;
use serde::Serialize;
use std::fmt;

pub const MAX_TITLE_SCALARS: usize = 213;
pub const MAX_TITLE_BYTES: usize = 815;
pub const MAX_SUMMARY_SCALARS: usize = 2_013;
pub const MAX_SUMMARY_BYTES: usize = 8_015;
pub const MAX_HANDOFF_SCALARS: usize = 1_013;
pub const MAX_HANDOFF_BYTES: usize = 4_015;
pub const MAX_PRIOR_PUBLICATIONS: usize = 4;
pub const MAX_VISIBLE_FACT_REFERENCES: u16 = 32;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ActorRole {
    Root,
    Member,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TargetKind {
    NewEvent,
    ExistingEvent,
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalScope {
    title: String,
}

impl LocalScope {
    pub fn new(title: impl Into<String>) -> Result<Self, ContractFailure> {
        let scope = Self {
            title: title.into(),
        };
        validate_text(
            &scope.title,
            MAX_TITLE_SCALARS,
            MAX_TITLE_BYTES,
            RequiredText::Yes,
        )?;
        Ok(scope)
    }

    pub fn title(&self) -> &str {
        &self.title
    }
}

impl fmt::Debug for LocalScope {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LocalScope")
            .field("title_scalars", &self.title.chars().count())
            .field("title_bytes", &self.title.len())
            .finish()
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PublicationCandidate {
    summary: String,
    handoff: Option<String>,
}

impl PublicationCandidate {
    pub fn new(summary: impl Into<String>) -> Result<Self, ContractFailure> {
        let candidate = Self {
            summary: summary.into(),
            handoff: None,
        };
        candidate.validate()?;
        Ok(candidate)
    }

    pub fn with_handoff(mut self, handoff: impl Into<String>) -> Result<Self, ContractFailure> {
        self.handoff = Some(handoff.into());
        self.validate()?;
        Ok(self)
    }

    pub fn summary(&self) -> &str {
        &self.summary
    }

    pub fn handoff(&self) -> Option<&str> {
        self.handoff.as_deref()
    }

    fn validate(&self) -> Result<(), ContractFailure> {
        validate_text(
            &self.summary,
            MAX_SUMMARY_SCALARS,
            MAX_SUMMARY_BYTES,
            RequiredText::Yes,
        )?;
        if let Some(handoff) = &self.handoff {
            validate_text(
                handoff,
                MAX_HANDOFF_SCALARS,
                MAX_HANDOFF_BYTES,
                RequiredText::No,
            )?;
        }
        Ok(())
    }
}

impl fmt::Debug for PublicationCandidate {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("PublicationCandidate")
            .field("summary_scalars", &self.summary.chars().count())
            .field("summary_bytes", &self.summary.len())
            .field("handoff_present", &self.handoff.is_some())
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ContextFreshness {
    Current,
    KnownStale,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, tag = "state", rename_all = "snake_case")]
pub enum ContinuityCoverage {
    Complete,
    Partial { omitted_count: Option<u32> },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, tag = "state", rename_all = "snake_case")]
pub enum FactReferenceSummary {
    None,
    Present {
        visible_count: u16,
        count_omitted: bool,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FactReferenceCountCoverage {
    Complete,
    Omitted,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ObservationAvailability {
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PriorEvidence {
    pub fact_references: FactReferenceSummary,
    pub observation_availability: ObservationAvailability,
}

impl PriorEvidence {
    pub fn none() -> Self {
        Self {
            fact_references: FactReferenceSummary::None,
            observation_availability: ObservationAvailability::Unknown,
        }
    }

    pub fn present(
        visible_count: u16,
        count_coverage: FactReferenceCountCoverage,
    ) -> Result<Self, ContractFailure> {
        let evidence = Self {
            fact_references: FactReferenceSummary::Present {
                visible_count,
                count_omitted: matches!(count_coverage, FactReferenceCountCoverage::Omitted),
            },
            observation_availability: ObservationAvailability::Unknown,
        };
        evidence.validate()?;
        Ok(evidence)
    }

    fn validate(&self) -> Result<(), ContractFailure> {
        if let FactReferenceSummary::Present { visible_count, .. } = &self.fact_references
            && !(1..=MAX_VISIBLE_FACT_REFERENCES).contains(visible_count)
        {
            return Err(ContractFailure::InvalidPacket);
        }
        Ok(())
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PriorPublication {
    summary: String,
    handoff: Option<String>,
    pub evidence: PriorEvidence,
}

impl PriorPublication {
    pub fn new(
        summary: impl Into<String>,
        evidence: PriorEvidence,
    ) -> Result<Self, ContractFailure> {
        let publication = Self {
            summary: summary.into(),
            handoff: None,
            evidence,
        };
        publication.validate()?;
        Ok(publication)
    }

    pub fn with_handoff(mut self, handoff: impl Into<String>) -> Result<Self, ContractFailure> {
        self.handoff = Some(handoff.into());
        self.validate()?;
        Ok(self)
    }

    fn validate(&self) -> Result<(), ContractFailure> {
        validate_text(
            &self.summary,
            MAX_SUMMARY_SCALARS,
            MAX_SUMMARY_BYTES,
            RequiredText::Yes,
        )?;
        if let Some(handoff) = &self.handoff {
            validate_text(
                handoff,
                MAX_HANDOFF_SCALARS,
                MAX_HANDOFF_BYTES,
                RequiredText::No,
            )?;
        }
        self.evidence.validate()
    }
}

impl fmt::Debug for PriorPublication {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("PriorPublication")
            .field("summary_scalars", &self.summary.chars().count())
            .field("summary_bytes", &self.summary.len())
            .field("handoff_present", &self.handoff.is_some())
            .field("evidence", &self.evidence)
            .finish()
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, tag = "state", rename_all = "snake_case")]
pub enum ContinuityContext {
    NotApplicable,
    Available {
        source_team_revision: u64,
        freshness: ContextFreshness,
        coverage: ContinuityCoverage,
        prior_publications: Vec<PriorPublication>,
    },
    Unavailable {
        last_known_revision: Option<u64>,
        freshness: ContextFreshness,
    },
}

impl ContinuityContext {
    pub fn available(
        source_team_revision: u64,
        freshness: ContextFreshness,
        coverage: ContinuityCoverage,
        prior_publications: Vec<PriorPublication>,
    ) -> Result<Self, ContractFailure> {
        let context = Self::Available {
            source_team_revision,
            freshness,
            coverage,
            prior_publications,
        };
        context.validate()?;
        Ok(context)
    }

    pub fn unavailable(last_known_revision: Option<u64>, freshness: ContextFreshness) -> Self {
        Self::Unavailable {
            last_known_revision,
            freshness,
        }
    }

    fn validate(&self) -> Result<(), ContractFailure> {
        match self {
            Self::NotApplicable => Ok(()),
            Self::Available {
                coverage,
                prior_publications,
                ..
            } => {
                if prior_publications.len() > MAX_PRIOR_PUBLICATIONS {
                    return Err(ContractFailure::InvalidPacket);
                }
                if matches!(
                    coverage,
                    ContinuityCoverage::Partial {
                        omitted_count: Some(0)
                    }
                ) {
                    return Err(ContractFailure::InvalidPacket);
                }
                prior_publications
                    .iter()
                    .try_for_each(PriorPublication::validate)
            }
            Self::Unavailable { freshness, .. } => {
                if matches!(freshness, ContextFreshness::Current) {
                    return Err(ContractFailure::InvalidPacket);
                }
                Ok(())
            }
        }
    }
}

impl fmt::Debug for ContinuityContext {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotApplicable => f.write_str("ContinuityContext::NotApplicable"),
            Self::Available {
                source_team_revision,
                freshness,
                coverage,
                prior_publications,
            } => f
                .debug_struct("ContinuityContext::Available")
                .field("source_team_revision", source_team_revision)
                .field("freshness", freshness)
                .field("coverage", coverage)
                .field("prior_publication_count", &prior_publications.len())
                .finish(),
            Self::Unavailable {
                last_known_revision,
                freshness,
            } => f
                .debug_struct("ContinuityContext::Unavailable")
                .field("last_known_revision", last_known_revision)
                .field("freshness", freshness)
                .finish(),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SemanticEntailmentPolicy {
    NotEvaluated,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CandidateEvidenceWindow {
    NotFrozenBeforeCommit,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceV1 {
    pub semantic_entailment: SemanticEntailmentPolicy,
    pub candidate_window: CandidateEvidenceWindow,
}

impl EvidenceV1 {
    fn fixed() -> Self {
        Self {
            semantic_entailment: SemanticEntailmentPolicy::NotEvaluated,
            candidate_window: CandidateEvidenceWindow::NotFrozenBeforeCommit,
        }
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PublicationPacket {
    pub qualification: QualificationIdentity,
    pub actor_role: ActorRole,
    pub target_kind: TargetKind,
    pub local_scope: LocalScope,
    pub candidate: PublicationCandidate,
    pub continuity: ContinuityContext,
    pub evidence_v1: EvidenceV1,
}

impl PublicationPacket {
    pub fn new(
        qualification: QualificationIdentity,
        actor_role: ActorRole,
        target_kind: TargetKind,
        local_scope: LocalScope,
        candidate: PublicationCandidate,
        continuity: ContinuityContext,
    ) -> Result<Self, ContractFailure> {
        let packet = Self {
            qualification,
            actor_role,
            target_kind,
            local_scope,
            candidate,
            continuity,
            evidence_v1: EvidenceV1::fixed(),
        };
        packet.validate()?;
        Ok(packet)
    }

    pub fn validate(&self) -> Result<(), ContractFailure> {
        validate_text(
            self.local_scope.title(),
            MAX_TITLE_SCALARS,
            MAX_TITLE_BYTES,
            RequiredText::Yes,
        )?;
        self.candidate.validate()?;
        self.continuity.validate()?;
        match (&self.target_kind, &self.continuity) {
            (TargetKind::NewEvent, ContinuityContext::NotApplicable)
            | (
                TargetKind::ExistingEvent,
                ContinuityContext::Available { .. } | ContinuityContext::Unavailable { .. },
            ) => Ok(()),
            (TargetKind::NewEvent, _)
            | (TargetKind::ExistingEvent, ContinuityContext::NotApplicable) => {
                Err(ContractFailure::InvalidPacket)
            }
        }
    }
}

impl fmt::Debug for PublicationPacket {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("PublicationPacket")
            .field("qualification", &self.qualification)
            .field("actor_role", &self.actor_role)
            .field("target_kind", &self.target_kind)
            .field("local_scope", &self.local_scope)
            .field("candidate", &self.candidate)
            .field("continuity", &self.continuity)
            .field("evidence_v1", &self.evidence_v1)
            .finish()
    }
}
