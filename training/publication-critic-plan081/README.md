# Plan 081 local training readiness contracts

This directory binds the next Publication Critic research route to the exact
`Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`
base, the frozen v8 train/validation projection, direct non-PEFT parameter
updates, and the continuous observation/checkpoint lifecycle implemented by
Plan 081.

`route-contract-v1.json` intentionally does not choose concrete trainable
layers, learning rate, batch size, update count, optimizer, scheduler, or scope
expansion rule. Those are runtime records and inputs to a later authorized
commissioning task. `cloud-handoff-v1.json` limits that later task to one A40
48GB (preferred) or L40S 48GB, at most 12 hours and 15 USD total external cost.

The local Plan 081 tests use only fixture/fake adapters. They prove controller,
same-cohort validation, retention, archive, and recovery behavior; they do not
load or train a model, prove GPU feasibility or quality, create a research
candidate, authorize cloud work, unlock M3-D, or establish product GO. Current
stage and subsequent work are defined only by `doc/WBS.md` and
`doc/WBS/multi-agent-trusted-evidence.md`.
