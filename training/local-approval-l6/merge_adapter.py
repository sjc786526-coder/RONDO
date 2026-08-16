#!/usr/bin/env python3
"""Merge one frozen local LoRA adapter into its frozen local base model."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from typing import Sequence

_FROZEN_TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json")


class MergeAdapterError(RuntimeError):
    """Stable fail-closed merge error."""


def _require_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise MergeAdapterError("required_directory_missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise MergeAdapterError("required_directory_invalid")


def _copy_frozen_tokenizer(base: Path, output: Path) -> None:
    for name in _FROZEN_TOKENIZER_FILES:
        source = base / name
        try:
            body = source.read_bytes()
        except OSError as exc:
            raise MergeAdapterError("frozen_tokenizer_file_missing") from exc
        if not body:
            raise MergeAdapterError("frozen_tokenizer_file_empty")
        target = output / name
        try:
            with target.open("xb") as stream:
                stream.write(body)
        except OSError as exc:
            raise MergeAdapterError("frozen_tokenizer_copy_failed") from exc


def merge_adapter(base: Path, adapter: Path, output: Path) -> None:
    _require_directory(base)
    _require_directory(adapter)
    if output.exists() or output.is_symlink():
        raise MergeAdapterError("merge_output_exists")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForImageTextToText

    model = AutoModelForImageTextToText.from_pretrained(
        base,
        local_files_only=True,
        low_cpu_mem_usage=True,
        device_map="cpu",
        torch_dtype=torch.bfloat16,
    )
    merged = PeftModel.from_pretrained(
        model, adapter, local_files_only=True
    ).merge_and_unload()
    merged.save_pretrained(
        output, safe_serialization=True, max_shard_size="5GB"
    )
    # Re-serializing this tokenizer with Transformers 5 writes
    # `tokenizer_class=TokenizersBackend`, which b10333's converter cannot
    # import. Preserve the already-verified frozen tokenizer bytes instead.
    _copy_frozen_tokenizer(base, output)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="merge_adapter.py")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        merge_adapter(args.base, args.adapter, args.output)
        return 0
    except (MergeAdapterError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
