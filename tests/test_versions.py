"""Every file that carries the package version carries the same one."""

import json
import re
from pathlib import Path

import aitextaroo

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ("plugin.json", ".claude-plugin/plugin.json", "gemini-extension.json")


def test_every_manifest_carries_the_package_version() -> None:
    # A regex, not tomllib: tomllib needs Python 3.11 and CI also runs 3.10.
    match = re.search(r'^version = "([^"]+)"$', (ROOT / "pyproject.toml").read_text(), re.M)
    assert match is not None
    version = match.group(1)
    assert aitextaroo.__version__ == version
    for manifest in MANIFESTS:
        assert json.loads((ROOT / manifest).read_text())["version"] == version, manifest
