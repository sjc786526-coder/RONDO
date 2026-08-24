# Plan 066 formal full-model training

This directory freezes the bounded M3-B1c recipe and Pod entrypoints. The
runtime reuses the Plan 060 exact model, environment, winner lock, FlashAdamW
implementation and checkpoint machinery. The upload body contains v8 train and
validation rows only; unseen-test bodies remain sealed.

The authoritative execution contract is
`plan/066-multi-publication-critic-formal-full-model-training-execplan.md`.
