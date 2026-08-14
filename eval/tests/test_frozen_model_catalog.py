from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rondo_eval.frozen_model_catalog import (
    RONDO_CATALOG_PATH,
    UPSTREAM_CATALOG_PATH,
    FrozenModelCatalogError,
    load_frozen_model_catalog,
    load_shared_model_catalog,
)


class FrozenModelCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.commit = "a" * 40
        self.models_path = (
            self.root
            / "codex-source-code/codex-rs/models-manager/models.json"
        )
        self.models_path.parent.mkdir(parents=True)
        self.source = {
            "models": [
                {
                    "slug": "gpt-5.6-sol",
                    "display_name": "Sol",
                    "auto_review_model_override": None,
                },
                {
                    "slug": "gpt-5.6-luna",
                    "display_name": "Luna",
                    "auto_review_model_override": None,
                },
                {"slug": "unused", "auto_review_model_override": None},
            ]
        }
        self.models_path.write_text(json.dumps(self.source), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        command = _args[0]
        if command[-2:] == ("rev-parse", "HEAD"):
            return SimpleNamespace(returncode=0, stdout=self.commit + "\n")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(self.source).encode(),
        )

    def test_source_bound_projection_is_minimal_private_and_deterministic(self) -> None:
        projection = load_frozen_model_catalog(
            self.root,
            source_commit=self.commit,
            main_model="gpt-5.6-sol",
            guardian_model="gpt-5.6-sol",
            _run=self._run,
        )
        catalog = projection.to_dict()
        self.assertEqual([model["slug"] for model in catalog["models"]], ["gpt-5.6-sol"])
        self.assertEqual(
            catalog["models"][0]["auto_review_model_override"],
            "gpt-5.6-sol",
        )
        self.assertEqual(json.loads(self.models_path.read_text()), self.source)

        output = self.root / "output/model-catalog.json"
        output.parent.mkdir()
        projection.write_private(output)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o400)
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), projection.sha256)

    def test_source_commit_mismatch_fails_closed(self) -> None:
        def mismatched(*_args: object, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=0, stdout="b" * 40 + "\n")

        with self.assertRaisesRegex(FrozenModelCatalogError, "differs"):
            load_frozen_model_catalog(
                self.root,
                source_commit=self.commit,
                main_model="gpt-5.6-sol",
                guardian_model="gpt-5.6-sol",
                _run=mismatched,
            )

    def test_duplicate_or_missing_selected_model_fails_closed(self) -> None:
        self.source["models"].append(dict(self.source["models"][0]))
        self.models_path.write_text(json.dumps(self.source), encoding="utf-8")
        for guardian_model in ("gpt-5.6-sol", "missing"):
            with self.subTest(guardian_model=guardian_model), self.assertRaisesRegex(
                FrozenModelCatalogError, "absent"
            ):
                load_frozen_model_catalog(
                    self.root,
                    source_commit=self.commit,
                    main_model="gpt-5.6-sol",
                    guardian_model=guardian_model,
                    _run=self._run,
                )


class SharedModelCatalogTests(unittest.TestCase):
    """Both sides must load one artifact, and its provenance must be checkable."""

    upstream_commit = "a" * 40
    rondo_commit = "b" * 40
    blob_id = "f" * 40

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "codex-source-code").mkdir()
        self.source = {
            "models": [
                {"slug": f"model-{index}", "auto_review_model_override": None}
                for index in range(8)
            ]
        }
        self.source["models"][2]["slug"] = "gpt-5.6-sol"
        self.source["models"][5]["slug"] = "gpt-5.6-luna"
        self.blobs = {
            (self.upstream_commit, UPSTREAM_CATALOG_PATH): self.blob_id,
            (self.rondo_commit, RONDO_CATALOG_PATH): self.blob_id,
        }
        self.bodies = {
            self.blob_id: json.dumps(self.source).encode(),
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, *args: object, **kwargs: object):
        command = args[0]
        text = kwargs.get("text", False)
        spec = command[-1]
        if command[-2] == "rev-parse" and spec.endswith("^{commit}"):
            return SimpleNamespace(returncode=0, stdout=spec[: -len("^{commit}")] + "\n")
        commit, _, path = spec.partition(":")
        blob = self.blobs.get((commit, path))
        if blob is None:
            return SimpleNamespace(returncode=1, stdout="" if text else b"")
        if command[-2] == "rev-parse":
            return SimpleNamespace(returncode=0, stdout=blob + "\n")
        return SimpleNamespace(returncode=0, stdout=self.bodies[blob])

    def _load(self, **overrides: object):
        values: dict[str, object] = {
            "upstream_source_commit": self.upstream_commit,
            "rondo_source_commit": self.rondo_commit,
            "main_model": "gpt-5.6-sol",
            "guardian_model": "gpt-5.6-sol",
            "_run": self._run,
        }
        values.update(overrides)
        return load_shared_model_catalog(self.root, **values)  # type: ignore[arg-type]

    def test_every_frozen_model_survives_the_projection(self) -> None:
        projection = self._load()
        catalog = projection.to_dict()
        self.assertEqual(len(catalog["models"]), 8)
        self.assertEqual(
            [model["slug"] for model in catalog["models"]],
            [model["slug"] for model in self.source["models"]],
        )
        self.assertEqual(len(projection.model_slugs), 8)

    def test_only_the_target_entry_receives_the_override(self) -> None:
        projection = self._load(guardian_model="gpt-5.6-luna")
        overridden = {
            model["slug"]: model["auto_review_model_override"]
            for model in projection.to_dict()["models"]
            if model["auto_review_model_override"] is not None
        }
        self.assertEqual(overridden, {"gpt-5.6-sol": "gpt-5.6-luna"})
        self.assertEqual(projection.override_target_slug, "gpt-5.6-sol")

    def test_both_sides_receive_identical_bytes(self) -> None:
        first = self._load()
        second = self._load()
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_identity_records_both_sources_and_the_projection(self) -> None:
        projection = self._load()
        identity = projection.identity()
        self.assertEqual(
            identity["projection_algorithm"], "full_catalog_with_auto_review_override"
        )
        self.assertEqual(identity["projection_version"], 2)
        self.assertEqual(identity["override_target_slug"], "gpt-5.6-sol")
        self.assertEqual(
            {item["side"] for item in identity["sources"]}, {"upstream", "rondo"}
        )
        upstream = projection.source_for("upstream")
        rondo = projection.source_for("rondo")
        self.assertEqual(upstream.commit, self.upstream_commit)
        self.assertEqual(rondo.commit, self.rondo_commit)
        self.assertEqual(upstream.path, UPSTREAM_CATALOG_PATH)
        self.assertEqual(rondo.path, RONDO_CATALOG_PATH)
        self.assertEqual(upstream.blob_id, rondo.blob_id)
        projection.validate_identity(identity)

    def test_identity_drift_fails_closed(self) -> None:
        projection = self._load()
        drifted = json.loads(json.dumps(projection.identity()))
        drifted["sources"][0]["commit"] = "9" * 40
        with self.assertRaisesRegex(FrozenModelCatalogError, "drifted"):
            projection.validate_identity(drifted)

    def test_divergent_sources_have_no_shared_artifact(self) -> None:
        other = json.loads(json.dumps(self.source))
        other["models"].pop()
        self.blobs[(self.rondo_commit, RONDO_CATALOG_PATH)] = "e" * 40
        self.bodies["e" * 40] = json.dumps(other).encode()
        with self.assertRaisesRegex(FrozenModelCatalogError, "no shared artifact"):
            self._load()

    def test_an_unavailable_source_commit_fails_closed(self) -> None:
        for overrides in (
            {"upstream_source_commit": "c" * 40},
            {"rondo_source_commit": "d" * 40},
        ):
            with self.subTest(**overrides), self.assertRaisesRegex(
                FrozenModelCatalogError, "unavailable"
            ):
                self._load(**overrides)

    def test_a_missing_selected_model_fails_closed(self) -> None:
        with self.assertRaisesRegex(FrozenModelCatalogError, "absent"):
            self._load(guardian_model="not-in-catalog")

    def test_the_written_artifact_is_private_and_matches_its_digest(self) -> None:
        projection = self._load()
        output = self.root / "artifacts/shared-model-catalog.json"
        output.parent.mkdir()
        projection.write_private(output)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o400)
        self.assertEqual(
            hashlib.sha256(output.read_bytes()).hexdigest(), projection.sha256
        )


if __name__ == "__main__":
    unittest.main()
