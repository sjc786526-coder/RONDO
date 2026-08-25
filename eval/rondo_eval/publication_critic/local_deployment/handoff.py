"""Bounded, write-once S3 handoff for Plan 068 model artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any


VOLUME_ID = "hi3iaz8rsr"
HANDOFF_ROOT = "rondo-plan060-publication-critic-20260824t040742z/"
SOURCE_BUNDLE_PREFIX = "bundle-plan066-final-01/"
FORMAL_FREEZE_PREFIX = "formal-freeze-plan066-final01/"
FORMAL_RUN_PREFIX = "runs/plan066-formal-final01-01/"
WINNER_LOCK_KEY = "controller/winner-lock.json"
ALLOWED_PREFIXES = (
    SOURCE_BUNDLE_PREFIX,
    "controller/",
    FORMAL_FREEZE_PREFIX,
    "model/",
    "runs/",
    "wheels/",
)
ALLOWED_ROOT_OBJECTS = frozenset(
    {
        "dependency-freeze-observed.txt",
        "dependency-identity-observed.json",
    }
)
MAX_LIST_ENTRIES = 512
MAX_LIST_PAGES = 8
DEFAULT_CHUNK_BYTES = 1024 * 1024


class HandoffError(RuntimeError):
    """Stable Plan 068 failure that never includes provider or secret text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RemoteObject:
    relative_key: str
    size: int
    etag: str | None = None


@dataclass(frozen=True)
class BoundedListing:
    relative_prefix: str
    objects: tuple[RemoteObject, ...]
    common_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class DownloadSpec:
    relative_key: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _safe_object_key(self.relative_key)
        _nonnegative_int(self.size, "download_size_invalid")
        _require_sha256(self.sha256)


class HandoffClient:
    """Small injected-client facade for the exact Plan 068 winner volume."""

    def __init__(
        self,
        s3_client: Any,
        *,
        bucket: str = VOLUME_ID,
        root: str = HANDOFF_ROOT,
        additional_object_keys: Iterable[str] = (),
    ) -> None:
        if bucket != VOLUME_ID:
            raise HandoffError("handoff_bucket_not_allowed")
        if root != HANDOFF_ROOT:
            raise HandoffError("handoff_root_not_allowed")
        additions: set[str] = set()
        for value in additional_object_keys:
            additions.add(_safe_object_key(value))
        self._client = s3_client
        self.bucket = bucket
        self.root = root
        self._allowed_objects = ALLOWED_ROOT_OBJECTS | frozenset(additions)

    def list_level(
        self,
        relative_prefix: str = "",
        *,
        max_entries: int = MAX_LIST_ENTRIES,
        max_pages: int = MAX_LIST_PAGES,
    ) -> BoundedListing:
        """List one delimiter-bounded level below an allowed prefix."""

        prefix = _safe_list_prefix(relative_prefix)
        if prefix and not _under_allowed_prefix(prefix):
            raise HandoffError("handoff_prefix_not_allowed")
        if (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or not 1 <= max_entries <= MAX_LIST_ENTRIES
            or isinstance(max_pages, bool)
            or not isinstance(max_pages, int)
            or not 1 <= max_pages <= MAX_LIST_PAGES
        ):
            raise HandoffError("handoff_list_bound_invalid")

        absolute_prefix = self.root + prefix
        continuation: str | None = None
        objects: list[RemoteObject] = []
        common_prefixes: list[str] = []
        seen_tokens: set[str] = set()
        for _page in range(max_pages):
            remaining = max_entries - len(objects) - len(common_prefixes)
            if remaining <= 0:
                raise HandoffError("handoff_list_limit_exceeded")
            request: dict[str, Any] = {
                "Bucket": self.bucket,
                "Prefix": absolute_prefix,
                "Delimiter": "/",
                "MaxKeys": remaining,
            }
            if continuation is not None:
                request["ContinuationToken"] = continuation
            try:
                response = self._client.list_objects_v2(**request)
            except Exception:
                raise HandoffError("handoff_list_failed") from None
            if not isinstance(response, Mapping):
                raise HandoffError("handoff_list_response_invalid")
            page_objects = response.get("Contents", [])
            page_prefixes = response.get("CommonPrefixes", [])
            if not isinstance(page_objects, list) or not isinstance(page_prefixes, list):
                raise HandoffError("handoff_list_response_invalid")
            for item in page_objects:
                if not isinstance(item, Mapping):
                    raise HandoffError("handoff_list_response_invalid")
                key = _strip_remote_root(item.get("Key"), absolute_prefix, self.root)
                size = _nonnegative_int(item.get("Size"), "handoff_list_response_invalid")
                etag = item.get("ETag")
                if etag is not None and not isinstance(etag, str):
                    raise HandoffError("handoff_list_response_invalid")
                objects.append(RemoteObject(key, size, etag))
            for item in page_prefixes:
                if not isinstance(item, Mapping):
                    raise HandoffError("handoff_list_response_invalid")
                value = _strip_remote_prefix(
                    item.get("Prefix"), absolute_prefix, self.root
                )
                common_prefixes.append(value)
            if len(objects) + len(common_prefixes) > max_entries:
                raise HandoffError("handoff_list_limit_exceeded")
            truncated = response.get("IsTruncated")
            if not isinstance(truncated, bool):
                raise HandoffError("handoff_list_response_invalid")
            if not truncated:
                return BoundedListing(
                    prefix,
                    tuple(objects),
                    tuple(common_prefixes),
                )
            token = response.get("NextContinuationToken")
            if not isinstance(token, str) or not token or token in seen_tokens:
                raise HandoffError("handoff_list_response_invalid")
            seen_tokens.add(token)
            continuation = token
        raise HandoffError("handoff_list_page_limit_exceeded")

    def head(self, relative_key: str) -> RemoteObject:
        key = self._allowed_key(relative_key)
        try:
            response = self._client.head_object(
                Bucket=self.bucket,
                Key=self.root + key,
            )
        except Exception:
            raise HandoffError("handoff_head_failed") from None
        if not isinstance(response, Mapping):
            raise HandoffError("handoff_head_response_invalid")
        size = _nonnegative_int(
            response.get("ContentLength"), "handoff_head_response_invalid"
        )
        etag = response.get("ETag")
        if etag is not None and not isinstance(etag, str):
            raise HandoffError("handoff_head_response_invalid")
        return RemoteObject(key, size, etag)

    def known_spec(self, relative_key: str, sha256: str) -> DownloadSpec:
        """Resolve an exact known hash against the object's provider size."""

        _require_sha256(sha256)
        remote = self.head(relative_key)
        return DownloadSpec(remote.relative_key, remote.size, sha256)

    def download(
        self,
        spec: DownloadSpec,
        destination_root: Path,
        *,
        chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    ) -> Path:
        """Resume into ``.part`` and atomically publish without overwrite."""

        key = self._allowed_key(spec.relative_key)
        if (
            isinstance(chunk_bytes, bool)
            or not isinstance(chunk_bytes, int)
            or not 1 <= chunk_bytes <= 16 * 1024 * 1024
        ):
            raise HandoffError("download_chunk_size_invalid")
        root = _ensure_private_root(Path(destination_root))
        destination = _private_destination(root, key)
        partial = destination.with_name(destination.name + ".part")
        if _path_present(destination):
            raise HandoffError("download_destination_exists")
        offset = _partial_size(partial)
        if offset > spec.size:
            raise HandoffError("download_partial_too_large")

        remote = self.head(key)
        if remote.size != spec.size:
            raise HandoffError("download_remote_size_mismatch")
        if spec.size == 0 and not _path_present(partial):
            descriptor = _open_partial(partial, offset=0)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if offset < spec.size:
            self._append_range(
                key,
                partial,
                offset=offset,
                total_size=spec.size,
                chunk_bytes=chunk_bytes,
            )
        if _partial_size(partial) != spec.size:
            raise HandoffError("download_incomplete")
        _ensure_partial_mode(partial)
        if _sha256_regular(partial) != spec.sha256:
            _discard_private_partial(partial)
            raise HandoffError("download_hash_mismatch")
        try:
            os.link(partial, destination, follow_symlinks=False)
        except FileExistsError:
            raise HandoffError("download_destination_exists") from None
        except OSError:
            raise HandoffError("download_publish_failed") from None
        try:
            partial.unlink()
            _fsync_directory(destination.parent)
        except OSError:
            raise HandoffError("download_publish_cleanup_failed") from None
        return destination

    def _append_range(
        self,
        relative_key: str,
        partial: Path,
        *,
        offset: int,
        total_size: int,
        chunk_bytes: int,
    ) -> None:
        request: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": self.root + relative_key,
        }
        if offset:
            request["Range"] = f"bytes={offset}-"
        try:
            response = self._client.get_object(**request)
        except Exception:
            raise HandoffError("download_get_failed") from None
        if not isinstance(response, Mapping) or "Body" not in response:
            raise HandoffError("download_get_response_invalid")
        if offset:
            expected = f"bytes {offset}-{total_size - 1}/{total_size}"
            if response.get("ContentRange") != expected:
                _close_body(response["Body"])
                raise HandoffError("download_range_response_invalid")
        body = response["Body"]
        descriptor = _open_partial(partial, offset=offset)
        remaining = total_size - offset
        try:
            while remaining:
                chunk = _read_body(body, min(chunk_bytes, remaining))
                if not isinstance(chunk, bytes):
                    raise HandoffError("download_body_invalid")
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise HandoffError("download_write_failed")
                    view = view[written:]
                remaining -= len(chunk)
            if remaining == 0:
                extra = _read_body(body, 1)
                if not isinstance(extra, bytes) or extra:
                    raise HandoffError("download_body_size_mismatch")
            os.fsync(descriptor)
        except HandoffError:
            raise
        except Exception:
            raise HandoffError("download_stream_failed") from None
        finally:
            os.close(descriptor)
            _close_body(body)

    def _allowed_key(self, relative_key: str) -> str:
        key = _safe_object_key(relative_key)
        if not _under_allowed_prefix(key) and key not in self._allowed_objects:
            raise HandoffError("handoff_object_not_allowed")
        return key


def _safe_list_prefix(value: str) -> str:
    if value == "":
        return value
    if not isinstance(value, str) or not value.endswith("/"):
        raise HandoffError("handoff_prefix_invalid")
    _safe_parts(value[:-1])
    return value


def _safe_object_key(value: str) -> str:
    if not isinstance(value, str) or not value or value.endswith("/"):
        raise HandoffError("handoff_object_key_invalid")
    _safe_parts(value)
    return value


def _safe_parts(value: str) -> tuple[str, ...]:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "//" in value
        or any(ord(character) < 0x20 for character in value)
    ):
        raise HandoffError("handoff_relative_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HandoffError("handoff_relative_path_invalid")
    return path.parts


def _under_allowed_prefix(value: str) -> bool:
    return any(value.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _strip_remote_root(value: Any, absolute_prefix: str, root: str) -> str:
    if not isinstance(value, str) or not value.startswith(absolute_prefix):
        raise HandoffError("handoff_list_response_invalid")
    relative = value.removeprefix(root)
    return _safe_object_key(relative)


def _strip_remote_prefix(value: Any, absolute_prefix: str, root: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(absolute_prefix)
        or not value.endswith("/")
    ):
        raise HandoffError("handoff_list_response_invalid")
    relative = value.removeprefix(root)
    return _safe_list_prefix(relative)


def _require_sha256(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise HandoffError("sha256_invalid")
    return value


def _nonnegative_int(value: Any, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HandoffError(code)
    return value


def _ensure_private_root(path: Path) -> Path:
    absolute = path if path.is_absolute() else Path.cwd() / path
    if absolute.parent == absolute:
        raise HandoffError("download_root_invalid")
    missing: list[Path] = []
    current = absolute
    while not _path_present(current):
        if current.parent == current:
            raise HandoffError("download_root_invalid")
        missing.append(current)
        current = current.parent
    try:
        info = os.lstat(current)
    except OSError:
        raise HandoffError("download_root_invalid") from None
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise HandoffError("download_root_unsafe")
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o700)
        except OSError:
            raise HandoffError("download_root_create_failed") from None
    _reject_symlink_chain(absolute)
    try:
        os.chmod(absolute, 0o700)
    except OSError:
        raise HandoffError("download_root_mode_failed") from None
    return absolute


def _private_destination(root: Path, relative_key: str) -> Path:
    parts = _safe_parts(relative_key)
    parent = root
    for part in parts[:-1]:
        candidate = parent / part
        if _path_present(candidate):
            try:
                info = os.lstat(candidate)
            except OSError:
                raise HandoffError("download_directory_unsafe") from None
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise HandoffError("download_directory_unsafe")
        else:
            try:
                os.mkdir(candidate, 0o700)
            except OSError:
                raise HandoffError("download_directory_create_failed") from None
        try:
            os.chmod(candidate, 0o700)
        except OSError:
            raise HandoffError("download_directory_mode_failed") from None
        parent = candidate
    return parent / parts[-1]


def _reject_symlink_chain(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except OSError:
            raise HandoffError("download_root_invalid") from None
        if stat.S_ISLNK(info.st_mode):
            raise HandoffError("download_root_unsafe")


def _partial_size(path: Path) -> int:
    if not _path_present(path):
        return 0
    try:
        info = os.lstat(path)
    except OSError:
        raise HandoffError("download_partial_invalid") from None
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise HandoffError("download_partial_invalid")
    return info.st_size


def _open_partial(path: Path, *, offset: int) -> int:
    flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if offset:
        flags |= os.O_APPEND
    elif _path_present(path):
        # A request can fail before yielding its first byte.  Its empty private
        # partial remains a valid resume point and must not wedge the retry.
        pass
    else:
        flags |= os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        raise HandoffError("download_partial_open_failed") from None
    try:
        info = os.fstat(descriptor)
    except OSError:
        os.close(descriptor)
        raise HandoffError("download_partial_open_failed") from None
    if not stat.S_ISREG(info.st_mode) or info.st_size != offset:
        os.close(descriptor)
        raise HandoffError("download_partial_changed")
    try:
        os.fchmod(descriptor, 0o600)
    except OSError:
        os.close(descriptor)
        raise HandoffError("download_partial_mode_failed") from None
    return descriptor


def _ensure_partial_mode(path: Path) -> None:
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise HandoffError("download_partial_invalid")
        os.chmod(path, 0o600, follow_symlinks=False)
    except HandoffError:
        raise
    except OSError:
        raise HandoffError("download_partial_mode_failed") from None


def _sha256_regular(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise HandoffError("download_partial_invalid") from None
    try:
        info = os.fstat(descriptor)
    except OSError:
        os.close(descriptor)
        raise HandoffError("download_partial_invalid") from None
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        raise HandoffError("download_partial_invalid")
    digest = hashlib.sha256()
    try:
        while chunk := os.read(descriptor, DEFAULT_CHUNK_BYTES):
            digest.update(chunk)
    except OSError:
        raise HandoffError("download_hash_failed") from None
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _discard_private_partial(path: Path) -> None:
    try:
        info = os.lstat(path)
        if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            path.unlink()
    except OSError:
        raise HandoffError("download_partial_cleanup_failed") from None


def _close_body(body: Any) -> None:
    close = getattr(body, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _read_body(body: Any, size: int) -> Any:
    try:
        return body.read(size)
    except Exception:
        raise HandoffError("download_stream_failed") from None


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _path_present(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        raise HandoffError("download_path_inspection_failed") from None
    return True
