"""Small deterministic identity helpers for the Plan 054 model and runs."""

import hashlib
import json
from pathlib import Path
from typing import Any


class IdentityError(ValueError):
    """Raised when a frozen identity is absent or has drifted."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IdentityError(f"cannot load frozen JSON: {path}") from exc


def require_file_sha256(path: Path, expected: str) -> None:
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise IdentityError("expected SHA-256 is invalid")
    if not path.is_file() or path.is_symlink():
        raise IdentityError(f"frozen file is missing or unsafe: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise IdentityError(f"frozen file identity drifted: {path}")


def component_identity(name: str, revision: str) -> dict[str, str]:
    for value in (name, revision):
        encoded = value.encode("ascii", errors="strict")
        if not encoded or len(encoded) > 128 or any(byte <= 32 or byte >= 127 for byte in encoded):
            raise IdentityError("identity component does not satisfy the Plan 055 contract")
    return {"name": name, "revision": revision}
