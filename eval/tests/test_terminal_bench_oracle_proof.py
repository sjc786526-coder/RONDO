from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from rondo_eval.terminal_bench.oracle_proof import (
    OracleProofContract,
    OracleProofStore,
)
from rondo_eval.terminal_bench.tasksets import FrozenCanaryCatalog, FrozenTask


class OracleProofTests(unittest.TestCase):
    def _task(self, name: str) -> FrozenTask:
        return FrozenTask(
            task_id=f"terminal-bench/{name}",
            source_digest="a" * 64,
            image_tag=f"example/{name}:20260812",
            image_ref=f"example/{name}@sha256:{'b' * 64}",
            workdir="/app",
            memory_mb=2048,
            timeout_seconds=1800,
            agent_timeout_seconds=900,
            verifier_timeout_seconds=900,
            build_timeout_seconds=600,
        )

    def _contract(self, task: FrozenTask) -> OracleProofContract:
        return OracleProofContract(
            task=dict(task.__dict__),
            taskset_entry_sha256="c" * 64,
            catalog_entry_sha256="d" * 64,
            verifier_tree_sha256="e" * 64,
            shared_components={"runner": "f" * 64},
            terminal_bench_commit="1" * 40,
            harbor_version="0.20.0",
            seccomp_source_sha256="2" * 64,
            seccomp_effective_sha256="3" * 64,
        )

    @staticmethod
    def _docker(task: FrozenTask) -> dict[str, object]:
        return {
            "schema_version": 1,
            "returncode": 0,
            "image": {"id": f"sha256:{'b' * 64}", "reference": task.image_ref},
            "container": {
                "cap_add": [],
                "cap_drop": ["ALL"],
                "cgroupns": "private",
                "memory": task.memory_mb * 1024**2,
                "memory_swap": (task.memory_mb + 1024) * 1024**2,
                "mounts": [],
                "network_mode": "bridge",
                "networks": ["default"],
                "pids": task.pids_limit,
                "privileged": False,
                "read_only_rootfs": False,
                "security_opt": ["no-new-privileges:true", "seccomp=custom"],
                "user": "1000:1000",
            },
            "seccomp": {"kind": "custom", "sha256": "3" * 64},
            "cleanup": "verified_empty",
            "operation": "host",
        }

    def test_task_proofs_persist_incrementally_and_manifest_requires_all(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = OracleProofStore(Path(temporary).resolve())
            tasks = (self._task("one"), self._task("two"))
            contracts = tuple(self._contract(task) for task in tasks)
            catalog = FrozenCanaryCatalog("1" * 40, "4" * 64, tasks, "5" * 64)

            first = store.publish(
                contracts[0],
                outcome="completed",
                task_outcome="pass",
                reward=1.0,
                docker_receipt=self._docker(tasks[0]),
            )
            self.assertTrue(first.is_file())
            self.assertIsNone(
                store.publish_manifest(catalog=catalog, contracts=contracts)
            )
            self.assertIsNotNone(store.valid_proof(contracts[0]))
            store.publish(
                contracts[1],
                outcome="completed",
                task_outcome="pass",
                reward=1.0,
                docker_receipt=self._docker(tasks[1]),
            )
            manifest = store.publish_manifest(catalog=catalog, contracts=contracts)
            self.assertIsNotNone(manifest)
            self.assertTrue(manifest.is_file())
            manifest.write_text("{}\n", encoding="utf-8")
            self.assertIsNone(
                store.validate_manifest(catalog=catalog, contracts=contracts)
            )
            self.assertEqual(manifest.read_text(encoding="utf-8"), "{}\n")

    def test_task_and_shared_component_drift_have_exact_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = OracleProofStore(Path(temporary).resolve())
            one = self._contract(self._task("one"))
            two = self._contract(self._task("two"))
            store.publish(
                one,
                outcome="completed",
                task_outcome="pass",
                reward=1.0,
                docker_receipt=self._docker(self._task("one")),
            )
            store.publish(
                two,
                outcome="completed",
                task_outcome="pass",
                reward=1.0,
                docker_receipt=self._docker(self._task("two")),
            )

            changed_task = replace(
                one,
                task={**one.task, "source_digest": "9" * 64},
            )
            self.assertIsNone(store.valid_proof(changed_task))
            self.assertIsNotNone(store.valid_proof(two))

            changed_shared = replace(
                two,
                shared_components={"runner": "8" * 64},
            )
            self.assertIsNone(store.valid_proof(changed_shared))
            self.assertIsNotNone(store.valid_proof(one))

            changed_image = replace(
                one,
                task={
                    **one.task,
                    "image_ref": f"example/one@sha256:{'9' * 64}",
                },
            )
            self.assertIsNone(store.valid_proof(changed_image))

    def test_proof_rejects_crosswired_image_and_nonpassing_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = OracleProofStore(Path(temporary).resolve())
            task = self._task("one")
            contract = self._contract(task)
            wrong = self._docker(self._task("two"))
            with self.assertRaisesRegex(ValueError, "compatibility"):
                store.publish(
                    contract,
                    outcome="completed",
                    task_outcome="pass",
                    reward=1.0,
                    docker_receipt=wrong,
                )
            with self.assertRaisesRegex(ValueError, "proof gate"):
                store.publish(
                    contract,
                    outcome="agent_failed",
                    task_outcome="fail",
                    reward=0.0,
                    docker_receipt=self._docker(task),
                )

    def test_campaign_identity_is_not_part_of_the_proof_contract(self) -> None:
        contract_fields = set(OracleProofContract.__dataclass_fields__)
        self.assertNotIn("campaign_id", contract_fields)
        self.assertNotIn("campaign_lock_sha256", contract_fields)
        self.assertNotIn("git_commit", contract_fields)
        self.assertNotIn("provider_profile_sha256", contract_fields)
        self.assertNotIn("wire_canary_sha256", contract_fields)


if __name__ == "__main__":
    unittest.main()
