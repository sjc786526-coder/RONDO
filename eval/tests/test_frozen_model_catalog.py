from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rondo_eval.frozen_model_catalog import (
    FrozenModelCatalogError,
    load_frozen_model_catalog,
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


if __name__ == "__main__":
    unittest.main()
