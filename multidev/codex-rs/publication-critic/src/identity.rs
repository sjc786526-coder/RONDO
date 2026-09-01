use crate::CloudFiveDimensionDecisions;
use crate::ContractFailure;
use crate::ScoreFailureKind;
use crate::Verdict;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::Serializer;
use std::fmt;

const MAX_IDENTITY_COMPONENT_BYTES: usize = 128;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProtocolVersion {
    RondoPublicationCriticV1,
}

#[derive(Clone, Eq, Hash, PartialEq)]
pub struct IdentityComponent(String);

impl IdentityComponent {
    pub fn new(value: impl Into<String>) -> Result<Self, ContractFailure> {
        let value = value.into();
        if value.is_empty()
            || value.len() > MAX_IDENTITY_COMPONENT_BYTES
            || !value.bytes().all(|byte| byte.is_ascii_graphic())
        {
            return Err(ContractFailure::InvalidIdentity);
        }
        Ok(Self(value))
    }

    fn trusted_literal(value: &str) -> Self {
        Self(value.to_string())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for IdentityComponent {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_tuple("IdentityComponent").field(&self.0).finish()
    }
}

impl Serialize for IdentityComponent {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&self.0)
    }
}

impl<'de> Deserialize<'de> for IdentityComponent {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Copy, PartialEq)]
pub struct FiniteValue(f64);

impl FiniteValue {
    pub fn new(value: f64) -> Result<Self, ContractFailure> {
        if !value.is_finite() {
            return Err(ContractFailure::InvalidScore(ScoreFailureKind::NonFinite));
        }
        Ok(Self(if value == 0.0 { 0.0 } else { value }))
    }

    fn trusted_literal(value: f64) -> Self {
        Self(value)
    }

    pub fn get(self) -> f64 {
        self.0
    }
}

impl fmt::Debug for FiniteValue {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}

impl Serialize for FiniteValue {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_f64(self.0)
    }
}

impl<'de> Deserialize<'de> for FiniteValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = f64::deserialize(deserializer)?;
        Self::new(value).map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ComponentIdentity {
    name: IdentityComponent,
    revision: IdentityComponent,
}

impl ComponentIdentity {
    pub fn new(
        name: impl Into<String>,
        revision: impl Into<String>,
    ) -> Result<Self, ContractFailure> {
        Ok(Self {
            name: IdentityComponent::new(name)?,
            revision: IdentityComponent::new(revision)?,
        })
    }

    fn trusted_literal(name: &str, revision: &str) -> Self {
        Self {
            name: IdentityComponent::trusted_literal(name),
            revision: IdentityComponent::trusted_literal(revision),
        }
    }

    pub fn name(&self) -> &str {
        self.name.as_str()
    }

    pub fn revision(&self) -> &str {
        self.revision.as_str()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QualificationIdentity {
    pub packet_schema: ComponentIdentity,
    pub rubric: ComponentIdentity,
}

impl QualificationIdentity {
    pub fn new(packet_schema: ComponentIdentity, rubric: ComponentIdentity) -> Self {
        Self {
            packet_schema,
            rubric,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelIdentity {
    pub model: ComponentIdentity,
    pub tokenizer: ComponentIdentity,
}

impl ModelIdentity {
    pub fn new(model: ComponentIdentity, tokenizer: ComponentIdentity) -> Self {
        Self { model, tokenizer }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PassRule {
    ScoreGreaterThanOrEqualToThreshold,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ScoreDomain {
    min: FiniteValue,
    max: FiniteValue,
}

impl ScoreDomain {
    pub fn new(min: f64, max: f64) -> Result<Self, ContractFailure> {
        let domain = Self {
            min: FiniteValue::new(min)?,
            max: FiniteValue::new(max)?,
        };
        domain.validate()?;
        Ok(domain)
    }

    fn validate(&self) -> Result<(), ContractFailure> {
        if self.min.get() >= self.max.get() {
            return Err(ContractFailure::InvalidScoringConfiguration);
        }
        Ok(())
    }

    pub fn min(&self) -> f64 {
        self.min.get()
    }

    pub fn max(&self) -> f64 {
        self.max.get()
    }

    fn contains(&self, score: f64) -> bool {
        (self.min.get()..=self.max.get()).contains(&score)
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ScoringIdentity {
    pub definition: ComponentIdentity,
    pub input_template: ComponentIdentity,
    pub scalar_projection: ComponentIdentity,
    pub domain: ScoreDomain,
    threshold: FiniteValue,
    pub pass_rule: PassRule,
}

impl ScoringIdentity {
    pub fn new(
        definition: ComponentIdentity,
        input_template: ComponentIdentity,
        scalar_projection: ComponentIdentity,
        domain: ScoreDomain,
        threshold: f64,
    ) -> Result<Self, ContractFailure> {
        let identity = Self {
            definition,
            input_template,
            scalar_projection,
            domain,
            threshold: FiniteValue::new(threshold)?,
            pass_rule: PassRule::ScoreGreaterThanOrEqualToThreshold,
        };
        identity.validate()?;
        Ok(identity)
    }

    pub fn validate(&self) -> Result<(), ContractFailure> {
        self.domain.validate()?;
        if !self.domain.contains(self.threshold.get()) {
            return Err(ContractFailure::InvalidScoringConfiguration);
        }
        Ok(())
    }

    pub fn threshold(&self) -> f64 {
        self.threshold.get()
    }

    pub fn verdict_for_scores(&self, scores: &[f64]) -> Result<Verdict, ContractFailure> {
        if scores.len() != 1 {
            return Err(ContractFailure::InvalidScore(ScoreFailureKind::Shape));
        }
        let score = scores[0];
        if !score.is_finite() {
            return Err(ContractFailure::InvalidScore(ScoreFailureKind::NonFinite));
        }
        if !self.domain.contains(score) {
            return Err(ContractFailure::InvalidScore(ScoreFailureKind::OutOfDomain));
        }
        Ok(if score >= self.threshold.get() {
            Verdict::Pass
        } else {
            Verdict::Rewrite
        })
    }
}

/// Discrete five-head conjunction. This identity has no domain, threshold, or
/// scalar projection: the typed verdict is exactly the task-v2 §3 gate.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FiveDimensionPassRule {
    DiscreteNonCompensatingConjunction,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FiveDimensionScoringIdentity {
    pub definition: ComponentIdentity,
    pub input_template: ComponentIdentity,
    pub decision_projection: ComponentIdentity,
    pub pass_rule: FiveDimensionPassRule,
}

impl FiveDimensionScoringIdentity {
    pub fn new(
        definition: ComponentIdentity,
        input_template: ComponentIdentity,
        decision_projection: ComponentIdentity,
    ) -> Self {
        Self {
            definition,
            input_template,
            decision_projection,
            pass_rule: FiveDimensionPassRule::DiscreteNonCompensatingConjunction,
        }
    }

    pub fn validate(&self) -> Result<(), ContractFailure> {
        Ok(())
    }

    pub fn verdict_for_decisions(&self, decisions: &CloudFiveDimensionDecisions) -> Verdict {
        decisions.product_verdict()
    }
}

/// Product scoring contract. Untagged so a historical scalar identity stays
/// byte-identical; the five-dimension variant cannot carry a threshold.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(untagged)]
pub enum ScoringContract {
    FiveDimension(FiveDimensionScoringIdentity),
    Scalar(ScoringIdentity),
}

impl ScoringContract {
    pub fn validate(&self) -> Result<(), ContractFailure> {
        match self {
            Self::FiveDimension(identity) => identity.validate(),
            Self::Scalar(identity) => identity.validate(),
        }
    }

    pub fn as_scalar(&self) -> Option<&ScoringIdentity> {
        match self {
            Self::Scalar(identity) => Some(identity),
            Self::FiveDimension(_) => None,
        }
    }

    pub fn as_scalar_mut(&mut self) -> Option<&mut ScoringIdentity> {
        match self {
            Self::Scalar(identity) => Some(identity),
            Self::FiveDimension(_) => None,
        }
    }

    pub fn as_five_dimension(&self) -> Option<&FiveDimensionScoringIdentity> {
        match self {
            Self::FiveDimension(identity) => Some(identity),
            Self::Scalar(_) => None,
        }
    }

    pub fn definition(&self) -> &ComponentIdentity {
        match self {
            Self::FiveDimension(identity) => &identity.definition,
            Self::Scalar(identity) => &identity.definition,
        }
    }

    pub fn input_template(&self) -> &ComponentIdentity {
        match self {
            Self::FiveDimension(identity) => &identity.input_template,
            Self::Scalar(identity) => &identity.input_template,
        }
    }
}

impl From<ScoringIdentity> for ScoringContract {
    fn from(value: ScoringIdentity) -> Self {
        Self::Scalar(value)
    }
}

impl From<FiveDimensionScoringIdentity> for ScoringContract {
    fn from(value: FiveDimensionScoringIdentity) -> Self {
        Self::FiveDimension(value)
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ServiceIdentity {
    pub protocol: ProtocolVersion,
    pub implementation: ComponentIdentity,
    pub qualification: QualificationIdentity,
    pub model: ModelIdentity,
    pub scoring: ScoringContract,
}

impl ServiceIdentity {
    pub fn new(
        implementation: ComponentIdentity,
        qualification: QualificationIdentity,
        model: ModelIdentity,
        scoring: impl Into<ScoringContract>,
    ) -> Result<Self, ContractFailure> {
        let scoring = scoring.into();
        scoring.validate()?;
        Ok(Self {
            protocol: ProtocolVersion::RondoPublicationCriticV1,
            implementation,
            qualification,
            model,
            scoring,
        })
    }

    pub fn validate(&self) -> Result<(), ContractFailure> {
        self.scoring.validate()
    }
}

pub fn controlled_test_identity() -> ServiceIdentity {
    ServiceIdentity {
        protocol: ProtocolVersion::RondoPublicationCriticV1,
        implementation: ComponentIdentity::trusted_literal(
            "rondo-publication-critic-service",
            "v1",
        ),
        qualification: QualificationIdentity {
            packet_schema: ComponentIdentity::trusted_literal("rondo-publication-packet", "v1"),
            rubric: ComponentIdentity::trusted_literal("rondo-publication-qualification", "v1"),
        },
        model: ModelIdentity {
            model: ComponentIdentity::trusted_literal("rondo-controlled-test-scorer", "v1"),
            tokenizer: ComponentIdentity::trusted_literal("rondo-controlled-test-tokenizer", "v1"),
        },
        scoring: ScoringContract::Scalar(ScoringIdentity {
            definition: ComponentIdentity::trusted_literal("controlled-test-scalar", "v1"),
            input_template: ComponentIdentity::trusted_literal(
                "rondo-publication-packet-render",
                "v1",
            ),
            scalar_projection: ComponentIdentity::trusted_literal("single-scalar", "v1"),
            domain: ScoreDomain {
                min: FiniteValue::trusted_literal(/*value*/ 0.0),
                max: FiniteValue::trusted_literal(/*value*/ 1.0),
            },
            threshold: FiniteValue::trusted_literal(/*value*/ 0.5),
            pass_rule: PassRule::ScoreGreaterThanOrEqualToThreshold,
        }),
    }
}
