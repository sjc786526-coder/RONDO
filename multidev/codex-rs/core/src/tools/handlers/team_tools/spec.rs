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
        (
            "before".to_string(),
            JsonSchema::integer(Some(
                "Pass the `next_before` from a previous result to read the page before it."
                    .to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "team_history".to_string(),
        description:
            "Read team history you can no longer see in the active world index, including anything the projection reported as omitted. Scoped to what you are allowed to read and bounded in size; page backwards with `before` to reach older entries."
                .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(properties, /*required*/ None, Some(false.into())),
        output_schema: Some(history_output_schema()),
    })
}

pub(crate) fn create_team_route_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "event_id".to_string(),
            JsonSchema::string(Some("The event to hand over.".to_string())),
        ),
        (
            "target".to_string(),
            JsonSchema::string(Some(
                "The agent to route it to, by the same reference you use for other agent tools."
                    .to_string(),
            )),
        ),
        (
            "intent".to_string(),
            JsonSchema::string_enum(
                vec![json!("assign"), json!("notify")],
                Some(
                    "`assign` when you want the target to work on this and asks it to start or continue; `notify` when you only want it to know. Do not use `assign` for something you are not asking for."
                        .to_string(),
                ),
            ),
        ),
        (
            "note".to_string(),
            JsonSchema::string(Some(
                "A short instruction for the target. Keep it to what you want done; the target reads the event itself."
                    .to_string(),
            )),
        ),
        (
            "based_on_revision".to_string(),
            JsonSchema::integer(Some(
                "The team revision shown in the active world index you acted on.".to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "team_route".to_string(),
        description:
            "Root only. Give one other agent access to one team event, and optionally assign it as work. Access is permanent once granted and lets the target read the whole chain and add its own versions, without copying the event anywhere. The target is told where to look, never the content."
                .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec![
                "event_id".to_string(),
                "target".to_string(),
                "intent".to_string(),
            ]),
            Some(false.into()),
        ),
        output_schema: Some(route_output_schema()),
    })
}

pub(crate) fn create_team_route_update_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "route_id".to_string(),
            JsonSchema::string(Some("The route to act on.".to_string())),
        ),
        (
            "action".to_string(),
            JsonSchema::string_enum(
                vec![json!("end"), json!("retry_notice")],
                Some(
                    "`end` finishes the assignment, which is the target's or the root's to do; `retry_notice` re-sends a notice that is reported as failed."
                        .to_string(),
                ),
            ),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "team_route_update".to_string(),
        description:
            "End a route assignment, or retry its notice after a failed delivery. Ending an assignment only retires that piece of work: what the target was given access to stays readable, and any other reason the event is still active is untouched."
                .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["route_id".to_string(), "action".to_string()]),
            Some(false.into()),
        ),
        output_schema: Some(route_update_output_schema()),
    })
}

pub(crate) fn create_team_evidence_tool() -> ToolSpec {
    let properties = BTreeMap::from([(
        "fact_id".to_string(),
        JsonSchema::string(Some(
            "An evidence reference from a team version you can read.".to_string(),
        )),
    )]);

    ToolSpec::Function(ResponsesApiTool {
        name: "team_evidence".to_string(),
        description:
            "Read the tool result a team version was published with. It returns what the harness recorded at that moment for that one observation, bounded in size — not the surrounding work, and not a claim that the result still holds. You can read your own evidence and anything a version of an event you can see explicitly referenced."
                .to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(vec!["fact_id".to_string()]),
            Some(false.into()),
        ),
        output_schema: Some(evidence_output_schema()),
    })
}

fn publish_output_schema() -> serde_json::Value {
    json!({
        "type": "object",
        "properties": {
            "event_id": { "type": "string" },
            "version_id": { "type": "string" },
            "revision": { "type": "integer" },
            "evidence_refs": { "type": "array", "items": { "type": "string" } },
            "authored_on_stale_view": { "type": "boolean" },
            "deduplicated": { "type": "boolean" }
        },
        "required": ["event_id", "version_id", "revision", "evidence_refs", "authored_on_stale_view", "deduplicated"],
        "additionalProperties": false
    })
}

fn evidence_output_schema() -> serde_json::Value {
    json!({
        "type": "object",
        "properties": {
            "fact_id": { "type": "string" },
            "producer": { "type": "string" },
            "tool": { "type": "string" },
            "category": { "type": "string" },
            "availability": { "type": "string" },
            "unavailable_reason": { "type": ["string", "null"] },
            "observation": { "type": ["string", "null"] },
            "truncated": { "type": "boolean" },
            "total_chars": { "type": ["integer", "null"] }
        },
        "required": ["fact_id", "producer", "tool", "category", "availability", "unavailable_reason", "observation", "truncated", "total_chars"],
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

fn route_output_schema() -> serde_json::Value {
    json!({
        "type": "object",
        "properties": {
            "route_id": { "type": "string" },
            "event_id": { "type": "string" },
            "target": { "type": "string" },
            "duty": { "type": "string" },
            "delivery": { "type": "string" },
            "delivery_error": { "type": ["string", "null"] },
            "revision": { "type": "integer" },
            "deduplicated": { "type": "boolean" }
        },
        "required": ["route_id", "event_id", "target", "duty", "delivery", "delivery_error", "revision", "deduplicated"],
        "additionalProperties": false
    })
}

fn route_update_output_schema() -> serde_json::Value {
    json!({
        "type": "object",
        "properties": {
            "route_id": { "type": "string" },
            "event_id": { "type": "string" },
            "duty": { "type": "string" },
            "delivery": { "type": "string" },
            "delivery_error": { "type": ["string", "null"] },
            "revision": { "type": "integer" }
        },
        "required": ["route_id", "event_id", "duty", "delivery", "delivery_error", "revision"],
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
            "next_before": { "type": ["integer", "null"] },
            "events": { "type": "array", "items": { "type": "object" } }
        },
        "required": ["revision", "total_events", "omitted_events", "next_before", "events"],
        "additionalProperties": false
    })
}
