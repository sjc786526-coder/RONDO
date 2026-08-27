# Plan 079 RunPod runbook

This runbook owns only the authorized 4B base-quality campaign. It never opens
unseen-test, invokes a Judge, trains, quantizes, converts, or deletes the network
volume.

1. Finish pure/fake/focused tests locally. Do not create a billable resource
   while local code, release preparation, source bundling, or recomputation is
   still being debugged.
2. Through RunPod MCP, refresh data-center hardware support first. Build the
   intersection of Secure Cloud RTX 4090 support, RTX 6000 Ada support, and
   Standard network-volume support; do not infer support from current stock.
   Then refresh allowed base-GPU stock, price, and CUDA host versions inside
   that intersection. Prefer 4090, then 3090 if supported, then A5000.
3. Create exactly one smallest practical Standard volume in the selected center,
   then create one Secure Cloud Pod with the selected allowed 24GB GPU and mount
   that volume at `/workspace`. Prefer MCP for resource state and billing; use
   `runpodctl pod create` only because the MCP create call cannot attach an
   existing network volume. Recheck the created Pod and volume through MCP.
   If stock must be polled, `scripts/create-runpod-when-ready.py`
   may own only the latency-sensitive poll/create step after the controller has
   separately approved budget, price, volume, image, CUDA and all runtime
   arguments. Run at most one monitor for an exact Pod name; after an uncertain
   create, let its full reconciliation grace finish before another creator may
   use that name. The monitor never performs readiness, start, stop or delete.
4. Build the source tar from a clean committed worktree with
   `build-source-bundle.sh`. It intentionally excludes `multidev/`, mixed v8
   data, ignored assets, secrets, model weights, and unrelated project files.
   Separately tar the already verified Plan 066 bundle contents. Upload only
   those two archives plus their SHA-256 values into the task root. Verify the
   source archive before extracting it into a new, archive-specific source
   root; never reuse a source root for a different archive. Bootstrap and every
   evaluation independently compare every archived file with that executing
   source tree and reject extra, stale, linked, or drifted entries. Source
   receipts are keyed by archive hash so a repaired commissioning source can
   coexist with prior evidence; changing source still invalidates the prior
   commissioning qualification.
5. Launch `bootstrap` with one unique launch name. It verifies both uploaded
   archives, installs only the locked ordinary dependencies into the persistent
   volume, downloads the exact official two-shard revision, verifies the full
   snapshot, and records dependency/GPU facts. Interrupted downloads resume in
   the same HF cache and model directory.
6. Prepare the validation release locally and upload it. Freeze a commissioning
   run spec from the observed Pod/volume/GPU/image/CUDA identities. Launch
   `evaluate`; its namespace may resume exact prior successful candidate rows.
   Commissioning is complete only after 55 finite scores, aggregation, archive,
   recomputation, and safe result recovery all succeed.
7. Commit the completed implementation and tests, create a new clean source tar,
   upload and re-bootstrap only if its identity changed, then freeze a formal
   run spec. Formal freeze and run both consume the completed commissioning
   run spec, release, scores, runtime, and result; they require 55 scores, zero
   typed failures, `COMMISSIONING_COMPLETE`, and the same source/model/input/
   runtime/GPU-related identity. A replacement Pod ID alone may differ. Formal
   uses a new run id and an empty namespace. Any typed failure or missing row is
   `INCONCLUSIVE`; a complete quality failure is `NO_GO` and is not rerun to
   seek a better result.
8. Recover only the run spec, validation release, scores, runtime, result,
   bootstrap receipts, dependency freeze, task-root usage, and billing/resource
   facts. Independently run `recompute --expected result.json` outside the Pod.
9. Stop and delete the task Pod, then confirm compute billing is zero and no
   task Pod remains. Keep the task network volume. Record its ID, center,
   capacity, observed usage, current rate, accrued cost, remaining budget, and
   projected time to the 15 USD lifetime cap.
