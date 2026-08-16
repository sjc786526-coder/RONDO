//! Tool specs for the team world state surface.

use codex_team_state::MAX_HISTORY_LIMIT;
use codex_tools::JsonSchema;
use codex_tools::ResponsesApiTool;
use codex_tools::ToolSpec;
use serde_json::json;
use std::collections::BTreeMap;

pub(crate) fn create_team_publish_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "event_id".to_string(),
            JsonSchema::string(Some(
                "Existing event to add a version to. Omit to open a new event.".to_string(),
            )),
        ),
        (
            "title".to_string(),
            JsonSchema::string(Some(
                "Short title for a new event. Required when event_id is omitted.".to_string(),
            )),
        ),
        (
            "summary".to_string(),
            JsonSchema::string(Some(
                "What you concluded. This is written once and never rewritten.".to_string(),
            )),
        ),
        (
            "handoff".to_string(),
            JsonSchema::string(Some(
                "What another participant should do with this, if anything.".to_string(),
            )),
        ),
        (
            "based_on_revision".to_string(),
            JsonSchema::integer(Some(
                "The team revision shown in the active world index you acted on. Omit only if you have not seen one."
                    .to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "team_publish".to_string(),
        description:
            "Publish a semantic checkpoint to the team's canonical state: open a new event or append a version to an existing one. The harness keeps it, so you do not have to remember or restate it. Publish when you have reached a conclusion the team needs, not on a schedule."
                .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["summary".to_string()]),
            Some(false.into()),
        ),
        output_schema: Some(publish_output_schema()),
    })
}

pub(crate) fn create_team_update_tool() -> ToolSpec {
    let target = JsonSchema::object(
        BTreeMap::from([
            (
                "version_id".to_string(),
                JsonSchema::string(Some("Version to update.".to_string())),
            ),
            (
                "expect_producer_state".to_string(),
                JsonSchema::string_enum(
                    vec![json!("open"), json!("closed")],
                    Some("The producer state you believe this version currently has.".to_string()),
                ),
            ),
            (
                "expect_root_state".to_string(),
                JsonSchema::string_enum(
                    vec![json!("pending"), json!("tracking"), json!("resolved")],
                    Some("The root state you believe this version currently has.".to_string()),
                ),
            ),
            (
                "set_producer_state".to_string(),
                JsonSchema::string_enum(
                    vec![json!("closed")],
                    Some(
                        "Close your own version. Closing is final; publish a new version if the matter becomes relevant again."
                            .to_string(),
                    ),
                ),
            ),
            (
                "set_root_state".to_string(),
                JsonSchema::string_enum(
                    vec![json!("pending"), json!("tracking"), json!("resolved")],
                    Some(
                        "Root only. `resolved` ends your coordination; it does not close the author's item."
                            .to_string(),
                    ),
                ),
            ),
        ]),
        Some(vec![
            "version_id".to_string(),
            "expect_producer_state".to_string(),
            "expect_root_state".to_string(),
        ]),
        Some(false.into()),
    );

    let properties = BTreeMap::from([(
        "targets".to_string(),
        JsonSchema::array(
            target,
            Some(
                "Only these versions change. Anything you do not list keeps its current state."
                    .to_string(),
            ),
        ),
    )]);

    ToolSpec::Function(ResponsesApiTool {
        name: "team_update".to_string(),
        description:
            "Update the lifecycle of specific team versions. Producer state is yours to close on your own versions; root state is the root's coordination attention. The two are independent. Each target states the state you believe it has, and the update is refused with the current state if it has already moved."
                .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["targets".to_string()]),
            Some(false.into()),
        ),
        output_schema: Some(update_output_schema()),
    })
}

pub(crate) fn create_team_history_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "event_id".to_string(),
            JsonSchema::string(Some(
                "Read the full chain of one event. Omit to list events you may read.".to_string(),
            )),
        ),
        (
            "limit".to_string(),
            JsonSchema::integer(Some(format!(
                "Maximum entries to return, capped at {MAX_HISTORY_LIMIT}."
            ))),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "team_history".to_string(),
        description:
            "Read team history you can no longer see in the active world index, including anything the projection reported as omitted. Scoped to what you are allowed to read and bounded in size."
                .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(properties, /*required*/ None, Some(false.into())),
        output_schema: Some(history_output_schema()),
    })
}

fn publish_output_schema() -> serde_json::Value {
    json!({
        "type": "object",
        "properties": {
            "event_id": { "type": "string" },
            "version_id": { "type": "string" },
            "revision": { "type": "integer" },
            "authored_on_stale_view": { "type": "boolean" },
            "deduplicated": { "type": "boolean" }
        },
        "required": ["event_id", "version_id", "revision", "authored_on_stale_view", "deduplicated"],
        "additionalProperties": false
    })
}

fn update_output_schema() -> serde_json::Value {
    json!({
        "type": "object",
        "properties": {
            "revision": { "type": "integer" },
            "updated": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "version_id": { "type": "string" },
                        "producer_state": { "type": "string" },
                        "root_state": { "type": "string" }
                    },
                    "required": ["version_id", "producer_state", "root_state"],
                    "additionalProperties": false
                }
            }
        },
        "required": ["revision", "updated"],
        "additionalProperties": false
    })
}

fn history_output_schema() -> serde_json::Value {
    json!({
        "type": "object",
        "properties": {
            "revision": { "type": "integer" },
            "total_events": { "type": "integer" },
            "omitted_events": { "type": "integer" },
            "events": { "type": "array", "items": { "type": "object" } }
        },
        "required": ["revision", "total_events", "omitted_events", "events"],
        "additionalProperties": false
    })
}
