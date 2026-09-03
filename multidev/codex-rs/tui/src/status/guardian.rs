//! Guardian override summary for the `/status` card.
//!
//! RONDO extends upstream's `[auto_review]` table with explicit model, model-provider,
//! reasoning-effort and evidence-directory overrides. This module turns whatever the effective
//! [`Config`] actually loaded into one bounded summary line.
//!
//! The summary deliberately reports two things only: which overrides are loaded, and whether the
//! configured reviewer is the one that would consume them. It never claims that a review ran, and
//! it never infers the model identity a review actually used -- Guardian resolves that at review
//! time from the catalog and the provider, and `[auto_review].model` is only one input to it.

use codex_protocol::config_types::ApprovalsReviewer;

use crate::legacy_core::config::Config;
use crate::text_formatting::truncate_text;

use super::helpers::format_directory_display;

/// Config values are free-form strings, so cap each one. Without this a long model slug or
/// evidence path would stretch the transcript rendering, which is laid out at `u16::MAX` width.
const MAX_OVERRIDE_WIDTH: usize = 48;

/// Summarizes the Guardian overrides the effective config loaded, or `None` when it loaded none.
///
/// The returned string is the `/status` value for the `Guardian config` field.
pub(crate) fn guardian_config_summary(config: &Config) -> Option<String> {
    let mut overrides: Vec<String> = Vec::new();

    if let Some(model) = config.guardian_model_config.as_deref() {
        overrides.push(format!(
            "model {}",
            truncate_text(model, MAX_OVERRIDE_WIDTH)
        ));
    }
    if let Some(provider) = config.guardian_model_provider_config.as_deref() {
        overrides.push(format!(
            "provider {}",
            truncate_text(provider, MAX_OVERRIDE_WIDTH)
        ));
    }
    if let Some(effort) = config.guardian_reasoning_effort_config.as_ref() {
        overrides.push(format!(
            "reasoning effort {}",
            truncate_text(effort.as_str(), MAX_OVERRIDE_WIDTH)
        ));
    }
    if let Some(evidence_dir) = config.guardian_evidence_dir.as_ref() {
        overrides.push(format!(
            "evidence dir {}",
            format_directory_display(evidence_dir.as_path(), Some(MAX_OVERRIDE_WIDTH))
        ));
    }

    if overrides.is_empty() {
        return None;
    }

    let loaded = overrides.join(", ");
    Some(match config.approvals_reviewer {
        ApprovalsReviewer::AutoReview => format!("loaded for reviewer auto_review ({loaded})"),
        ApprovalsReviewer::User => format!("loaded, unused by reviewer user ({loaded})"),
    })
}
