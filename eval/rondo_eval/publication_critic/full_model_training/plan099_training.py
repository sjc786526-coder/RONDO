"""Checkpoint-first five-head training, evaluation, selection, and recovery."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import random
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from ..qualification import (
    QualificationError,
    decision_config_sha256,
    decode_with_decision_config,
    evaluate_qualification_predictions,
)
from ..successor_task import HARD_DIMENSIONS, evaluate_pair_predictions
from ..tokenization import ExactTokenizer
from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    sha256_bytes,
    sha256_file,
)
from .plan082_adapter import verify_snapshot
from .plan099_artifacts import EVALUATION_RESULT_SCHEMA, Plan099ArtifactStore
from .plan099_contract import (
    REPO_ROOT,
    assess_development_checkpoint,
    checkpoint_selection_key,
    decision_margin_grid,
    freeze_sha256,
)
from .plan099_data import (
    Plan099Dataset,
    TokenizedDataset,
    feature_cache_identity,
    tokenize_dataset,
)
from .plan099_model import (
    assert_frozen_scope,
    build_from_exact_classifier,
    load_inference_ready,
    model_identity,
    save_inference_ready,
    verify_inference_ready,
    verify_initialization_parity,
)
from .plan099_objective import (
    flat_rows_from_tensor,
    structured_output_from_flat,
    torch_objective,
)


CONTROLLER_SCHEMA = "rondo-publication-critic-plan099-controller-state-v1"
UPDATE_SCHEMA = "rondo-publication-critic-plan099-update-receipt-v1"
TRAINING_STATE_SCHEMA = "rondo-publication-critic-plan099-training-state-v1"
RECOVERY_SCHEMA = "rondo-publication-critic-plan099-recovery-receipt-v1"
FORMAL_RESULT_SCHEMA = "rondo-publication-critic-plan099-formal-result-v1"
MODEL_LOCK_RELATIVE = Path(
    "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json"
)


class Plan099TorchAdapter:
    """Real frozen-feature adapter; construction is the only model-loading seam."""

    training_state_codec = "plan099-torch-state-v1"

    def __init__(
        self,
        *,
        torch_module: Any,
        student: Any,
        tokenizer: Any,
        device: Any,
        freeze: Mapping[str, Any],
        source_commit: str,
        train: TokenizedDataset,
        validation: TokenizedDataset,
        train_features: Any,
        validation_features: Any,
        initialization_parity: Mapping[str, Any],
    ) -> None:
        self.torch = torch_module
        self.student = student
        self.tokenizer = tokenizer
        self.exact_tokenizer = ExactTokenizer(tokenizer)
        self.device = device
        self.freeze = json.loads(json.dumps(freeze))
        self.recipe = self.freeze["recipe"]
        self.source_commit = source_commit
        self.train = train
        self.validation = validation
        self.train_features = train_features
        self.validation_features = validation_features
        self.initialization_parity = json.loads(json.dumps(initialization_parity))
        self.global_step = 0
        _configure_precision(self.torch)
        self.student.to(device)
        self.student.freeze_backbone()
        assert_frozen_scope(self.student, self.recipe)
        self.optimizer = self._new_optimizer()
        self.model_identity = model_identity(
            freeze_sha256=freeze_sha256(REPO_ROOT),
            source_commit=source_commit,
            model_contract=self.freeze["model"],
        )

    @classmethod
    def from_snapshot(
        cls,
        *,
        snapshot_root: Path,
        freeze: Mapping[str, Any],
        source_commit: str,
        train: TokenizedDataset,
        validation: TokenizedDataset,
        repo_root: Path | str = REPO_ROOT,
    ) -> "Plan099TorchAdapter":
        """Load the exact base only during an authorized real-model phase."""

        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
        root = Path(repo_root)
        verify_snapshot(Path(snapshot_root), root / MODEL_LOCK_RELATIVE)
        if not torch.cuda.is_available() or int(torch.cuda.device_count()) != 1:
            raise FullModelTrainingError("plan099_single_cuda_gpu_required")
        if str(torch.cuda.get_device_name(0)) != "NVIDIA L40S":
            raise FullModelTrainingError("plan099_exact_gpu_required")
        device = torch.device("cuda:0")
        _seed_everything(torch, int(freeze["recipe"]["seed"]))
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.set_float32_matmul_precision("highest")
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            snapshot_root, local_files_only=True, trust_remote_code=False
        )
        classifier = transformers.AutoModelForSequenceClassification.from_pretrained(
            snapshot_root,
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=torch.bfloat16,
            attn_implementation="sdpa",
        ).to(device)
        classifier.eval()
        student = build_from_exact_classifier(
            classifier, model_contract=freeze["model"]
        ).to(device)
        samples = train.inputs[:2]
        width = max(len(item.input_ids) for item in samples) + 1
        pad = int(tokenizer.pad_token_id)
        input_ids = torch.tensor(
            [
                list(item.input_ids) + [pad] * (width - len(item.input_ids))
                for item in samples
            ],
            dtype=torch.long,
            device=device,
        )
        attention_mask = torch.tensor(
            [
                [1] * len(item.input_ids) + [0] * (width - len(item.input_ids))
                for item in samples
            ],
            dtype=torch.long,
            device=device,
        )
        parity = verify_initialization_parity(
            classifier,
            student,
            input_ids=input_ids,
            attention_mask=attention_mask,
        )
        del classifier
        train_features = _extract_features(torch, student, train, device)
        validation_features = _extract_features(torch, student, validation, device)
        return cls(
            torch_module=torch,
            student=student,
            tokenizer=tokenizer,
            device=device,
            freeze=freeze,
            source_commit=source_commit,
            train=train,
            validation=validation,
            train_features=train_features,
            validation_features=validation_features,
            initialization_parity=parity,
        )

    @classmethod
    def from_recovery_checkpoint(
        cls,
        *,
        model_root: Path,
        freeze: Mapping[str, Any],
        source_commit: str,
        train_dataset: Plan099Dataset,
        validation_dataset: Plan099Dataset,
    ) -> "Plan099TorchAdapter":
        """Create a fresh-process adapter from the checkpoint, not the exact base."""

        torch = importlib.import_module("torch")
        if not torch.cuda.is_available() or int(torch.cuda.device_count()) != 1:
            raise FullModelTrainingError("plan099_single_cuda_gpu_required")
        if str(torch.cuda.get_device_name(0)) != "NVIDIA L40S":
            raise FullModelTrainingError("plan099_exact_gpu_required")
        device = torch.device("cuda:0")
        student, tokenizer, receipt = load_inference_ready(model_root)
        exact = ExactTokenizer(tokenizer)
        model_input = freeze["model"]["input"]
        train = tokenize_dataset(train_dataset, exact, model_input_identity=model_input)
        validation = tokenize_dataset(
            validation_dataset, exact, model_input_identity=model_input
        )
        train_features = torch.zeros(
            (len(train.inputs), 2048), dtype=torch.bfloat16, device="cpu"
        )
        validation_features = torch.zeros(
            (len(validation.inputs), 2048), dtype=torch.bfloat16, device="cpu"
        )
        return cls(
            torch_module=torch,
            student=student,
            tokenizer=tokenizer,
            device=device,
            freeze=freeze,
            source_commit=source_commit,
            train=train,
            validation=validation,
            train_features=train_features,
            validation_features=validation_features,
            initialization_parity={
                "schema": "rondo-publication-critic-plan099-recovery-shell-v1",
                "checkpoint_model_exact_tree_sha256": receipt["exact_tree_sha256"],
            },
        )

    def apply_update(self, dataset: Plan099Dataset) -> dict[str, Any]:
        if dataset.split not in {"train", "commissioning"}:
            raise FullModelTrainingError("plan099_gradient_split_forbidden")
        if dataset.split == "train":
            features = self.train_features
            tokenized = self.train
        else:
            indices = [
                self.train.dataset.candidate_ids.index(value)
                for value in dataset.candidate_ids
            ]
            features = self.train_features[indices]
            tokenized = TokenizedDataset(
                dataset=dataset,
                inputs=tuple(self.train.inputs[index] for index in indices),
                identity={"content_sha256": "commissioning-subset"},
            )
        self.student.train(True)
        assert_frozen_scope(self.student, self.recipe)
        before = {
            name: parameter.detach().float().clone()
            for name, parameter in self.student.named_parameters()
            if parameter.requires_grad
        }
        self.optimizer.zero_grad(set_to_none=True)
        logits = self.student.logits_from_features(features.to(self.device)).float()
        losses = torch_objective(
            candidate_ids=tokenized.dataset.candidate_ids,
            flat_logits=logits,
            labels_by_id=tokenized.dataset.labels_by_id,
            pairs=tokenized.dataset.pairs,
            recipe=self.recipe,
        )
        losses["total"].backward()
        gradient_norm = float(
            self.torch.nn.utils.clip_grad_norm_(
                [
                    parameter
                    for parameter in self.student.parameters()
                    if parameter.requires_grad
                ],
                float(self.recipe["optimizer"]["gradient_clip_norm"]),
            ).item()
        )
        if not math.isfinite(gradient_norm) or gradient_norm <= 0.0:
            raise FullModelTrainingError("plan099_gradient_invalid")
        self.optimizer.step()
        self.global_step += 1
        delta = max(
            float((parameter.detach().float() - before[name]).abs().max().item())
            for name, parameter in self.student.named_parameters()
            if parameter.requires_grad
        )
        if not math.isfinite(delta) or delta <= 0.0:
            raise FullModelTrainingError("plan099_nonzero_update_required")
        return {
            "schema": UPDATE_SCHEMA,
            "global_step": self.global_step,
            "dataset_split": dataset.split,
            "candidate_rows": len(dataset.candidates),
            "pair_rows": len(dataset.pairs),
            "losses": {
                key: float(value.detach().float().cpu().item())
                for key, value in losses.items()
            },
            "gradient_norm_before_clip": gradient_norm,
            "maximum_parameter_delta": delta,
        }

    def evaluate(self, dataset: Plan099Dataset) -> dict[str, Any]:
        tokenized, features = self._dataset_cache(dataset)
        self.student.eval()
        with self.torch.no_grad():
            logits = self.student.logits_from_features(features.to(self.device)).float()
            losses = torch_objective(
                candidate_ids=tokenized.dataset.candidate_ids,
                flat_logits=logits,
                labels_by_id=tokenized.dataset.labels_by_id,
                pairs=tokenized.dataset.pairs,
                recipe=self.recipe,
            )
        rows = flat_rows_from_tensor(logits)
        return {
            "flat_logits": rows,
            "structured_output": structured_output_from_flat(rows),
            "losses": {
                key: float(value.detach().float().cpu().item())
                for key, value in losses.items()
            },
        }

    def save_model(self, destination: Path) -> None:
        save_inference_ready(
            self.student,
            self.tokenizer,
            destination,
            identity=self.model_identity,
        )

    def current_model_artifact_sha256(self) -> str:
        heads = {}
        for name, parameter in self.student.named_parameters():
            if parameter.requires_grad:
                raw = parameter.detach().float().contiguous().cpu().numpy().tobytes()
                heads[name] = hashlib.sha256(raw).hexdigest()
        return sha256_bytes(
            canonical_json_bytes(
                {
                    "model_identity_sha256": self.model_identity["content_sha256"],
                    "head_weights": heads,
                }
            )
        )

    def capture_training_state(self, selection: Mapping[str, Any]) -> dict[str, Any]:
        torch = self.torch
        return {
            "schema": TRAINING_STATE_SCHEMA,
            "global_step": self.global_step,
            "optimizer": self.optimizer.state_dict(),
            "scheduler": {"name": "constant", "last_step": self.global_step},
            "precision": json.loads(json.dumps(self.recipe["precision"])),
            "rng": {
                "python": random.getstate(),
                "torch_cpu": torch.random.get_rng_state(),
                "torch_cuda": torch.cuda.get_rng_state_all(),
            },
            "data_cursor": {"macro_update": self.global_step, "shuffle": False},
            "selection": json.loads(json.dumps(selection)),
            "feature_caches": {
                "train": self.train_features.detach().cpu(),
                "validation": self.validation_features.detach().cpu(),
            },
            "feature_identities": {
                "train": feature_cache_identity(
                    self.train,
                    model_identity_sha256=self.model_identity["content_sha256"],
                    feature_shape=self.train_features.shape,
                    feature_dtype=str(self.train_features.dtype).removeprefix("torch."),
                    feature_content_sha256=_feature_sha256(
                        self.torch, self.train_features
                    ),
                ),
                "validation": feature_cache_identity(
                    self.validation,
                    model_identity_sha256=self.model_identity["content_sha256"],
                    feature_shape=self.validation_features.shape,
                    feature_dtype=str(self.validation_features.dtype).removeprefix(
                        "torch."
                    ),
                    feature_content_sha256=_feature_sha256(
                        self.torch, self.validation_features
                    ),
                ),
            },
        }

    def write_training_state(self, destination: Path, value: Mapping[str, Any]) -> None:
        destination.mkdir(mode=0o700)
        self.torch.save(dict(value), destination / "training-state.pt")
        identity = {
            "schema": TRAINING_STATE_SCHEMA,
            "global_step": value["global_step"],
            "codec": self.training_state_codec,
            "payload_sha256": sha256_file(destination / "training-state.pt"),
        }
        (destination / "training-state-identity.json").write_bytes(
            pretty_json_bytes(identity)
        )

    def read_training_state(self, root: Path) -> Mapping[str, Any]:
        identity = read_json(root / "training-state-identity.json")
        if (
            identity.get("schema") != TRAINING_STATE_SCHEMA
            or identity.get("codec") != self.training_state_codec
            or identity.get("payload_sha256") != sha256_file(root / "training-state.pt")
        ):
            raise FullModelTrainingError("plan099_training_state_identity_invalid")
        value = self.torch.load(
            root / "training-state.pt", map_location="cpu", weights_only=False
        )
        if value.get("schema") != TRAINING_STATE_SCHEMA:
            raise FullModelTrainingError("plan099_training_state_invalid")
        return value

    def restore(self, model_root: Path, state: Mapping[str, Any]) -> None:
        required = {
            "schema",
            "global_step",
            "optimizer",
            "scheduler",
            "precision",
            "rng",
            "data_cursor",
            "selection",
            "feature_caches",
            "feature_identities",
        }
        if not isinstance(state, Mapping) or set(state) != required:
            raise FullModelTrainingError("plan099_training_state_invalid")
        step = state.get("global_step")
        if (
            not isinstance(step, int)
            or isinstance(step, bool)
            or step < 1
            or state.get("scheduler") != {"name": "constant", "last_step": step}
            or state.get("precision") != self.recipe["precision"]
            or state.get("data_cursor") != {"macro_update": step, "shuffle": False}
            or not isinstance(state.get("selection"), Mapping)
        ):
            raise FullModelTrainingError("plan099_training_state_invalid")
        student, tokenizer, receipt = load_inference_ready(model_root)
        if receipt["identity"] != self.model_identity:
            raise FullModelTrainingError("plan099_recovery_model_identity_mismatch")
        self.student = student.to(self.device)
        self.tokenizer = tokenizer
        self.exact_tokenizer = ExactTokenizer(tokenizer)
        self.student.freeze_backbone()
        assert_frozen_scope(self.student, self.recipe)
        self.optimizer = self._new_optimizer()
        self.optimizer.load_state_dict(state["optimizer"])
        self.global_step = step
        self.train_features = state["feature_caches"]["train"]
        self.validation_features = state["feature_caches"]["validation"]
        expected_identities = {
            "train": feature_cache_identity(
                self.train,
                model_identity_sha256=self.model_identity["content_sha256"],
                feature_shape=self.train_features.shape,
                feature_dtype=str(self.train_features.dtype).removeprefix("torch."),
                feature_content_sha256=_feature_sha256(self.torch, self.train_features),
            ),
            "validation": feature_cache_identity(
                self.validation,
                model_identity_sha256=self.model_identity["content_sha256"],
                feature_shape=self.validation_features.shape,
                feature_dtype=str(self.validation_features.dtype).removeprefix(
                    "torch."
                ),
                feature_content_sha256=_feature_sha256(
                    self.torch, self.validation_features
                ),
            ),
        }
        if state.get("feature_identities") != expected_identities:
            raise FullModelTrainingError("plan099_feature_cache_identity_invalid")
        if not bool(
            self.torch.isfinite(self.train_features.float()).all().item()
        ) or not bool(
            self.torch.isfinite(self.validation_features.float()).all().item()
        ):
            raise FullModelTrainingError("plan099_feature_cache_nonfinite")
        random.setstate(state["rng"]["python"])
        self.torch.random.set_rng_state(state["rng"]["torch_cpu"])
        self.torch.cuda.set_rng_state_all(state["rng"]["torch_cuda"])

    def runtime_identity(self) -> dict[str, Any]:
        return {
            "runtime": "torch-frozen-feature-five-head",
            "torch": str(self.torch.__version__),
            "cuda": str(self.torch.version.cuda),
            "gpu": str(self.torch.cuda.get_device_name(0)),
            "device_count": int(self.torch.cuda.device_count()),
            "source_commit": self.source_commit,
            "model_identity_sha256": self.model_identity["content_sha256"],
            "initialization_parity": self.initialization_parity,
        }

    def _new_optimizer(self) -> Any:
        optimizer = self.recipe["optimizer"]
        return self.torch.optim.AdamW(
            [
                parameter
                for parameter in self.student.parameters()
                if parameter.requires_grad
            ],
            lr=float(optimizer["learning_rate"]),
            betas=tuple(float(value) for value in optimizer["betas"]),
            eps=float(optimizer["epsilon"]),
            weight_decay=float(optimizer["weight_decay"]),
            fused=False,
            foreach=False,
        )

    def _dataset_cache(self, dataset: Plan099Dataset) -> tuple[TokenizedDataset, Any]:
        if dataset.split == "train":
            return self.train, self.train_features
        if dataset.split == "validation":
            return self.validation, self.validation_features
        raise FullModelTrainingError("plan099_evaluation_split_invalid")


class Plan099TrainingController:
    """Checkpoint before every development evaluation and replay overlays on resume."""

    def __init__(
        self,
        *,
        freeze: Mapping[str, Any],
        run_kind: str,
        namespace: str,
        source_identity: Mapping[str, Any],
        artifact_store: Plan099ArtifactStore,
        process_nonce: str | None = None,
        state_publisher: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        if run_kind not in {"commissioning", "formal"}:
            raise FullModelTrainingError("plan099_run_kind_invalid")
        self.freeze = json.loads(json.dumps(freeze))
        self.run_kind = run_kind
        self.namespace = namespace
        self.source_identity = json.loads(json.dumps(source_identity))
        self.store = artifact_store
        self._state_publisher = state_publisher
        self.state = {
            "schema": CONTROLLER_SCHEMA,
            "run_kind": run_kind,
            "namespace": namespace,
            "freeze_sha256": freeze_sha256(REPO_ROOT),
            "source_identity": self.source_identity,
            "process_nonce": process_nonce or secrets.token_hex(16),
            "runtime_identity": None,
            "status": "created",
            "current_step": 0,
            "updates": [],
            "base_evaluation": None,
            "evaluations": [],
            "selection": {"best_checkpoint_id": None, "best_key": None},
            "fresh_process_recoveries": {},
            "pending_checkpoint_id": None,
            "latest_checkpoint_id": None,
            "terminal": None,
        }

    @classmethod
    def from_state(
        cls,
        *,
        freeze: Mapping[str, Any],
        artifact_store: Plan099ArtifactStore,
        value: Mapping[str, Any],
        state_publisher: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> "Plan099TrainingController":
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != CONTROLLER_SCHEMA
            or value.get("freeze_sha256") != freeze_sha256(REPO_ROOT)
        ):
            raise FullModelTrainingError("plan099_controller_state_invalid")
        controller = cls(
            freeze=freeze,
            run_kind=str(value["run_kind"]),
            namespace=str(value["namespace"]),
            source_identity=value["source_identity"],
            artifact_store=artifact_store,
            process_nonce=str(value["process_nonce"]),
            state_publisher=state_publisher,
        )
        controller.state = json.loads(json.dumps(value))
        return controller

    def initialize(self, adapter: Any, validation: Plan099Dataset) -> dict[str, Any]:
        if self.state["status"] != "created":
            raise FullModelTrainingError("plan099_controller_already_initialized")
        base = evaluate_development(
            adapter,
            validation,
            self.freeze,
            model_artifact_sha256=adapter.current_model_artifact_sha256(),
            checkpoint=None,
        )
        self.state["base_evaluation"] = base
        self.state["runtime_identity"] = adapter.runtime_identity()
        self.state["status"] = "paused"
        self._publish_state()
        return self.summary()

    def run(
        self,
        adapter: Any,
        *,
        training: Plan099Dataset,
        validation: Plan099Dataset,
        stop_after: int | None = None,
    ) -> dict[str, Any]:
        if self.state["status"] != "paused":
            raise FullModelTrainingError("plan099_controller_not_runnable")
        maximum = (
            int(self.freeze["recipe"]["control"]["commissioning_updates"])
            if self.run_kind == "commissioning"
            else int(self.freeze["recipe"]["control"]["maximum_formal_updates"])
        )
        target = maximum if stop_after is None else stop_after
        allowed_stops = (
            {1}
            if self.run_kind == "commissioning"
            else set(self.freeze["recipe"]["control"]["checkpoint_steps"])
        )
        if (
            target < self.state["current_step"]
            or target > maximum
            or target not in allowed_stops
        ):
            raise FullModelTrainingError("plan099_stop_point_invalid")
        checkpoint_steps = (
            {1}
            if self.run_kind == "commissioning"
            else set(self.freeze["recipe"]["control"]["checkpoint_steps"])
        )
        for step in range(int(self.state["current_step"]) + 1, target + 1):
            receipt = adapter.apply_update(training)
            if receipt.get("global_step") != step:
                raise FullModelTrainingError("plan099_update_step_drifted")
            self.state["updates"].append(json.loads(json.dumps(receipt)))
            self.state["current_step"] = step
            if step in checkpoint_steps:
                self._checkpoint_then_evaluate(adapter, validation, step)
            if self.state["status"] == "recovery_required":
                break
        if self.state["current_step"] == maximum and self.state["status"] == "paused":
            self._finish()
        self._publish_state()
        return self.summary()

    def recover_latest_for_continuation(
        self,
        adapter: Any,
        *,
        checkpoint_id: str,
        validation: Plan099Dataset,
        process_nonce: str | None = None,
    ) -> dict[str, Any]:
        if (
            self.state["status"] != "paused"
            or checkpoint_id != self.state.get("latest_checkpoint_id")
            or int(checkpoint_id.rsplit("-", 1)[1]) != self.state["current_step"]
        ):
            raise FullModelTrainingError("plan099_continuation_checkpoint_invalid")
        nonce = process_nonce or secrets.token_hex(16)
        if nonce == self.state["process_nonce"]:
            raise FullModelTrainingError("plan099_fresh_process_required")
        checkpoint = self.store.verify_checkpoint(checkpoint_id)
        _controller, training_state, model_root = self.store.read_checkpoint(
            checkpoint_id, state_reader=adapter.read_training_state
        )
        adapter.restore(model_root, training_state)
        expected = self.store.read_evaluation_result(checkpoint_id)
        replay = evaluate_development(
            adapter,
            validation,
            self.freeze,
            model_artifact_sha256=expected["checkpoint"]["model_exact_tree_sha256"],
            checkpoint=expected["checkpoint"],
        )
        if checkpoint["content_sha256"] != expected["checkpoint"][
            "content_sha256"
        ] or sha256_bytes(canonical_json_bytes(replay)) != sha256_bytes(
            canonical_json_bytes(expected)
        ):
            raise FullModelTrainingError("plan099_recovery_evaluation_mismatch")
        self.state["process_nonce"] = nonce
        self._publish_state()
        return self.summary()

    def _checkpoint_then_evaluate(
        self, adapter: Any, validation: Plan099Dataset, step: int
    ) -> None:
        checkpoint_id = f"checkpoint-attempt-0-step-{step:06d}"
        self.state["status"] = "evaluation_pending"
        self.state["pending_checkpoint_id"] = checkpoint_id
        training_state = adapter.capture_training_state(self.state["selection"])
        checkpoint = self.store.save_checkpoint(
            checkpoint_id,
            model_saver=adapter.save_model,
            training_state=training_state,
            controller_state=self.state,
            metadata={
                "global_step": step,
                "run_kind": self.run_kind,
                "namespace": self.namespace,
                "training_state_codec": adapter.training_state_codec,
                "evaluation_pending": True,
            },
            state_writer=adapter.write_training_state,
        )
        checkpoint = self.store.verify_checkpoint(checkpoint_id)
        self.state["latest_checkpoint_id"] = checkpoint_id
        self._publish_state()
        self._evaluate_saved_checkpoint(adapter, validation, checkpoint_id, checkpoint)

    def _evaluate_saved_checkpoint(
        self,
        adapter: Any,
        validation: Plan099Dataset,
        checkpoint_id: str,
        checkpoint: Mapping[str, Any],
    ) -> None:
        step = int(checkpoint_id.rsplit("-", 1)[1])
        model_receipt = verify_inference_ready(
            self.store.root / "recovery-checkpoints" / checkpoint_id / "payload"
        )
        evaluation = evaluate_development(
            adapter,
            validation,
            self.freeze,
            model_artifact_sha256=model_receipt["exact_tree_sha256"],
            checkpoint={
                "checkpoint_id": checkpoint_id,
                "content_sha256": checkpoint["content_sha256"],
                "bytes": checkpoint["bytes"],
                "model_exact_tree_sha256": model_receipt["exact_tree_sha256"],
            },
        )
        self.store.publish_evaluation_result(
            checkpoint_id,
            checkpoint_content_sha256=checkpoint["content_sha256"],
            value=evaluation,
        )
        self.state["evaluations"].append(
            {
                "checkpoint_id": checkpoint_id,
                "content_sha256": checkpoint["content_sha256"],
                "evaluation_sha256": sha256_bytes(canonical_json_bytes(evaluation)),
            }
        )
        self.state["pending_checkpoint_id"] = None
        if evaluation["assessment"] is not None:
            key = checkpoint_selection_key(
                evaluation["assessment"],
                global_step=step,
                decision_config_sha256=evaluation["decision_config_sha256"],
                checkpoint_content_sha256=checkpoint["content_sha256"],
            )
            previous = self.state["selection"]["best_key"]
            encoded = _json_selection_key(key)
            if previous is None or tuple(key) > _selection_key_from_json(previous):
                self.state["selection"] = {
                    "best_checkpoint_id": checkpoint_id,
                    "best_key": encoded,
                }
        recovery_step = int(
            self.freeze["recipe"]["control"]["fresh_process_recovery_step"]
        )
        if self.run_kind == "commissioning" or step == recovery_step:
            self.state["status"] = "recovery_required"
            self.state["recovery_checkpoint_id"] = checkpoint_id
        else:
            self.state["status"] = "paused"
        self._publish_state()

    def recover_pending_evaluation(
        self, adapter: Any, *, validation: Plan099Dataset
    ) -> dict[str, Any]:
        if self.state["status"] != "evaluation_pending":
            raise FullModelTrainingError("plan099_evaluation_not_pending")
        checkpoint_id = str(self.state.get("pending_checkpoint_id") or "")
        checkpoint = self.store.verify_checkpoint(checkpoint_id)
        controller_state, training_state, model_root = self.store.read_checkpoint(
            checkpoint_id, state_reader=adapter.read_training_state
        )
        if int(controller_state.get("current_step", -1)) != int(
            self.state["current_step"]
        ):
            raise FullModelTrainingError("plan099_recovery_controller_mismatch")
        adapter.restore(model_root, training_state)
        if self.store.has_evaluation_result(checkpoint_id):
            expected = self.store.read_evaluation_result(checkpoint_id)
            replay = evaluate_development(
                adapter,
                validation,
                self.freeze,
                model_artifact_sha256=expected["checkpoint"]["model_exact_tree_sha256"],
                checkpoint=expected["checkpoint"],
            )
            if sha256_bytes(canonical_json_bytes(replay)) != sha256_bytes(
                canonical_json_bytes(expected)
            ):
                raise FullModelTrainingError("plan099_recovery_evaluation_mismatch")
            self._adopt_existing_evaluation(checkpoint_id, checkpoint, expected)
        else:
            self._evaluate_saved_checkpoint(
                adapter, validation, checkpoint_id, checkpoint
            )
        return self.summary()

    def resume_fresh_process(
        self,
        adapter: Any,
        *,
        checkpoint_id: str,
        validation: Plan099Dataset,
        process_nonce: str | None = None,
    ) -> dict[str, Any]:
        if self.state["status"] != "recovery_required":
            raise FullModelTrainingError("plan099_recovery_not_required")
        nonce = process_nonce or secrets.token_hex(16)
        if nonce == self.state["process_nonce"]:
            raise FullModelTrainingError("plan099_fresh_process_required")
        checkpoint = self.store.verify_checkpoint(checkpoint_id)
        controller_state, training_state, model_root = self.store.read_checkpoint(
            checkpoint_id, state_reader=adapter.read_training_state
        )
        checkpoint_step = int(checkpoint_id.rsplit("-", 1)[1])
        if (
            int(controller_state.get("current_step", -1)) != checkpoint_step
            or controller_state.get("freeze_sha256") != self.state["freeze_sha256"]
            or controller_state.get("namespace") != self.state["namespace"]
            or controller_state.get("source_identity") != self.state["source_identity"]
        ):
            raise FullModelTrainingError("plan099_recovery_controller_mismatch")
        adapter.restore(model_root, training_state)
        expected = self.store.read_evaluation_result(checkpoint_id)
        replay = evaluate_development(
            adapter,
            validation,
            self.freeze,
            model_artifact_sha256=expected["checkpoint"]["model_exact_tree_sha256"],
            checkpoint=expected["checkpoint"],
        )
        expected_sha = sha256_bytes(canonical_json_bytes(expected))
        replay_sha = sha256_bytes(canonical_json_bytes(replay))
        if replay_sha != expected_sha:
            raise FullModelTrainingError("plan099_recovery_evaluation_mismatch")
        self.state["process_nonce"] = nonce
        recovery = {
            "schema": RECOVERY_SCHEMA,
            "checkpoint_id": checkpoint_id,
            "checkpoint_content_sha256": checkpoint["content_sha256"],
            "evaluation_sha256": replay_sha,
            "prior_process_nonce_sha256": hashlib.sha256(
                controller_state["process_nonce"].encode("utf-8")
            ).hexdigest(),
            "new_process_nonce_sha256": hashlib.sha256(
                nonce.encode("utf-8")
            ).hexdigest(),
            "reproduced": True,
            "runtime_identity": adapter.runtime_identity(),
        }
        self.state["fresh_process_recoveries"][checkpoint_id] = recovery
        maximum = (
            int(self.freeze["recipe"]["control"]["commissioning_updates"])
            if self.run_kind == "commissioning"
            else int(self.freeze["recipe"]["control"]["maximum_formal_updates"])
        )
        self.state["status"] = "paused"
        if self.state["current_step"] == maximum:
            self._finish()
        self._publish_state()
        return self.summary()

    def _finish(self) -> None:
        if not self.state["fresh_process_recoveries"]:
            raise FullModelTrainingError("plan099_fresh_process_recovery_required")
        best_id = self.state["selection"]["best_checkpoint_id"]
        if best_id not in self.state["fresh_process_recoveries"]:
            self.state["status"] = "recovery_required"
            self.state["recovery_checkpoint_id"] = best_id
            self._publish_state()
            return
        best = self.store.read_evaluation_result(best_id) if best_id else None
        base = self.state["base_evaluation"]
        candidate = False
        if best is not None and best["assessment"]["eligible"]:
            base_assessment = base.get("assessment")
            candidate = (
                base_assessment is None
                or not base_assessment["eligible"]
                or _quality_key(best["assessment"]) > _quality_key(base_assessment)
            )
        disposition = (
            "COMMISSIONING-PASS"
            if self.run_kind == "commissioning"
            else ("CANDIDATE" if candidate else "NO-GO")
        )
        latest_id = (
            self.state["evaluations"][-1]["checkpoint_id"]
            if self.state["evaluations"]
            else None
        )
        recovery_step = (
            1
            if self.run_kind == "commissioning"
            else int(self.freeze["recipe"]["control"]["fresh_process_recovery_step"])
        )
        recovery_id = f"checkpoint-attempt-0-step-{recovery_step:06d}"
        keep = {
            value for value in (best_id, latest_id, recovery_id) if value is not None
        }
        retention = self.store.prune(keep_snapshot_ids=set(), keep_checkpoint_ids=keep)
        retention["kept_checkpoints"] = sorted(keep)
        retention["maximum_full_checkpoints"] = 3
        for checkpoint_id in sorted(keep):
            self.store.mark_retention_complete(checkpoint_id)
        self.state["terminal"] = {
            "schema": FORMAL_RESULT_SCHEMA,
            "run_kind": self.run_kind,
            "disposition": disposition,
            "best_checkpoint_id": best_id,
            "valid_formal_trajectory": self.run_kind == "formal",
            "development_only": True,
            "qualification_claim": False,
            "retention": retention,
            "reason": (
                "eligible_and_strictly_improved_from_step_zero"
                if candidate
                else "valid_trajectory_did_not_meet_prefrozen_development_gate"
            ),
        }
        self.state["status"] = "terminal"
        self._publish_state()

    def _adopt_existing_evaluation(
        self,
        checkpoint_id: str,
        checkpoint: Mapping[str, Any],
        evaluation: Mapping[str, Any],
    ) -> None:
        if not any(
            row["checkpoint_id"] == checkpoint_id for row in self.state["evaluations"]
        ):
            self.state["evaluations"].append(
                {
                    "checkpoint_id": checkpoint_id,
                    "content_sha256": checkpoint["content_sha256"],
                    "evaluation_sha256": sha256_bytes(canonical_json_bytes(evaluation)),
                }
            )
        step = int(checkpoint_id.rsplit("-", 1)[1])
        assessment = evaluation.get("assessment")
        if assessment is not None:
            key = checkpoint_selection_key(
                assessment,
                global_step=step,
                decision_config_sha256=evaluation["decision_config_sha256"],
                checkpoint_content_sha256=checkpoint["content_sha256"],
            )
            previous = self.state["selection"]["best_key"]
            if previous is None or key > _selection_key_from_json(previous):
                self.state["selection"] = {
                    "best_checkpoint_id": checkpoint_id,
                    "best_key": _json_selection_key(key),
                }
        self.state["pending_checkpoint_id"] = None
        recovery_step = int(
            self.freeze["recipe"]["control"]["fresh_process_recovery_step"]
        )
        if self.run_kind == "commissioning" or step == recovery_step:
            self.state["status"] = "recovery_required"
            self.state["recovery_checkpoint_id"] = checkpoint_id
        else:
            self.state["status"] = "paused"
        self._publish_state()

    def _publish_state(self) -> None:
        if self._state_publisher is not None:
            self._state_publisher(self.summary())

    def summary(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.state))


def evaluate_development(
    adapter: Any,
    validation: Plan099Dataset,
    freeze: Mapping[str, Any],
    *,
    model_artifact_sha256: str,
    checkpoint: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if validation.split != "validation":
        raise FullModelTrainingError("plan099_validation_entrypoint_required")
    raw = adapter.evaluate(validation)
    output = raw["structured_output"]
    release = _development_release(validation)
    try:
        decision = release.select_and_freeze_validation_decision_config(
            validation_candidate_ids=validation.candidate_ids,
            validation_output=output,
            candidate_head_margins=decision_margin_grid(freeze["development_gate"]),
            model_artifact_sha256=model_artifact_sha256,
        )
    except QualificationError as exc:
        return {
            "schema": EVALUATION_RESULT_SCHEMA,
            "checkpoint": json.loads(json.dumps(checkpoint)),
            "output_sha256": sha256_bytes(canonical_json_bytes(output)),
            "losses": raw["losses"],
            "decision_config": None,
            "decision_config_sha256": None,
            "assessment": None,
            "ineligible_reason": f"decision_config_unavailable:{type(exc).__name__}",
        }
    predicted = decode_with_decision_config(output, decision)
    gold = tuple(row["labels"] for row in validation.candidates)
    metrics = evaluate_qualification_predictions(gold, predicted)
    predicted_by_id = dict(zip(validation.candidate_ids, predicted, strict=True))
    pair_rows = [
        {
            "pair_id": pair["pair_id"],
            "kind": pair["kind"],
            "left_labels": predicted_by_id[pair["left_candidate_id"]],
            "right_labels": predicted_by_id[pair["right_candidate_id"]],
            "target_dimension": pair["target_dimension"],
        }
        for pair in validation.pairs
    ]
    pair_evaluation = evaluate_pair_predictions(pair_rows)
    assessment = assess_development_checkpoint(
        metrics=metrics,
        pair_evaluation=pair_evaluation,
        predicted_rows=predicted,
        training_loss=float(raw["losses"]["total"]),
    )
    return {
        "schema": EVALUATION_RESULT_SCHEMA,
        "checkpoint": json.loads(json.dumps(checkpoint)),
        "output_sha256": sha256_bytes(canonical_json_bytes(output)),
        "losses": raw["losses"],
        "decision_config": decision,
        "decision_config_sha256": decision_config_sha256(decision),
        "assessment": assessment,
        "ineligible_reason": None,
    }


def validate_terminal_candidate(
    state: Mapping[str, Any], store: Plan099ArtifactStore
) -> dict[str, Any]:
    """Recompute the complete formal candidate decision from immutable artifacts."""

    terminal = state.get("terminal")
    source = state.get("source_identity")
    if (
        state.get("schema") != CONTROLLER_SCHEMA
        or state.get("run_kind") != "formal"
        or state.get("status") != "terminal"
        or not isinstance(terminal, Mapping)
        or terminal.get("disposition") != "CANDIDATE"
        or terminal.get("valid_formal_trajectory") is not True
        or terminal.get("development_only") is not True
        or terminal.get("qualification_claim") is not False
        or state.get("freeze_sha256") != freeze_sha256(REPO_ROOT)
        or not isinstance(source, Mapping)
        or source.get("freeze_sha256") != state.get("freeze_sha256")
    ):
        raise FullModelTrainingError("plan099_candidate_export_not_allowed")
    ranked: list[tuple[tuple[Any, ...], str, dict[str, Any]]] = []
    seen: set[str] = set()
    for row in state.get("evaluations", []):
        checkpoint_id = str(row.get("checkpoint_id", ""))
        if checkpoint_id in seen:
            raise FullModelTrainingError("plan099_candidate_trajectory_invalid")
        seen.add(checkpoint_id)
        checkpoint = store.verify_checkpoint(checkpoint_id)
        evaluation = store.read_evaluation_result(checkpoint_id)
        if (
            row.get("content_sha256") != checkpoint["content_sha256"]
            or row.get("evaluation_sha256")
            != sha256_bytes(canonical_json_bytes(evaluation))
            or evaluation.get("assessment") is None
        ):
            raise FullModelTrainingError("plan099_candidate_trajectory_invalid")
        step = int(checkpoint_id.rsplit("-", 1)[1])
        ranked.append(
            (
                checkpoint_selection_key(
                    evaluation["assessment"],
                    global_step=step,
                    decision_config_sha256=evaluation["decision_config_sha256"],
                    checkpoint_content_sha256=checkpoint["content_sha256"],
                ),
                checkpoint_id,
                evaluation,
            )
        )
    if len(ranked) != 5:
        raise FullModelTrainingError("plan099_candidate_trajectory_invalid")
    if seen != {f"checkpoint-attempt-0-step-{step:06d}" for step in (2, 4, 8, 12, 16)}:
        raise FullModelTrainingError("plan099_candidate_trajectory_invalid")
    _key, best_id, best = max(ranked, key=lambda item: item[0])
    base = state.get("base_evaluation")
    recoveries = state.get("fresh_process_recoveries")
    if (
        best_id != terminal.get("best_checkpoint_id")
        or best_id != state.get("selection", {}).get("best_checkpoint_id")
        or not best["assessment"]["eligible"]
        or not isinstance(base, Mapping)
        or (
            base.get("assessment") is not None
            and base["assessment"]["eligible"]
            and _quality_key(best["assessment"]) <= _quality_key(base["assessment"])
        )
        or not isinstance(recoveries, Mapping)
        or recoveries.get(best_id, {}).get("reproduced") is not True
        or recoveries[best_id].get("evaluation_sha256")
        != sha256_bytes(canonical_json_bytes(best))
        or not store.has_retention_completion(best_id)
    ):
        raise FullModelTrainingError("plan099_candidate_decision_invalid")
    return {
        "checkpoint_id": best_id,
        "evaluation": best,
        "recovery": json.loads(json.dumps(recoveries[best_id])),
    }


def _extract_features(
    torch: Any, student: Any, tokenized: TokenizedDataset, device: Any
) -> Any:
    rows = []
    student.eval()
    with torch.no_grad():
        for item in tokenized.inputs:
            ids = torch.tensor([item.input_ids], dtype=torch.long, device=device)
            mask = torch.ones_like(ids)
            pooled = student.pooled_features(input_ids=ids, attention_mask=mask)
            rows.append(pooled.detach().to(dtype=torch.bfloat16, device="cpu"))
    result = torch.cat(rows, dim=0)
    if tuple(result.shape) != (len(tokenized.inputs), 2048):
        raise FullModelTrainingError("plan099_feature_cache_shape_invalid")
    return result


def _development_release(validation: Plan099Dataset) -> Any:
    from ..directional_data import DevelopmentRelease
    from .plan099_contract import V10_ROOT

    release = DevelopmentRelease.open(REPO_ROOT / V10_ROOT, repo_root=REPO_ROOT)
    expected, _pairs = release.load_validation()
    if tuple(row["candidate_id"] for row in expected) != validation.candidate_ids:
        raise FullModelTrainingError("plan099_validation_identity_mismatch")
    return release


def _quality_key(assessment: Mapping[str, Any]) -> tuple[Any, ...]:
    metrics = assessment["metrics"]
    recalls = []
    for dimension in HARD_DIMENSIONS:
        confusion = metrics["per_dimension"][dimension]["confusion"]
        values = []
        for label, row in confusion.items():
            denominator = sum(row.values())
            values.append(row[label] / denominator if denominator else -1.0)
        recalls.append(sum(values) / len(values))
    return (
        bool(assessment["eligible"]),
        min(recalls),
        -int(metrics["gate"]["false_pass"]),
        int(metrics["gate"]["correct"]),
        -int(metrics["gate"]["false_rewrite"]),
        sum(
            metrics["per_dimension"][dimension]["correct"]
            for dimension in HARD_DIMENSIONS
        ),
    )


def _json_selection_key(key: tuple[Any, ...]) -> list[Any]:
    result = []
    for value in key:
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            result.append({"fraction": [int(value.numerator), int(value.denominator)]})
        elif isinstance(value, tuple):
            result.append(list(value))
        else:
            result.append(value)
    return result


def _selection_key_from_json(value: list[Any]) -> tuple[Any, ...]:
    from fractions import Fraction

    result = []
    for item in value:
        if isinstance(item, Mapping) and set(item) == {"fraction"}:
            result.append(Fraction(*item["fraction"]))
        elif isinstance(item, list):
            result.append(tuple(item))
        else:
            result.append(item)
    return tuple(result)


def _seed_everything(torch: Any, seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def _configure_precision(torch: Any) -> None:
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.set_float32_matmul_precision("highest")


def _feature_sha256(torch: Any, value: Any) -> str:
    tensor = value.detach().contiguous().cpu()
    raw = tensor.view(torch.uint16).numpy().tobytes()
    return hashlib.sha256(raw).hexdigest()


__all__ = [
    "FORMAL_RESULT_SCHEMA",
    "Plan099TorchAdapter",
    "Plan099TrainingController",
    "evaluate_development",
]
