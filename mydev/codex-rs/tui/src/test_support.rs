//! Test-only helpers shared across the TUI crate.

use std::sync::LazyLock;

use codex_models_manager::bundled_models_response;
use codex_protocol::openai_models::ModelPreset;
pub(crate) use codex_utils_absolute_path::test_support::PathBufExt;
pub(crate) use codex_utils_absolute_path::test_support::test_path_buf;
use serde::Serialize;
use serde::de::DeserializeOwned;
use unicode_width::UnicodeWidthStr;

use crate::version::CODEX_CLI_VERSION;

/// Stand-in for the compiled-in CLI version inside rendered snapshots.
pub(crate) const VERSION_PLACEHOLDER: &str = "[[version]]";

pub(crate) static TEST_MODEL_PRESETS: LazyLock<Vec<ModelPreset>> = LazyLock::new(|| {
    let mut response = bundled_models_response()
        .unwrap_or_else(|err| panic!("bundled models.json should parse: {err}"));
    response.models.sort_by_key(|model| model.priority);
    let mut presets: Vec<ModelPreset> = response.models.into_iter().map(Into::into).collect();
    ModelPreset::mark_default_by_picker_visibility(&mut presets);
    presets
});

pub(crate) fn test_path_display(path: &str) -> String {
    test_path_buf(path).display().to_string()
}

pub(crate) fn session_source_cli<T>() -> T
where
    T: DeserializeOwned,
{
    from_app_server_wire(codex_app_server_protocol::SessionSource::Cli)
}

pub(crate) fn skill_scope_user<T>() -> T
where
    T: DeserializeOwned,
{
    from_app_server_wire(codex_app_server_protocol::SkillScope::User)
}

pub(crate) fn skill_scope_repo<T>() -> T
where
    T: DeserializeOwned,
{
    from_app_server_wire(codex_app_server_protocol::SkillScope::Repo)
}

/// Replaces the compiled-in CLI version in a rendered line with a stable placeholder.
///
/// `CARGO_PKG_VERSION` changes on every release tag, so any snapshot that renders the
/// version drifts whenever the upstream baseline moves. Rendered lines usually sit inside
/// a fixed-width box, so the padding in front of the trailing border is rebuilt to keep the
/// frame aligned no matter how wide the real version is.
pub(crate) fn sanitize_cli_version(line: String) -> String {
    if !line.contains(CODEX_CLI_VERSION) {
        return line;
    }
    let original_width = UnicodeWidthStr::width(line.as_str());
    let replaced = line.replace(CODEX_CLI_VERSION, VERSION_PLACEHOLDER);
    let Some(border) = replaced.rfind('│') else {
        return replaced;
    };
    let (head, border) = replaced.split_at(border);
    let head = head.trim_end_matches(' ');
    let padding = original_width
        .saturating_sub(UnicodeWidthStr::width(head) + UnicodeWidthStr::width(border));
    format!("{head}{}{border}", " ".repeat(padding))
}

/// Applies [`sanitize_cli_version`] to every rendered line.
pub(crate) fn sanitize_cli_version_lines(lines: Vec<String>) -> Vec<String> {
    lines.into_iter().map(sanitize_cli_version).collect()
}

fn from_app_server_wire<T>(value: impl Serialize) -> T
where
    T: DeserializeOwned,
{
    serde_json::to_value(value)
        .and_then(serde_json::from_value)
        .unwrap_or_else(|err| {
            panic!("app-server wire value should map to legacy helper type: {err}")
        })
}
