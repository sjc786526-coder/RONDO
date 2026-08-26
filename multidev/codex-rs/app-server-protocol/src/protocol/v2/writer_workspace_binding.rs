use crate::JsonSchema;
use crate::TS;
use codex_protocol::protocol::WriterWorkspaceBindingAvailability as CoreAvailability;
use codex_protocol::protocol::WriterWorkspaceBindingSnapshot as CoreSnapshot;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;
use serde::Serialize;

/// Caller-prepared local linked worktree to bind as a writer's primary workspace.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct WriterWorkspaceBindingParams {
    pub worktree_root: AbsolutePathBuf,
    #[ts(optional = nullable)]
    pub environment_id: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(tag = "type", rename_all = "camelCase")]
#[ts(tag = "type", rename_all = "camelCase", export_to = "v2/")]
pub enum WriterWorkspaceBindingAvailability {
    Available,
    Unavailable { reason: String },
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct WriterWorkspaceBinding {
    #[ts(type = "number")]
    pub generation: u64,
    pub worktree_root: AbsolutePathBuf,
    pub git_dir: AbsolutePathBuf,
    pub common_dir: AbsolutePathBuf,
    pub repository_root: AbsolutePathBuf,
    pub environment_id: String,
    pub availability: WriterWorkspaceBindingAvailability,
}

impl From<CoreSnapshot> for WriterWorkspaceBinding {
    fn from(snapshot: CoreSnapshot) -> Self {
        let binding = snapshot.binding;
        Self {
            generation: binding.generation,
            worktree_root: binding.worktree_root,
            git_dir: binding.git_dir,
            common_dir: binding.common_dir,
            repository_root: binding.repository_root,
            environment_id: binding.environment_id,
            availability: match snapshot.availability {
                CoreAvailability::Available => WriterWorkspaceBindingAvailability::Available,
                CoreAvailability::Unavailable { reason } => {
                    WriterWorkspaceBindingAvailability::Unavailable { reason }
                }
            },
        }
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct WriterWorkspaceBindingReadParams {
    pub thread_id: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct WriterWorkspaceBindingReadResponse {
    pub binding: Option<WriterWorkspaceBinding>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct WriterWorkspaceBindingReplaceParams {
    pub thread_id: String,
    pub binding: WriterWorkspaceBindingParams,
    #[ts(optional = nullable)]
    #[ts(type = "number | null")]
    pub expected_generation: Option<u64>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct WriterWorkspaceBindingReplaceResponse {
    pub outcome: WriterWorkspaceBindingReplaceOutcome,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(tag = "type", rename_all = "camelCase")]
#[ts(tag = "type", rename_all = "camelCase", export_to = "v2/")]
pub enum WriterWorkspaceBindingReplaceOutcome {
    Applied {
        binding: WriterWorkspaceBinding,
    },
    Unknown {
        binding: WriterWorkspaceBinding,
        message: String,
    },
}
