use super::is_artifact_object_id;

#[test]
fn artifact_object_id_accepts_legacy_and_bounded_runtime_ids() {
    for value in [
        "base",
        "c1",
        "c2",
        "c3",
        "qualified-plan097",
        "Skywork.Reward_V2-1.7B",
    ] {
        assert!(is_artifact_object_id(value), "rejected {value:?}");
    }
    assert!(is_artifact_object_id(&"a".repeat(128)));
}

#[test]
fn artifact_object_id_rejects_unsafe_or_unbounded_values() {
    for value in [
        "",
        "-leading",
        "_leading",
        ".leading",
        "contains/slash",
        "contains space",
        "non-ascii-é",
    ] {
        assert!(!is_artifact_object_id(value), "accepted {value:?}");
    }
    assert!(!is_artifact_object_id(&"a".repeat(129)));
}
