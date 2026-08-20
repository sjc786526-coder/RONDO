"""Boolean-only local readiness checks for Plan 049 Phase B."""

from __future__ import annotations

import stat

from ..config import ConfigError, RepoPaths, load_provider_secret, load_runtime_config


def secret_readiness(paths: RepoPaths, *, provider_name: str) -> dict[str, bool]:
    """Inspect no secret content unless the file boundary is already safe.

    The strict project loader parses KEY=VALUE data and returns the requested
    value in-process. This function immediately reduces that result to one
    boolean and never returns a name, value, error detail, or file content.
    """

    path = paths.common_root / ".env.local"
    try:
        metadata = path.lstat()
    except OSError:
        return {
            "exists": False,
            "regular_file": False,
            "non_symlink": False,
            "mode_0600": False,
            "phase_b_required_values_nonempty": False,
        }
    regular = stat.S_ISREG(metadata.st_mode)
    non_symlink = not stat.S_ISLNK(metadata.st_mode)
    mode_ok = stat.S_IMODE(metadata.st_mode) == 0o600
    values_ok = False
    if regular and non_symlink and mode_ok:
        try:
            config = load_runtime_config(paths)
            _discarded_name, secret = load_provider_secret(config, provider_name)
            values_ok = bool(secret)
        except ConfigError:
            values_ok = False
    return {
        "exists": True,
        "regular_file": regular,
        "non_symlink": non_symlink,
        "mode_0600": mode_ok,
        "phase_b_required_values_nonempty": values_ok,
    }
