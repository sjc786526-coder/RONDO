use unicode_width::UnicodeWidthStr;

use super::VERSION_PLACEHOLDER;
use super::sanitize_cli_version;
use crate::version::CODEX_CLI_VERSION;

#[test]
fn cli_version_sanitizer_only_rewrites_known_rendered_shapes() {
    let unrelated = format!("model-{CODEX_CLI_VERSION}-candidate");
    assert_eq!(sanitize_cli_version(unrelated.clone()), unrelated);

    let update = format!("Update {CODEX_CLI_VERSION} -> 9.9.9");
    assert_eq!(
        sanitize_cli_version(update),
        format!("Update {VERSION_PLACEHOLDER} -> 9.9.9")
    );

    let original_padding = 12;
    let framed = format!(
        "│ >_ OpenAI Codex (v{CODEX_CLI_VERSION}){}│",
        " ".repeat(original_padding)
    );
    let sanitized = sanitize_cli_version(framed.clone());
    let expected_padding = original_padding + UnicodeWidthStr::width(CODEX_CLI_VERSION)
        - UnicodeWidthStr::width(VERSION_PLACEHOLDER);
    assert_eq!(
        sanitized,
        format!(
            "│ >_ OpenAI Codex (v{VERSION_PLACEHOLDER}){}│",
            " ".repeat(expected_padding)
        )
    );
    assert_eq!(
        UnicodeWidthStr::width(sanitized.as_str()),
        UnicodeWidthStr::width(framed.as_str())
    );
}
