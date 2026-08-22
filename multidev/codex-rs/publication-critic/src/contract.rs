use crate::ContractFailure;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Verdict {
    Pass,
    Rewrite,
}

#[derive(Clone, Copy)]
pub(crate) enum RequiredText {
    Yes,
    No,
}

pub(crate) fn validate_text(
    value: &str,
    max_scalars: usize,
    max_bytes: usize,
    required: RequiredText,
) -> Result<(), ContractFailure> {
    if matches!(required, RequiredText::Yes) && value.trim().is_empty() {
        return Err(ContractFailure::InvalidPacket);
    }
    if value.len() > max_bytes || value.chars().count() > max_scalars {
        return Err(ContractFailure::InvalidPacket);
    }
    Ok(())
}
