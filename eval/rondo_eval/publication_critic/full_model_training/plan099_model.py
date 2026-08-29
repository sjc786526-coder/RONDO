"""One-forward five-head student and inference-ready artifact for Plan 099."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from ..successor_task import DIMENSION_CLASSES, HARD_DIMENSIONS
from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    sha256_file,
)
from .plan099_objective import FLAT_LOGIT_COUNT


MODEL_IDENTITY_SCHEMA = "rondo-publication-critic-plan099-model-identity-v1"
INFERENCE_MANIFEST_SCHEMA = (
    "rondo-publication-critic-plan099-inference-ready-manifest-v1"
)


def build_from_exact_classifier(
    classifier: Any,
    *,
    model_contract: Mapping[str, Any],
) -> Any:
    """Replace the exact scalar score with deterministic independent heads."""

    torch = _torch()
    base = model_contract["base"]
    if (
        classifier.__class__.__name__ != base["class"]
        or not hasattr(classifier, "model")
        or not hasattr(classifier, "score")
        or tuple(classifier.score.weight.shape) != (1, int(base["hidden_size"]))
        or classifier.score.bias is not None
    ):
        raise FullModelTrainingError("plan099_exact_classifier_invalid")
    scalar_weight = classifier.score.weight.detach().float().clone()
    student = _new_student(
        classifier.model,
        hidden_size=int(base["hidden_size"]),
        torch=torch,
    )
    with torch.no_grad():
        for dimension in HARD_DIMENSIONS:
            weight = student.five_heads[dimension].weight
            weight.zero_()
            weight[0].copy_(0.5 * scalar_weight[0])
            weight[1].copy_(-0.5 * scalar_weight[0])
    student.freeze_backbone()
    return student


def build_empty_student(backbone: Any, *, hidden_size: int) -> Any:
    student = _new_student(backbone, hidden_size=hidden_size, torch=_torch())
    student.freeze_backbone()
    return student


def head_parameter_names(student: Any) -> tuple[str, ...]:
    return tuple(
        name
        for name, parameter in student.named_parameters()
        if parameter.requires_grad
    )


def assert_frozen_scope(student: Any, recipe: Mapping[str, Any]) -> None:
    expected = tuple(recipe["scope"]["parameter_names"])
    actual = head_parameter_names(student)
    if actual != expected:
        raise FullModelTrainingError("plan099_trainable_scope_drifted")
    count = sum(
        int(parameter.numel())
        for _name, parameter in student.named_parameters()
        if parameter.requires_grad
    )
    if count != int(recipe["scope"]["trainable_parameter_elements"]):
        raise FullModelTrainingError("plan099_trainable_parameter_count_drifted")
    if student.backbone.training:
        raise FullModelTrainingError("plan099_backbone_not_eval")


def verify_initialization_parity(
    classifier: Any,
    student: Any,
    *,
    input_ids: Any,
    attention_mask: Any,
    atol: float = 5e-2,
) -> dict[str, Any]:
    """Prove exact head initialization, pooling, and score compatibility."""

    torch = _torch()
    classifier.eval()
    student.eval()
    with torch.no_grad():
        original_pooled = student.pooled_features(
            input_ids=input_ids, attention_mask=attention_mask
        )
        original = classifier.score(original_pooled).float().reshape(-1)
        flat = student.logits_from_features(original_pooled).float()
    maximum_error = 0.0
    scalar = classifier.score.weight.detach().float()[0]
    for dimension in HARD_DIMENSIONS:
        weight = student.five_heads[dimension].weight.detach().float()
        if not torch.equal(weight[0], 0.5 * scalar) or not torch.equal(
            weight[1], -0.5 * scalar
        ):
            raise FullModelTrainingError("plan099_initialization_weight_parity_failed")
        if weight.shape[0] == 3 and not torch.equal(
            weight[2], torch.zeros_like(weight[2])
        ):
            raise FullModelTrainingError("plan099_initialization_weight_parity_failed")
        head = student.head_logits(flat, dimension)
        margin = head[:, 0] - head[:, 1]
        maximum_error = max(
            maximum_error, float(torch.max(torch.abs(margin - original)).item())
        )
    if maximum_error > atol:
        raise FullModelTrainingError("plan099_initialization_parity_failed")
    return {
        "schema": "rondo-publication-critic-plan099-initialization-parity-v1",
        "rows": int(flat.shape[0]),
        "maximum_absolute_error": maximum_error,
        "atol": atol,
        "passed": True,
    }


def model_identity(
    *,
    freeze_sha256: str,
    source_commit: str,
    model_contract: Mapping[str, Any],
) -> dict[str, Any]:
    core = {
        "schema": MODEL_IDENTITY_SCHEMA,
        "freeze_sha256": freeze_sha256,
        "source_commit": source_commit,
        "base": json.loads(json.dumps(model_contract["base"])),
        "student": json.loads(json.dumps(model_contract["student"])),
        "input": json.loads(json.dumps(model_contract["input"])),
    }
    return {
        **core,
        "content_sha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest(),
    }


def save_inference_ready(
    student: Any,
    tokenizer: Any,
    destination: Path,
    *,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Write the complete backbone plus five heads; never an adapter-only handoff."""

    root = Path(destination)
    if root.is_symlink() or (
        root.exists() and (not root.is_dir() or any(root.iterdir()))
    ):
        raise FullModelTrainingError("plan099_inference_destination_exists")
    if not root.exists():
        root.mkdir(mode=0o700, parents=True)
    try:
        safetensors = _safetensors()
        state = {
            name: tensor.detach().contiguous().cpu()
            for name, tensor in student.state_dict().items()
        }
        safetensors.save_file(state, str(root / "model.safetensors"))
        config = dict(student.backbone.config.to_dict())
        config.update(
            {
                "architectures": ["RondoPublicationCriticFiveHeadModel"],
                "rondo_publication_critic": {
                    "schema": "rondo-publication-critic-plan099-five-head-config-v1",
                    "logical_head_order": list(HARD_DIMENSIONS),
                    "classes": {
                        key: list(DIMENSION_CLASSES[key]) for key in HARD_DIMENSIONS
                    },
                    "flat_logit_count": FLAT_LOGIT_COUNT,
                    "backbone_state_prefix": "backbone.",
                },
            }
        )
        (root / "config.json").write_bytes(pretty_json_bytes(config))
        (root / "rondo-plan099-model-identity.json").write_bytes(
            pretty_json_bytes(identity)
        )
        tokenizer.save_pretrained(root)
        return _write_inference_manifest(root)
    except BaseException:
        _remove_created_tree(root)
        raise


def load_inference_ready(root: Path) -> tuple[Any, Any, dict[str, Any]]:
    """Load only a verified complete Plan 099 handoff in a fresh process."""

    verified = verify_inference_ready(root)
    transformers = _transformers()
    torch = _torch()
    config = transformers.AutoConfig.from_pretrained(root, local_files_only=True)
    hidden_size = int(config.hidden_size)
    backbone = transformers.AutoModel.from_config(config, torch_dtype=torch.bfloat16)
    student = build_empty_student(backbone, hidden_size=hidden_size)
    state = _safetensors().load_file(str(Path(root) / "model.safetensors"))
    incompatible = student.load_state_dict(state, strict=True)
    if incompatible.missing_keys or incompatible.unexpected_keys:
        raise FullModelTrainingError("plan099_inference_state_invalid")
    tokenizer = transformers.AutoTokenizer.from_pretrained(root, local_files_only=True)
    identity = json.loads(
        (Path(root) / "rondo-plan099-model-identity.json").read_text(encoding="utf-8")
    )
    student.freeze_backbone()
    return student, tokenizer, {**verified, "identity": identity}


def verify_inference_ready(root: Path) -> dict[str, Any]:
    path = Path(root)
    manifest_path = path / "inference-manifest.json"
    if path.is_symlink() or not path.is_dir() or not manifest_path.is_file():
        raise FullModelTrainingError("plan099_inference_artifact_invalid")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, Mapping)
        or set(manifest) != {"schema", "files", "exact_tree_sha256"}
        or manifest.get("schema") != INFERENCE_MANIFEST_SCHEMA
        or not isinstance(manifest.get("files"), Mapping)
    ):
        raise FullModelTrainingError("plan099_inference_manifest_invalid")
    actual = set()
    for candidate in path.rglob("*"):
        info = os.lstat(candidate)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("plan099_inference_nonregular_entry")
        actual.add(candidate.relative_to(path).as_posix())
    expected = set(manifest["files"]) | {"inference-manifest.json"}
    if actual != expected:
        raise FullModelTrainingError("plan099_inference_tree_mismatch")
    for relative, metadata in manifest["files"].items():
        member = path / relative
        if (
            not isinstance(metadata, Mapping)
            or set(metadata) != {"bytes", "sha256"}
            or type(metadata["bytes"]) is not int
            or metadata["bytes"] != member.stat().st_size
            or metadata["sha256"] != sha256_file(member)
        ):
            raise FullModelTrainingError("plan099_inference_member_drifted", relative)
    tree_sha = hashlib.sha256(canonical_json_bytes(manifest["files"])).hexdigest()
    if tree_sha != manifest["exact_tree_sha256"]:
        raise FullModelTrainingError("plan099_inference_tree_identity_drifted")
    required = {
        "model.safetensors",
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "merges.txt",
        "vocab.json",
        "chat_template.jinja",
        "rondo-plan099-model-identity.json",
        "inference-manifest.json",
    }
    if not required <= actual:
        raise FullModelTrainingError("plan099_inference_required_member_missing")
    identity = json.loads(
        (path / "rondo-plan099-model-identity.json").read_text(encoding="utf-8")
    )
    if not isinstance(identity, Mapping) or set(identity) != {
        "schema",
        "freeze_sha256",
        "source_commit",
        "base",
        "student",
        "input",
        "content_sha256",
    }:
        raise FullModelTrainingError("plan099_model_identity_invalid")
    identity_core = {
        key: value for key, value in identity.items() if key != "content_sha256"
    }
    if (
        identity.get("schema") != MODEL_IDENTITY_SCHEMA
        or identity.get("content_sha256")
        != hashlib.sha256(canonical_json_bytes(identity_core)).hexdigest()
        or not _hex(identity.get("freeze_sha256"), 64)
        or not _hex(identity.get("source_commit"), 40)
        or identity.get("base", {}).get("repository")
        != "Skywork/Skywork-Reward-V2-Qwen3-1.7B"
        or identity.get("base", {}).get("revision")
        != "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc"
        or identity.get("base", {}).get("weight_sha256")
        != "117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9"
        or identity.get("student", {}).get("flat_logit_count") != 11
        or identity.get("student", {}).get("logical_head_count") != 5
    ):
        raise FullModelTrainingError("plan099_model_identity_invalid")
    config_value = json.loads((path / "config.json").read_text(encoding="utf-8"))
    custom = config_value.get("rondo_publication_critic", {})
    if (
        custom.get("schema") != "rondo-publication-critic-plan099-five-head-config-v1"
        or custom.get("logical_head_order") != list(HARD_DIMENSIONS)
        or custom.get("classes")
        != {key: list(DIMENSION_CLASSES[key]) for key in HARD_DIMENSIONS}
        or custom.get("flat_logit_count") != FLAT_LOGIT_COUNT
        or custom.get("backbone_state_prefix") != "backbone."
    ):
        raise FullModelTrainingError("plan099_inference_config_invalid")
    return {
        "schema": INFERENCE_MANIFEST_SCHEMA,
        "status": "verified",
        "file_count": len(actual),
        "total_bytes": sum((path / relative).stat().st_size for relative in actual),
        "exact_tree_sha256": tree_sha,
        "manifest_sha256": sha256_file(manifest_path),
    }


def _new_student(backbone: Any, *, hidden_size: int, torch: Any) -> Any:
    class RondoPublicationCriticFiveHeadModel(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.backbone = backbone
            self.five_heads = torch.nn.ModuleDict(
                {
                    dimension: torch.nn.Linear(
                        hidden_size,
                        len(DIMENSION_CLASSES[dimension]),
                        bias=False,
                        dtype=torch.float32,
                    )
                    for dimension in HARD_DIMENSIONS
                }
            )

        def freeze_backbone(self) -> None:
            for parameter in self.backbone.parameters():
                parameter.requires_grad_(False)
            self.backbone.eval()
            for head in self.five_heads.values():
                head.float()
                for parameter in head.parameters():
                    parameter.requires_grad_(True)

        def train(self, mode: bool = True) -> Any:
            super().train(mode)
            self.backbone.eval()
            return self

        def pooled_features(self, *, input_ids: Any, attention_mask: Any) -> Any:
            if (
                input_ids.ndim != 2
                or attention_mask.ndim != 2
                or tuple(input_ids.shape) != tuple(attention_mask.shape)
                or bool(((attention_mask != 0) & (attention_mask != 1)).any().item())
                or bool(
                    ((attention_mask[:, 1:] - attention_mask[:, :-1]) > 0).any().item()
                )
            ):
                raise FullModelTrainingError("plan099_right_padding_required")
            pad_token_id = getattr(self.backbone.config, "pad_token_id", None)
            if pad_token_id is None or bool(
                (input_ids[attention_mask == 0] != int(pad_token_id)).any().item()
            ):
                raise FullModelTrainingError("plan099_masked_token_invalid")
            outputs = self.backbone(
                input_ids=input_ids,
                attention_mask=attention_mask,
                use_cache=False,
                return_dict=True,
            )
            hidden = outputs.last_hidden_state
            positions = attention_mask.to(dtype=torch.long).sum(dim=1) - 1
            if bool((positions < 0).any().item()):
                raise FullModelTrainingError("plan099_empty_model_input")
            batch = torch.arange(hidden.shape[0], device=hidden.device)
            return hidden[batch, positions]

        def logits_from_features(self, features: Any) -> Any:
            values = features.float()
            return torch.cat(
                [self.five_heads[dimension](values) for dimension in HARD_DIMENSIONS],
                dim=-1,
            )

        def forward(self, *, input_ids: Any, attention_mask: Any) -> Any:
            return self.logits_from_features(
                self.pooled_features(input_ids=input_ids, attention_mask=attention_mask)
            )

        @staticmethod
        def head_logits(flat_logits: Any, dimension: str) -> Any:
            if dimension not in HARD_DIMENSIONS:
                raise FullModelTrainingError("plan099_head_invalid")
            start = sum(
                len(DIMENSION_CLASSES[item])
                for item in HARD_DIMENSIONS[: HARD_DIMENSIONS.index(dimension)]
            )
            return flat_logits[:, start : start + len(DIMENSION_CLASSES[dimension])]

    return RondoPublicationCriticFiveHeadModel()


def _write_inference_manifest(root: Path) -> dict[str, Any]:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file():
            raise FullModelTrainingError("plan099_inference_nonregular_entry")
        relative = path.relative_to(root).as_posix()
        if relative == "inference-manifest.json":
            raise FullModelTrainingError("plan099_inference_manifest_conflict")
        files[relative] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    manifest = {
        "schema": INFERENCE_MANIFEST_SCHEMA,
        "files": files,
        "exact_tree_sha256": hashlib.sha256(canonical_json_bytes(files)).hexdigest(),
    }
    (root / "inference-manifest.json").write_bytes(pretty_json_bytes(manifest))
    return verify_inference_ready(root)


def _remove_created_tree(root: Path) -> None:
    if not root.exists() or root.is_symlink():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir() and not path.is_symlink():
            path.rmdir()
        else:
            path.unlink()
    root.rmdir()


def _torch() -> Any:
    try:
        import torch
    except ImportError as exc:
        raise FullModelTrainingError("plan099_torch_dependency_missing") from exc
    return torch


def _safetensors() -> Any:
    try:
        from safetensors import torch as safetensors_torch
    except ImportError as exc:
        raise FullModelTrainingError("plan099_safetensors_dependency_missing") from exc
    return safetensors_torch


def _transformers() -> Any:
    try:
        import transformers
    except ImportError as exc:
        raise FullModelTrainingError("plan099_transformers_dependency_missing") from exc
    return transformers


def _hex(value: Any, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "assert_frozen_scope",
    "build_empty_student",
    "build_from_exact_classifier",
    "head_parameter_names",
    "load_inference_ready",
    "model_identity",
    "save_inference_ready",
    "verify_inference_ready",
    "verify_initialization_parity",
]
