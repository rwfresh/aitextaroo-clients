"""Where AI Text-a-roo command-line tools find the API key.

Lookup order: an explicit --api-key, then the AITEXTAROO_API_KEY
environment variable, then ~/.aitextaroo/credentials.json (written by
`aitextaroo-setup --save`). The file lets an agent's future sessions use
the key without the agent having to remember it.

The file is created with owner-only permissions (0600, directory 0700)
and holds the API key and assigned number — never the user's phone.
"""

from __future__ import annotations

import json
import os
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
    """Write the key with owner-only permissions and return the file path."""
    target = path or CREDENTIALS_PATH
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {"api_key": api_key, "assigned_number": assigned_number}
    # Create with 0600 from the start so the key is never world-readable.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    os.chmod(target, 0o600)
    return target
