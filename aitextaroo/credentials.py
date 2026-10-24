"""Where AI Text-a-roo command-line tools find the API key.

Lookup order: an explicit --api-key, then the AITEXTAROO_API_KEY
environment variable, then ~/.aitextaroo/credentials.json (written by
`aitextaroo-setup --save`). The file lets an agent's future sessions use
the key without the agent having to remember it.

The file is created with owner-only permissions (0600, directory 0700)
and holds the API key and assigned number — never the user's phone. It's
written to a new temporary file and renamed into place, so the key never
sits in a file with looser permissions and a symlink at the path isn't followed.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
from pathlib import Path

ENV_VAR = "AITEXTAROO_API_KEY"
CREDENTIALS_PATH = Path.home() / ".aitextaroo" / "credentials.json"


def load_api_key(explicit: str | None = None, path: Path | None = None) -> str:
    """Return the first API key found, or an empty string."""
    if explicit:
        return explicit
    from_env = os.environ.get(ENV_VAR, "")
    if from_env:
        return from_env
    data = load_credentials(path)
    key = data.get("api_key") if data else None
    return key if isinstance(key, str) else ""


def load_credentials(path: Path | None = None) -> dict | None:
    """Read the saved credentials file, or None if missing or unreadable."""
    target = path or CREDENTIALS_PATH
    try:
        data = json.loads(target.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_credentials(
    api_key: str, assigned_number: str | None = None, path: Path | None = None
) -> Path:
    """Write the key with owner-only permissions and return the file path.

    Raises:
        OSError: If the directory or the file can't be written.
    """
    target = path or CREDENTIALS_PATH
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # mkdir's mode doesn't touch a directory that already exists.
    os.chmod(target.parent, 0o700)
    payload = {"api_key": api_key, "assigned_number": assigned_number}
    # Write a brand-new 0600 file (O_EXCL never opens an existing file or a
    # symlink), then rename it over the target. An old file's looser mode never
    # applies to the key, and a symlink at the target is replaced, not followed.
    tmp = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        os.chmod(tmp, 0o600)  # exactly 0600, whatever the umask
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    return target
