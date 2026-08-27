# Publication Critic Plan 090

Plan 090 confirms the retained Plan 087 Route O signal without continuing the
search.  Every formal run starts from the exact Skywork 1.7B base, updates the
same nine Layer 27 tensors once on the frozen v8 train cohort, and scores train
and validation before and after through the existing evaluator.

`confirmation-freeze-v1.json` is generated from and exactly validated by
`plan090_contract.frozen_contract()`.  It fixes the two BF16 seeds, conditional
FP32 control, complete rubric, runtime, resource, budget, namespace and claim
boundaries before any result exists.  FP32 is an entire-model FP32 training
condition control because that is the smallest reliable path supported by the
existing adapter; it is not presented as update-only causal evidence.

The existing Plan 087 small-handoff envelope and terminal helper are reused.
Their legacy schema/file names identify the already reviewed mechanism, not a
Plan 087 research result.  Plan 090 does not add a Pod creator or receipt
system: the repository-wide stock script creates, the executor independently
checks the live Pod, and the retained terminal helper releases a mismatch.

`runbook.md` is the only operational entry.  Its paid sections remain closed
until the reviewer explicitly approves Stage B.
