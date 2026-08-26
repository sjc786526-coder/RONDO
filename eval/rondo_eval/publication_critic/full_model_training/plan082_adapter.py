"""Concrete Torch adapter for Plan 082 continuous direct-parameter training."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
import copy
import gc
import importlib
import json
import math
import os
from pathlib import Path
import random
from typing import Any

from ..tokenization import ExactTokenizer
from .contract import (
    MODEL_REPOSITORY,
    MODEL_REVISION,
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    sha256_bytes,
    sha256_file,
    write_exclusive,
)
from .data import PortableTrainingDataset, tokenize_dataset
from .objective import binary_loss, extract_raw_scalar, pair_loss
from .plan066_data import ValidationDataset, tokenize_validation
from .plan081_contract import TrainableScope
from .plan081_observation import (
    training_identity_sha256,
    validation_identity_sha256,
)
from .plan082_bundle import MODEL_LOCK_SHA256


RECIPE_SCHEMA = "rondo-publication-critic-plan082-training-recipe-v1"
SNAPSHOT_SCHEMA = "rondo-publication-critic-plan082-snapshot-receipt-v1"
RUNTIME_KIND = "torch_real_direct_original_parameters"
MODEL_LOCK_RELATIVE = (
    "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json"
)
ALLOWED_GPUS = frozenset({"NVIDIA A40", "NVIDIA L40S"})
COMPONENT_WEIGHTS = {
    "binary": 1.0 / 3.0,
    "boundary": 1.0 / 3.0,
    "within_pass": 1.0 / 3.0,
}


def validate_recipe(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "seed",
        "optimizer",
        "scheduler",
        "binary_micro_batch_size",
        "pair_micro_batch_size",
        "gradient_clip_norm",
        "activation_checkpointing",
        "attention_backend",
        "macro_update",
        "objective",
    }:
        raise FullModelTrainingError("plan082_recipe_fields_invalid")
    optimizer = value.get("optimizer")
    scheduler = value.get("scheduler")
    objective = value.get("objective")
    if (
        value.get("schema") != RECIPE_SCHEMA
        or not _positive_int(value.get("seed"))
        or not isinstance(optimizer, Mapping)
        or set(optimizer)
        != {
            "name",
            "learning_rate",
            "betas",
            "epsilon",
            "weight_decay",
            "fused",
        }
        or optimizer.get("name") != "torch.optim.AdamW"
        or not _positive_finite(optimizer.get("learning_rate"))
        or not _betas(optimizer.get("betas"))
        or not _positive_finite(optimizer.get("epsilon"))
        or not _nonnegative_finite(optimizer.get("weight_decay"))
        or type(optimizer.get("fused")) is not bool
        or scheduler != {"name": "constant"}
        or not _positive_int(value.get("binary_micro_batch_size"))
        or not _positive_int(value.get("pair_micro_batch_size"))
        or not _nonnegative_finite(value.get("gradient_clip_norm"))
        or type(value.get("activation_checkpointing")) is not bool
        or value.get("attention_backend") != "sdpa"
        or value.get("macro_update") != "one_full_v8_train_cohort"
        or objective
        != {
            "scalar": "logits[:,0]",
            "direction": "preferred_minus_dispreferred",
            "binary_loss": "softplus(-signed_target*logits[:,0])",
            "pair_loss": "softplus(dispreferred-preferred)",
            "pair_margin": 0.0,
            "pair_temperature": 1.0,
            "component_weights": COMPONENT_WEIGHTS,
        }
    ):
        raise FullModelTrainingError("plan082_recipe_invalid")
    return json.loads(json.dumps(value))


def verify_snapshot(snapshot_root: Path, model_lock_path: Path) -> dict[str, Any]:
    root = Path(snapshot_root)
    if root.is_symlink() or not root.is_dir():
        raise FullModelTrainingError("plan082_snapshot_root_unsafe")
    lock_path = Path(model_lock_path)
    if sha256_file(lock_path) != MODEL_LOCK_SHA256:
        raise FullModelTrainingError("plan082_model_lock_identity_mismatch")
    lock = read_json(lock_path)
    if (
        not isinstance(lock, Mapping)
        or lock.get("schema") != "rondo-publication-critic-skywork-assets-v1"
        or lock.get("model")
        != {
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "public": True,
            "gated": False,
            "pipeline_tag": "text-classification",
        }
        or lock.get("weights")
        != {
            "filename": "model.safetensors",
            "bytes": 3_441_189_792,
            "parameter_count": 1_720_577_024,
            "storage_dtype": "BF16",
        }
        or not isinstance(lock.get("files"), Mapping)
    ):
        raise FullModelTrainingError("plan082_model_lock_invalid")
    expected = set(lock["files"])
    actual: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".cache":
            if path.is_symlink():
                raise FullModelTrainingError("plan082_snapshot_entry_unsafe")
            continue
        if path.is_dir() and not path.is_symlink():
            continue
        if not path.is_file() or path.is_symlink():
            raise FullModelTrainingError("plan082_snapshot_entry_unsafe")
        actual.add(relative.as_posix())
    if actual != expected:
        raise FullModelTrainingError("plan082_snapshot_file_set_mismatch")
    files: dict[str, dict[str, Any]] = {}
    for relative, expected_sha256 in sorted(lock["files"].items()):
        path = root.joinpath(*Path(relative).parts)
        observed = sha256_file(path, maximum_bytes=4 * 1024 * 1024 * 1024)
        if observed != expected_sha256:
            raise FullModelTrainingError("plan082_snapshot_file_identity_mismatch")
        files[relative] = {"bytes": path.stat().st_size, "sha256": observed}
    return {
        "schema": SNAPSHOT_SCHEMA,
        "repository": MODEL_REPOSITORY,
        "revision": MODEL_REVISION,
        "model_lock_sha256": MODEL_LOCK_SHA256,
        "parameter_count": 1_720_577_024,
        "storage_dtype": "BF16",
        "files": files,
        "snapshot_content_sha256": sha256_bytes(canonical_json_bytes(files)),
    }


class TorchContinuousTrainingAdapter:
    """Real Torch implementation of the Plan 081-neutral adapter seam.

    ``from_snapshot`` is the production constructor.  ``from_components`` is
    intentionally explicit so focused tests can exercise the same adapter
    without installing or loading the 1.7B model.
    """

    def __init__(
        self,
        *,
        torch_module: Any,
        transformers_module: Any,
        model: Any,
        tokenizer: Any,
        device: Any,
        recipe: Mapping[str, Any],
        snapshot_root: Path,
        snapshot_receipt: Mapping[str, Any],
        runtime_facts: Mapping[str, Any],
    ) -> None:
        self.torch = torch_module
        self.transformers = transformers_module
        self.model = model
        self.tokenizer = tokenizer
        self.exact_tokenizer = ExactTokenizer(tokenizer)
        self.device = device
        self.recipe = validate_recipe(recipe)
        self.snapshot_root = Path(snapshot_root)
        self.snapshot_receipt = json.loads(json.dumps(snapshot_receipt))
        self.runtime_facts = json.loads(json.dumps(runtime_facts))
        self.optimizer: Any | None = None
        self.scheduler: Any | None = None
        self.scope: TrainableScope | None = None
        self.data_cursor: dict[str, Any] = {"macro_update": 0}
        self.global_step = 0
        self._training_cache: dict[str, Any] = {}
        self._validation_cache: dict[str, Any] = {}
        self._checkpoint_model_root: Path | None = None
        self._factory: Any | None = None
        self._disposed = False
        self.last_update_metrics: dict[str, Any] | None = None

    @classmethod
    def from_snapshot(
        cls,
        *,
        snapshot_root: Path,
        model_lock_path: Path,
        recipe: Mapping[str, Any],
    ) -> "TorchContinuousTrainingAdapter":
        recipe_value = validate_recipe(recipe)
        receipt = verify_snapshot(snapshot_root, model_lock_path)
        try:
            torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
        except ImportError as exc:
            raise FullModelTrainingError("plan082_training_dependency_missing") from exc
        if not torch.cuda.is_available() or int(torch.cuda.device_count()) != 1:
            raise FullModelTrainingError("plan082_single_cuda_gpu_required")
        gpu_name = str(torch.cuda.get_device_name(0))
        if gpu_name not in ALLOWED_GPUS:
            raise FullModelTrainingError("plan082_gpu_not_allowed")
        device = torch.device("cuda:0")
        seed = int(recipe_value["seed"])
        random.seed(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        try:
            numpy = importlib.import_module("numpy")
        except ImportError:
            pass
        else:
            numpy.random.seed(seed % (2**32))
        try:
            tokenizer = transformers.AutoTokenizer.from_pretrained(
                snapshot_root,
                local_files_only=True,
                trust_remote_code=False,
                use_fast=True,
            )
            model = transformers.AutoModelForSequenceClassification.from_pretrained(
                snapshot_root,
                local_files_only=True,
                trust_remote_code=False,
                torch_dtype=torch.bfloat16,
                attn_implementation="sdpa",
            )
        except Exception as exc:
            raise FullModelTrainingError("plan082_exact_model_load_failed") from exc
        model.to(device)
        model.config.use_cache = False
        if recipe_value["activation_checkpointing"]:
            model.gradient_checkpointing_enable()
            enable_input_grads = getattr(model, "enable_input_require_grads", None)
            if not callable(enable_input_grads):
                raise FullModelTrainingError("plan082_input_gradient_hook_unavailable")
            enable_input_grads()
        model.train()
        adapter = cls(
            torch_module=torch,
            transformers_module=transformers,
            model=model,
            tokenizer=tokenizer,
            device=device,
            recipe=recipe_value,
            snapshot_root=snapshot_root,
            snapshot_receipt=receipt,
            runtime_facts={
                "runtime_kind": RUNTIME_KIND,
                "gpu_name": gpu_name,
                "gpu_count": 1,
                "cuda_version": str(getattr(torch.version, "cuda", "")),
                "torch_version": str(getattr(torch, "__version__", "")),
                "transformers_version": str(getattr(transformers, "__version__", "")),
                "model_repository": MODEL_REPOSITORY,
                "model_revision": MODEL_REVISION,
                "peft": False,
                "quantized_training": False,
            },
        )
        adapter._factory = lambda: cls.from_snapshot(
            snapshot_root=snapshot_root,
            model_lock_path=model_lock_path,
            recipe=recipe_value,
        )
        adapter.assert_fresh_exact_base(MODEL_REPOSITORY, MODEL_REVISION)
        return adapter

    @classmethod
    def from_components(
        cls,
        *,
        torch_module: Any,
        transformers_module: Any,
        model: Any,
        tokenizer: Any,
        device: Any,
        recipe: Mapping[str, Any],
        snapshot_root: Path,
        snapshot_receipt: Mapping[str, Any],
        runtime_facts: Mapping[str, Any],
        recovery_factory: Any | None = None,
    ) -> "TorchContinuousTrainingAdapter":
        adapter = cls(
            torch_module=torch_module,
            transformers_module=transformers_module,
            model=model,
            tokenizer=tokenizer,
            device=device,
            recipe=recipe,
            snapshot_root=snapshot_root,
            snapshot_receipt=snapshot_receipt,
            runtime_facts=runtime_facts,
        )
        adapter._factory = recovery_factory
        return adapter

    def plan082_runtime_identity(self) -> dict[str, Any]:
        inventory = self.parameter_inventory()
        return {
            **json.loads(json.dumps(self.runtime_facts)),
            "snapshot_content_sha256": self.snapshot_receipt.get(
                "snapshot_content_sha256"
            ),
            "recipe_sha256": sha256_bytes(canonical_json_bytes(self.recipe)),
            "parameter_inventory_sha256": inventory["inventory_sha256"],
            "parameter_tensors": inventory["parameter_tensors"],
            "parameter_elements": inventory["parameter_elements"],
        }

    def parameter_inventory(self) -> dict[str, Any]:
        rows = []
        elements = 0
        for name, parameter in self.model.named_parameters():
            count = int(parameter.numel())
            elements += count
            rows.append(
                {
                    "name": name,
                    "elements": count,
                    "dtype": str(parameter.dtype),
                    "requires_grad": bool(parameter.requires_grad),
                }
            )
        if not rows:
            raise FullModelTrainingError("plan082_parameter_inventory_empty")
        identity_rows = [
            {key: value for key, value in row.items() if key != "requires_grad"}
            for row in rows
        ]
        return {
            "parameter_tensors": len(rows),
            "parameter_elements": elements,
            "trainable_parameter_tensors": sum(row["requires_grad"] for row in rows),
            "trainable_parameter_elements": sum(
                row["elements"] for row in rows if row["requires_grad"]
            ),
            "parameters": rows,
            "inventory_sha256": sha256_bytes(canonical_json_bytes(identity_rows)),
        }

    def assert_fresh_exact_base(self, repository: str, revision: str) -> None:
        if (
            self._disposed
            or repository != MODEL_REPOSITORY
            or revision != MODEL_REVISION
            or self.global_step != 0
            or self.optimizer is not None
            or self.scheduler is not None
            or self.data_cursor != {"macro_update": 0}
            or self._checkpoint_model_root is not None
        ):
            raise FullModelTrainingError("plan082_adapter_not_fresh_exact_base")

    def configure_trainable_scope(self, scope: TrainableScope) -> None:
        if not isinstance(scope, TrainableScope):
            raise FullModelTrainingError("plan082_trainable_scope_invalid")
        named = dict(self.model.named_parameters())
        selected = set(scope.parameter_names)
        if not selected <= set(named):
            raise FullModelTrainingError("plan082_trainable_scope_unknown_parameter")
        elements = sum(int(named[name].numel()) for name in selected)
        if elements != scope.trainable_parameter_elements:
            raise FullModelTrainingError("plan082_trainable_scope_elements_mismatch")
        previous = set(self.scope.parameter_names) if self.scope is not None else set()
        if previous and not previous <= selected:
            raise FullModelTrainingError("plan082_trainable_scope_shrank")
        if self.scope is not None and scope.parameter_names[
            : len(self.scope.parameter_names)
        ] != (self.scope.parameter_names):
            raise FullModelTrainingError("plan082_trainable_scope_order_drifted")
        for name, parameter in named.items():
            parameter.requires_grad_(name in selected)
        new_parameters = [
            named[name] for name in scope.parameter_names if name not in previous
        ]
        if self.optimizer is None:
            self.optimizer = self._new_optimizer(new_parameters)
            self.scheduler = self.torch.optim.lr_scheduler.LambdaLR(
                self.optimizer, lambda _step: 1.0
            )
        elif new_parameters:
            if len(self.optimizer.param_groups) != 1:
                raise FullModelTrainingError("plan082_optimizer_group_layout_invalid")
            self.optimizer.param_groups[0]["params"].extend(new_parameters)
        self.scope = TrainableScope.from_value(scope.as_dict())

    def assert_trainable_scope(self, scope: TrainableScope) -> None:
        named = dict(self.model.named_parameters())
        actual = tuple(
            name for name, parameter in named.items() if parameter.requires_grad
        )
        optimizer_parameters = (
            []
            if self.optimizer is None
            else [
                parameter
                for group in self.optimizer.param_groups
                for parameter in group["params"]
            ]
        )
        expected_parameters = [named[name] for name in scope.parameter_names]
        if (
            self.scope != scope
            or set(actual) != set(scope.parameter_names)
            or {id(parameter) for parameter in optimizer_parameters}
            != {id(parameter) for parameter in expected_parameters}
            or len(optimizer_parameters) != len(expected_parameters)
        ):
            raise FullModelTrainingError("plan082_trainable_scope_runtime_mismatch")

    def apply_update(
        self,
        step: int,
        scope: TrainableScope,
        training_dataset: PortableTrainingDataset,
    ) -> dict[str, Any]:
        self.assert_trainable_scope(scope)
        if (
            self.optimizer is None
            or self.scheduler is None
            or step != self.global_step + 1
        ):
            raise FullModelTrainingError("plan082_update_state_invalid")
        identity = training_identity_sha256(training_dataset)
        tokenized = self._training_cache.get(identity)
        if tokenized is None:
            tokenized = tokenize_dataset(training_dataset, self.exact_tokenizer)
            self._training_cache = {identity: tokenized}
        self.model.train()
        self.optimizer.zero_grad(set_to_none=True)
        component_sums = {name: 0.0 for name in COMPONENT_WEIGHTS}
        component_counts = {name: 0 for name in COMPONENT_WEIGHTS}

        candidate_ids = tuple(sorted(training_dataset.supervision))
        binary_batch = int(self.recipe["binary_micro_batch_size"])
        for start in range(0, len(candidate_ids), binary_batch):
            batch_ids = candidate_ids[start : start + binary_batch]
            scalars = self._forward(tokenized, batch_ids)
            loss = binary_loss(
                scalars.float(),
                [training_dataset.label(candidate_id) for candidate_id in batch_ids],
            )
            self._require_finite_loss(loss)
            (
                loss
                * COMPONENT_WEIGHTS["binary"]
                * (len(batch_ids) / len(candidate_ids))
            ).backward()
            component_sums["binary"] += float(loss.detach().item()) * len(batch_ids)
            component_counts["binary"] += len(batch_ids)

        pairs_by_kind: dict[str, list[Mapping[str, Any]]] = {
            "boundary": [],
            "within_pass": [],
        }
        for pair in training_dataset.pairs.values():
            pairs_by_kind[str(pair["kind"])].append(pair)
        pair_batch_size = int(self.recipe["pair_micro_batch_size"])
        for kind, pairs in pairs_by_kind.items():
            if not pairs:
                raise FullModelTrainingError("plan082_training_component_missing")
            for start in range(0, len(pairs), pair_batch_size):
                batch_pairs = pairs[start : start + pair_batch_size]
                flat_ids = tuple(
                    candidate_id
                    for pair in batch_pairs
                    for candidate_id in (
                        str(pair["preferred_candidate_id"]),
                        str(pair["dispreferred_candidate_id"]),
                    )
                )
                scalars = self._forward(tokenized, flat_ids).float()
                loss = pair_loss(
                    scalars[0::2],
                    scalars[1::2],
                    margin=0.0,
                    temperature=1.0,
                )
                self._require_finite_loss(loss)
                (
                    loss * COMPONENT_WEIGHTS[kind] * (len(batch_pairs) / len(pairs))
                ).backward()
                component_sums[kind] += float(loss.detach().item()) * len(batch_pairs)
                component_counts[kind] += len(batch_pairs)

        trainable = [
            parameter
            for parameter in self.model.parameters()
            if parameter.requires_grad
        ]
        clip = float(self.recipe["gradient_clip_norm"])
        norm = self.torch.nn.utils.clip_grad_norm_(
            trainable,
            clip if clip > 0 else float("inf"),
            error_if_nonfinite=True,
        )
        norm_value = float(norm.item() if hasattr(norm, "item") else norm)
        if not math.isfinite(norm_value) or norm_value <= 0:
            raise FullModelTrainingError("plan082_gradient_invalid")
        self.optimizer.step()
        self.scheduler.step()
        self.optimizer.zero_grad(set_to_none=True)
        self.global_step = step
        self.data_cursor = {
            "macro_update": step,
            "training_identity_sha256": identity,
            "candidate_count": len(candidate_ids),
            "pair_count": len(training_dataset.pairs),
        }
        self.last_update_metrics = {
            "component_mean_loss": {
                kind: component_sums[kind] / component_counts[kind]
                for kind in component_sums
            },
            "gradient_preclip_norm": norm_value,
            "optimizer": "torch.optim.AdamW",
            "macro_update": "one_full_v8_train_cohort",
        }
        return {
            "global_step": step,
            "training_split": "train",
            "validation_candidates_consumed": 0,
            "unseen_candidates_consumed": 0,
            "training_identity_sha256": identity,
            "training_candidate_count": len(training_dataset.supervision),
            "training_pair_count": len(training_dataset.pairs),
            "scope": scope.as_dict(),
            "data_cursor": copy.deepcopy(self.data_cursor),
        }

    def evaluate_validation(self, dataset: ValidationDataset) -> dict[str, Any]:
        if self.optimizer is None or self.scheduler is None:
            raise FullModelTrainingError("plan082_validation_before_scope")
        identity = validation_identity_sha256(dataset)
        tokenized = self._validation_cache.get(identity)
        if tokenized is None:
            tokenized = tokenize_validation(dataset, self.exact_tokenizer)
            self._validation_cache = {identity: tokenized}
        before = self._training_state_guard()
        self._require_no_gradients()
        training = bool(self.model.training)
        scores: dict[str, float] = {}
        self.model.eval()
        try:
            with self.torch.inference_mode():
                for candidate_id in sorted(dataset.supervision):
                    scalar = self._forward(tokenized, (candidate_id,))
                    score = float(scalar[0].float().item())
                    if not math.isfinite(score):
                        raise FullModelTrainingError("plan082_validation_nonfinite")
                    scores[candidate_id] = score
        finally:
            if training:
                self.model.train()
        self._require_no_gradients()
        after = self._training_state_guard()
        if before != after:
            raise FullModelTrainingError("plan082_validation_mutated_training_state")
        return {
            "raw_logits": scores,
            "gradient_access": False,
            "training_state_unchanged": True,
            "validation_identity_sha256": identity,
        }

    def training_state_codec_id(self) -> str:
        return "plan082-torch-state-v1"

    def capture_training_state(self) -> dict[str, Any]:
        if self.optimizer is None or self.scheduler is None:
            raise FullModelTrainingError("plan082_training_state_unavailable")
        return {
            "optimizer": self.optimizer.state_dict(),
            "scheduler": self.scheduler.state_dict(),
            "rng": self._capture_rng(),
            "data": copy.deepcopy(self.data_cursor),
        }

    def write_training_state(self, path: Path, value: Mapping[str, Any]) -> None:
        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise FullModelTrainingError("plan082_training_state_exists")
        try:
            self.torch.save(dict(value), destination)
            os.chmod(destination, 0o600)
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise FullModelTrainingError("plan082_training_state_write_failed") from exc

    def read_training_state(self, path: Path) -> Mapping[str, Any]:
        try:
            value = self.torch.load(
                Path(path), map_location=self.device, weights_only=False
            )
        except Exception as exc:
            raise FullModelTrainingError("plan082_training_state_read_failed") from exc
        if not isinstance(value, Mapping):
            raise FullModelTrainingError("plan082_training_state_invalid")
        return value

    def training_states_equal(self, left: Any, right: Any) -> bool:
        return self._values_equal(left, right)

    def restore_training_state(self, value: Mapping[str, Any]) -> None:
        if self.optimizer is None or self.scheduler is None:
            raise FullModelTrainingError("plan082_restore_before_scope")
        try:
            self.optimizer.load_state_dict(value["optimizer"])
            self.scheduler.load_state_dict(value["scheduler"])
            self._restore_rng(value["rng"])
            self.data_cursor = copy.deepcopy(dict(value["data"]))
            self.global_step = int(self.data_cursor["macro_update"])
        except Exception as exc:
            raise FullModelTrainingError(
                "plan082_training_state_restore_failed"
            ) from exc

    def assert_data_cursor(self, value: Mapping[str, Any]) -> None:
        if self.data_cursor != value:
            raise FullModelTrainingError("plan082_data_cursor_restore_mismatch")

    def save_model(self, destination: Path) -> None:
        target = _existing_empty_payload(destination)
        self.model.save_pretrained(
            target,
            safe_serialization=True,
            max_shard_size="5GB",
        )
        self.tokenizer.save_pretrained(target)

    def save_evaluation_snapshot(self, destination: Path) -> None:
        target = _existing_empty_payload(destination)
        value = {
            "schema": "rondo-publication-critic-plan082-evaluation-snapshot-ref-v1",
            "global_step": self.global_step,
            "scope": self.scope.as_dict() if self.scope is not None else None,
            "runtime_identity": self.plan082_runtime_identity(),
            "weight_payload": "retained_by_corresponding_full_checkpoint",
        }
        write_exclusive(target / "snapshot-reference.json", pretty_json_bytes(value))

    def load_model(self, model_root: Path) -> None:
        try:
            model = (
                self.transformers.AutoModelForSequenceClassification.from_pretrained(
                    model_root,
                    local_files_only=True,
                    trust_remote_code=False,
                    torch_dtype=self.torch.bfloat16,
                    attn_implementation="sdpa",
                )
            )
            tokenizer = self.transformers.AutoTokenizer.from_pretrained(
                model_root,
                local_files_only=True,
                trust_remote_code=False,
                use_fast=True,
            )
        except Exception as exc:
            raise FullModelTrainingError(
                "plan082_checkpoint_model_load_failed"
            ) from exc
        model.to(self.device)
        model.config.use_cache = False
        if self.recipe["activation_checkpointing"]:
            model.gradient_checkpointing_enable()
            enable_input_grads = getattr(model, "enable_input_require_grads", None)
            if not callable(enable_input_grads):
                raise FullModelTrainingError("plan082_input_gradient_hook_unavailable")
            enable_input_grads()
        model.train()
        self.model = model
        self.tokenizer = tokenizer
        self.exact_tokenizer = ExactTokenizer(tokenizer)
        self.optimizer = None
        self.scheduler = None
        self.scope = None
        self._checkpoint_model_root = Path(model_root).resolve()
        self._training_cache.clear()
        self._validation_cache.clear()

    def assert_checkpoint_model_loaded(self, model_root: Path) -> None:
        if self._checkpoint_model_root != Path(model_root).resolve():
            raise FullModelTrainingError("plan082_checkpoint_model_not_loaded")

    @contextmanager
    def checkpoint_recovery_probe(self):
        if not callable(self._factory):
            raise FullModelTrainingError("plan082_checkpoint_probe_factory_missing")
        self._dispose_runtime()
        probe = self._factory()
        try:
            yield probe
        except BaseException:
            probe._dispose_runtime()
            raise
        else:
            self._adopt_runtime(probe)

    def close(self) -> None:
        if not self._disposed:
            self._dispose_runtime()

    def _new_optimizer(self, parameters: Sequence[Any]) -> Any:
        if not parameters:
            raise FullModelTrainingError("plan082_optimizer_parameters_empty")
        config = self.recipe["optimizer"]
        try:
            return self.torch.optim.AdamW(
                list(parameters),
                lr=float(config["learning_rate"]),
                betas=tuple(float(item) for item in config["betas"]),
                eps=float(config["epsilon"]),
                weight_decay=float(config["weight_decay"]),
                fused=bool(config["fused"]),
            )
        except Exception as exc:
            raise FullModelTrainingError("plan082_optimizer_create_failed") from exc

    def _forward(
        self, tokenized: Mapping[str, Any], candidate_ids: Sequence[str]
    ) -> Any:
        if self.tokenizer.padding_side != "right":
            raise FullModelTrainingError("plan082_padding_side_drifted")
        batch = self.tokenizer.pad(
            {
                "input_ids": [
                    list(tokenized[candidate_id].input_ids)
                    for candidate_id in candidate_ids
                ]
            },
            padding=True,
            return_attention_mask=True,
            return_tensors="pt",
        )
        batch = {name: tensor.to(self.device) for name, tensor in batch.items()}
        output = self.model(**batch)
        return extract_raw_scalar(output.logits)

    def _require_finite_loss(self, loss: Any) -> None:
        try:
            finite = bool(self.torch.isfinite(loss).all().item())
        except Exception as exc:
            raise FullModelTrainingError("plan082_loss_invalid") from exc
        if not finite:
            raise FullModelTrainingError("plan082_loss_nonfinite")

    def _require_no_gradients(self) -> None:
        if any(parameter.grad is not None for parameter in self.model.parameters()):
            raise FullModelTrainingError("plan082_validation_gradient_present")

    def _training_state_guard(self) -> dict[str, Any]:
        if self.optimizer is None or self.scheduler is None:
            raise FullModelTrainingError("plan082_training_state_unavailable")
        versions = []
        for parameter, state in self.optimizer.state.items():
            row = {"parameter": id(parameter), "values": []}
            for key, value in sorted(state.items(), key=lambda item: str(item[0])):
                row["values"].append(
                    (
                        str(key),
                        id(value),
                        getattr(value, "_version", None),
                        str(getattr(value, "dtype", type(value).__name__)),
                        tuple(getattr(value, "shape", ())),
                    )
                )
            versions.append(row)
        return {
            "optimizer_versions": versions,
            "scheduler": repr(self.scheduler.state_dict()),
            "data_cursor": copy.deepcopy(self.data_cursor),
            "global_step": self.global_step,
            "model_training": bool(self.model.training),
        }

    def _capture_rng(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "python": random.getstate(),
            "torch_cpu": self.torch.get_rng_state(),
            "torch_cuda": self.torch.cuda.get_rng_state_all(),
        }
        try:
            numpy = importlib.import_module("numpy")
        except ImportError:
            value["numpy"] = None
        else:
            value["numpy"] = numpy.random.get_state()
        return value

    def _restore_rng(self, value: Mapping[str, Any]) -> None:
        random.setstate(value["python"])
        self.torch.set_rng_state(value["torch_cpu"])
        self.torch.cuda.set_rng_state_all(value["torch_cuda"])
        if value.get("numpy") is not None:
            numpy = importlib.import_module("numpy")
            numpy.random.set_state(value["numpy"])

    def _values_equal(self, left: Any, right: Any) -> bool:
        if type(left) is not type(right):
            return False
        if isinstance(left, Mapping):
            return set(left) == set(right) and all(
                self._values_equal(left[key], right[key]) for key in left
            )
        if isinstance(left, (tuple, list)):
            return len(left) == len(right) and all(
                self._values_equal(a, b) for a, b in zip(left, right)
            )
        if hasattr(self.torch, "is_tensor") and self.torch.is_tensor(left):
            return bool(self.torch.equal(left, right))
        if type(left).__module__.split(".", 1)[0] == "numpy" and hasattr(left, "shape"):
            try:
                numpy = importlib.import_module("numpy")
                return bool(numpy.array_equal(left, right))
            except (ImportError, TypeError, ValueError):
                return False
        try:
            result = left == right
        except Exception:
            return False
        return result is True

    def _dispose_runtime(self) -> None:
        self.model = None
        self.optimizer = None
        self.scheduler = None
        self.scope = None
        self._disposed = True
        gc.collect()
        try:
            self.torch.cuda.empty_cache()
        except Exception:
            pass

    def _adopt_runtime(self, probe: "TorchContinuousTrainingAdapter") -> None:
        self.model = probe.model
        self.tokenizer = probe.tokenizer
        self.exact_tokenizer = probe.exact_tokenizer
        self.optimizer = probe.optimizer
        self.scheduler = probe.scheduler
        self.scope = probe.scope
        self.data_cursor = probe.data_cursor
        self.global_step = probe.global_step
        self._checkpoint_model_root = probe._checkpoint_model_root
        self._training_cache = probe._training_cache
        self._validation_cache = probe._validation_cache
        self.last_update_metrics = probe.last_update_metrics
        self._disposed = False
        probe._disposed = True


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _nonnegative_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _betas(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 2
        and all(_positive_finite(item) and float(item) < 1 for item in value)
    )


def _existing_empty_payload(value: Path) -> Path:
    target = Path(value)
    if target.is_symlink() or not target.is_dir() or any(target.iterdir()):
        raise FullModelTrainingError("plan082_artifact_payload_unsafe")
    return target
