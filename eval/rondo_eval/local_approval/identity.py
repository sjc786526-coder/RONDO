"""Lightweight launcher-instance receipt for model-backed local approval."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from ..config import ConfigError, RuntimeConfig


_RECEIPT_RELATIVE_PATH = Path("eval-data/local-approval/launcher-identity.json")
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class LauncherIdentity:
    schema_version: int
    nonce: str
    pid: int
    process_start_ticks: int
    command_sha256: str
    runtime_sha256: str
    model_sha256: str
    model_path: str
    model_id: str
    base_url: str
    host: str
    port: int
    created_ns: int


def publish_launcher_identity(
    config: RuntimeConfig,
    *,
    pid: int,
    command: Sequence[str],
    runtime_sha256: str,
    model_sha256: str,
    model_path: Path,
    model_id: str,
    base_url: str,
    host: str,
    port: int,
) -> LauncherIdentity:
    """Publish one private receipt after the pinned launcher process starts."""

    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        raise ConfigError("local approval launcher PID is invalid")
    identity = LauncherIdentity(
        schema_version=1,
        nonce=secrets.token_hex(32),
        pid=pid,
        process_start_ticks=_process_start_ticks(pid),
        command_sha256=_command_sha256(command),
        runtime_sha256=runtime_sha256,
        model_sha256=model_sha256,
        model_path=os.fspath(model_path.resolve(strict=True)),
        model_id=model_id,
        base_url=base_url,
        host=host,
        port=port,
        created_ns=time.time_ns(),
    )
    _validate_identity(identity)
    _verify_process(identity, require_listener=False)
    path = _receipt_path(config)
    _prepare_receipt_parent(path.parent)
    if path.exists() or path.is_symlink():
        try:
            existing = _read_identity(path)
            _verify_process(existing, require_listener=False)
        except (ConfigError, OSError):
            path.unlink(missing_ok=True)
        else:
            raise ConfigError("a live local approval launcher identity already exists")
    raw = json.dumps(asdict(identity), separators=(",", ":"), sort_keys=True).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{identity.nonce}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("local approval launcher identity write did not progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    _fsync_directory(path.parent)
    return identity


def clear_launcher_identity(config: RuntimeConfig, identity: LauncherIdentity) -> None:
    """Remove only the receipt for the launcher instance being stopped."""

    path = _receipt_path(config)
    try:
        current = _read_identity(path)
    except (ConfigError, OSError):
        return
    if current.nonce != identity.nonce:
        return
    path.unlink(missing_ok=True)
    _fsync_directory(path.parent)


def require_launcher_identity(
    config: RuntimeConfig,
    *,
    runtime_sha256: str,
    model_sha256: str,
    model_path: Path,
    model_id: str,
    base_url: str,
    host: str,
    port: int,
) -> LauncherIdentity:
    """Load and validate the exact live process that owns the configured port."""

    identity = _read_identity(_receipt_path(config))
    expected = (
        runtime_sha256,
        model_sha256,
        os.fspath(model_path.resolve(strict=True)),
        model_id,
        base_url,
        host,
        port,
    )
    actual = (
        identity.runtime_sha256,
        identity.model_sha256,
        identity.model_path,
        identity.model_id,
        identity.base_url,
        identity.host,
        identity.port,
    )
    if actual != expected:
        raise ConfigError("local approval launcher identity differs from configuration")
    _verify_process(identity, require_listener=True)
    return identity


def revalidate_launcher_identity(
    config: RuntimeConfig, expected: LauncherIdentity
) -> None:
    current = _read_identity(_receipt_path(config))
    if current != expected:
        raise ConfigError("local approval launcher identity changed during request")
    _verify_process(current, require_listener=True)


def _receipt_path(config: RuntimeConfig) -> Path:
    try:
        root = config.paths.common_root.resolve(strict=True)
    except OSError as exc:
        raise ConfigError("RONDO common root is unavailable") from exc
    candidate = root / _RECEIPT_RELATIVE_PATH
    current = root
    for component in _RECEIPT_RELATIVE_PATH.parent.parts:
        current /= component
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ConfigError("local approval identity path is unavailable") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ConfigError("local approval identity path has an unsafe ancestor")
    try:
        candidate.parent.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as exc:
        raise ConfigError("local approval identity path escapes the RONDO root") from exc
    return candidate


def _prepare_receipt_parent(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ConfigError("local approval identity directory is invalid")
    mode = os.lstat(path).st_mode
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ConfigError("local approval identity directory is writable by other users")


def _read_identity(path: Path) -> LauncherIdentity:
    if path.is_symlink() or not path.is_file():
        raise ConfigError("local approval launcher identity is unavailable")
    mode = stat.S_IMODE(os.lstat(path).st_mode)
    if mode != 0o600:
        raise ConfigError("local approval launcher identity must have mode 0600")
    try:
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict) or set(value) != set(LauncherIdentity.__dataclass_fields__):
            raise ValueError
        identity = LauncherIdentity(**value)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConfigError("local approval launcher identity is invalid") from exc
    _validate_identity(identity)
    return identity


def _validate_identity(identity: LauncherIdentity) -> None:
    if (
        identity.schema_version != 1
        or not _HEX_64.fullmatch(identity.nonce)
        or not isinstance(identity.pid, int)
        or isinstance(identity.pid, bool)
        or identity.pid <= 1
        or not isinstance(identity.process_start_ticks, int)
        or identity.process_start_ticks <= 0
        or not _HEX_64.fullmatch(identity.command_sha256)
        or not _HEX_64.fullmatch(identity.runtime_sha256)
        or not _HEX_64.fullmatch(identity.model_sha256)
        or not Path(identity.model_path).is_absolute()
        or not identity.model_id
        or not identity.base_url
        or identity.host != "127.0.0.1"
        or not 1 <= identity.port <= 65535
        or not isinstance(identity.created_ns, int)
        or identity.created_ns <= 0
    ):
        raise ConfigError("local approval launcher identity fields are invalid")


def _verify_process(identity: LauncherIdentity, *, require_listener: bool) -> None:
    if _process_start_ticks(identity.pid) != identity.process_start_ticks:
        raise ConfigError("local approval launcher process identity differs")
    command = Path(f"/proc/{identity.pid}/cmdline").read_bytes()
    if hashlib.sha256(command).hexdigest() != identity.command_sha256:
        raise ConfigError("local approval launcher command identity differs")
    if require_listener and not _process_owns_listener(identity.pid, identity.host, identity.port):
        raise ConfigError("local approval launcher does not own the configured endpoint")


def _process_start_ticks(pid: int) -> int:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        tail = raw[raw.rindex(")") + 2 :].split()
        return int(tail[19])
    except (OSError, UnicodeError, ValueError, IndexError) as exc:
        raise ConfigError("local approval launcher process is unavailable") from exc


def _command_sha256(command: Sequence[str]) -> str:
    raw = b"\0".join(os.fsencode(item) for item in command) + b"\0"
    return hashlib.sha256(raw).hexdigest()


def _process_owns_listener(pid: int, host: str, port: int) -> bool:
    socket_inodes: set[str] = set()
    try:
        descriptors = list(Path(f"/proc/{pid}/fd").iterdir())
    except OSError:
        return False
    for descriptor in descriptors:
        try:
            target = os.readlink(descriptor)
        except OSError:
            continue
        match = re.fullmatch(r"socket:\[(\d+)\]", target)
        if match is not None:
            socket_inodes.add(match.group(1))
    expected_address = "0100007F" if host == "127.0.0.1" else ""
    expected_port = f"{port:04X}"
    try:
        lines = Path(f"/proc/{pid}/net/tcp").read_text(encoding="ascii").splitlines()[1:]
    except (OSError, UnicodeError):
        return False
    for line in lines:
        columns = line.split()
        if (
            len(columns) > 9
            and columns[1] == f"{expected_address}:{expected_port}"
            and columns[3] == "0A"
            and columns[9] in socket_inodes
        ):
            return True
    return False


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
