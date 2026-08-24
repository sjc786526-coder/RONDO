//! Narrow, test-only adapters for the Plan 062 synchronous microbenchmarks.
//!
//! Keeping these concrete adapters under the existing test-support surface lets
//! the benchmark exercise the real private hot paths without turning them into
//! stable product APIs.

use codex_protocol::models::ResponseItem;
use codex_tools::ResponsesApiTool;
use codex_tools::ToolSpec;

use crate::context_manager::remove_orphan_outputs;
use crate::tools::registry::ToolRegistry;
use crate::tools::router::ToolRouter;
use crate::unified_exec::HeadTailBuffer;

/// Runs the production orphan-output normalization pass over owned input.
pub fn normalize_history(mut items: Vec<ResponseItem>) -> Vec<ResponseItem> {
    remove_orphan_outputs(&mut items);
    items
}

/// A prebuilt non-empty model-visible tool-spec workload.
pub struct ToolSpecsWorkload {
    router: ToolRouter,
}

impl ToolSpecsWorkload {
    pub fn new(spec_count: usize) -> Self {
        let specs = (0..spec_count)
            .map(|index| {
                ToolSpec::Function(ResponsesApiTool {
                    name: format!("plan062_tool_{index}"),
                    description: format!(
                        "Deterministic Plan 062 tool {index} with a non-empty model-visible schema"
                    ),
                    strict: true,
                    defer_loading: None,
                    parameters: codex_tools::JsonSchema::object(
                        std::collections::BTreeMap::from([
                            (
                                "path".to_string(),
                                codex_tools::JsonSchema::string(Some(
                                    "A deterministic benchmark path".to_string(),
                                )),
                            ),
                            (
                                "limit".to_string(),
                                codex_tools::JsonSchema::integer(Some(
                                    "A deterministic benchmark limit".to_string(),
                                )),
                            ),
                        ]),
                        Some(vec!["path".to_string(), "limit".to_string()]),
                        Some(false.into()),
                    ),
                    output_schema: None,
                })
            })
            .collect();
        Self {
            router: ToolRouter::from_parts(ToolRegistry::default(), specs),
        }
    }

    /// Repeats the production router-to-prompt ownership handoff.
    pub fn clone_repeated(&self, repeats: usize) -> usize {
        let mut visible_count = 0usize;
        for _ in 0..repeats {
            let specs = self.router.model_visible_specs();
            visible_count = visible_count.saturating_add(specs.len());
            std::hint::black_box(&specs);
        }
        visible_count
    }
}

/// A prefilled unified-exec retained-output workload.
pub struct UnifiedOutputWorkload {
    buffer: HeadTailBuffer,
}

impl UnifiedOutputWorkload {
    pub fn new(input_bytes: usize, max_bytes: usize) -> Self {
        let mut buffer = HeadTailBuffer::new(max_bytes);
        let chunk = vec![b'x'; input_bytes];
        buffer.push_chunk(chunk);
        Self { buffer }
    }

    /// Runs the same retained-byte snapshot path used by sandbox-denial checks.
    pub fn snapshot(&self) -> Vec<u8> {
        self.buffer.snapshot_retained_bytes()
    }
}
