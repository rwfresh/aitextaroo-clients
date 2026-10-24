"""Tests for what `aitextaroo-setup` prints after confirming a code."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aitextaroo import setup

KEY = "key_abcdef1234567890"
RESULT = {"api_key": KEY, "assigned_number": "+15551110000", "tier": "free"}
SAVED_TO = Path("/home/user/.aitextaroo/credentials.json")


async def _confirm(save: bool, saver: MagicMock) -> None:
    confirm = AsyncMock(return_value=RESULT)
    with (
        patch.object(setup.TextarooClient, "confirm_verification", confirm),
        patch.object(setup, "save_credentials", saver),
    ):
        await setup._confirm("+12125551234", "123456", "https://test.com", save=save)


def _block(out: str) -> list[str]:
    """The lines inside the AGENT PERSISTENCE BLOCK."""
    start = out.index("--- AGENT PERSISTENCE BLOCK ---")
    end = out.index("--- END AGENT PERSISTENCE BLOCK ---")
    return out[start:end].splitlines()[1:]


class TestConfirmOutput:
    @pytest.mark.asyncio
    async def test_without_save_shows_the_key(self, capsys) -> None:
        saver = MagicMock()
        await _confirm(save=False, saver=saver)
        out = capsys.readouterr().out
        saver.assert_not_called()
        assert f"API Key:         {KEY}" in out
        assert f"AITEXTAROO_API_KEY={KEY}" in _block(out)
        assert f"AITEXTAROO_BRIDGE_CMD=aitextaroo-bridge --api-key {KEY}" in _block(out)

    @pytest.mark.asyncio
    async def test_save_masks_the_key_and_keeps_it_out_of_the_block(self, capsys) -> None:
        saver = MagicMock(return_value=SAVED_TO)
        await _confirm(save=True, saver=saver)
        out = capsys.readouterr().out
        saver.assert_called_once_with(KEY, "+15551110000")
        assert KEY not in out
        assert "API Key:         key_ab…" in out
        block = _block(out)
        assert f"AITEXTAROO_API_KEY_SAVED_TO={SAVED_TO}" in block
        assert "AITEXTAROO_BRIDGE_CMD=aitextaroo-bridge" in block
        assert not any(line.startswith("AITEXTAROO_API_KEY=") for line in block)
        assert "--api-key" not in out

    @pytest.mark.asyncio
    async def test_unwritable_home_warns_and_falls_back_to_showing_the_key(self, capsys) -> None:
        error = PermissionError(13, "Permission denied", "/home/user/.aitextaroo")
        await _confirm(save=True, saver=MagicMock(side_effect=error))
        captured = capsys.readouterr()
        assert "Warning: could not save the API key" in captured.err
        assert "Permission denied" in captured.err
        # The same output as without --save, so the key isn't lost.
        assert f"API Key:         {KEY}" in captured.out
        assert f"AITEXTAROO_API_KEY={KEY}" in _block(captured.out)
        assert f"AITEXTAROO_BRIDGE_CMD=aitextaroo-bridge --api-key {KEY}" in _block(captured.out)
