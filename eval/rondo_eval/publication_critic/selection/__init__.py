"""Plan 073 / M3-C2 joint evaluation, threshold selection and blind confirmation.

The Plan 054 corpus, the Plan 068 qualification cohort and the Plan 071
comparability cohort all describe *deployment* identity over 24 fixed samples.
M3-C2 instead compares three already-qualified artifacts over the frozen v8
evaluation splits, so it owns its own release, metric, threshold, judge and
lock vocabulary rather than widening those historical schemas.

Everything that already carries the product meaning is reused unchanged: the
Plan 054 packet-to-scalar path (``PublicationCriticInference``), the frozen
stable sigmoid projection, the Plan 055 service seam and the Plan 064 dataset
consumer.
"""

from .contract import (
    CANDIDATES,
    FREEZE_SCHEMA,
    SELECTION_METHOD,
    SelectionError,
    freeze_sha256,
    validate_freeze,
)

__all__ = [
    "CANDIDATES",
    "FREEZE_SCHEMA",
    "SELECTION_METHOD",
    "SelectionError",
    "freeze_sha256",
    "validate_freeze",
]
