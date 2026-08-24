"""Publication Critic BF16 full-model training qualification runtime.

The package deliberately has no heavyweight imports at module import time.
Torch, Transformers, and FlashOptim are loaded only by an authorized training
command in :mod:`runner`.
"""

from .bundle import (
    create_deterministic_archive,
    extract_verified_archive,
    prepare_bundle,
    verify_bundle,
)
from .checkpoint import read_checkpoint_metadata, verify_checkpoint
from .contract import FullModelTrainingError
from .data import PortableTrainingDataset, load_portable_dataset

__all__ = [
    "FullModelTrainingError",
    "PortableTrainingDataset",
    "create_deterministic_archive",
    "extract_verified_archive",
    "load_portable_dataset",
    "prepare_bundle",
    "read_checkpoint_metadata",
    "verify_bundle",
    "verify_checkpoint",
]
