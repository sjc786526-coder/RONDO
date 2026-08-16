#!/usr/bin/env python3
"""Merge one frozen local LoRA adapter into its frozen local base model."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from typing import Sequence


class MergeAdapterError(RuntimeError):
    """Stable fail-closed merge error."""


def _require_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise MergeAdapterError("required_directory_missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise MergeAdapterError("required_directory_invalid")


def merge_adapter(base: Path, adapter: Path, output: Path) -> None:
    _require_directory(base)
    _require_directory(adapter)
    if output.exists() or output.is_symlink():
        raise MergeAdapterError("merge_output_exists")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForImageTextToText, AutoTokenizer

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
    AutoTokenizer.from_pretrained(base, local_files_only=True).save_pretrained(
        output
    )


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
