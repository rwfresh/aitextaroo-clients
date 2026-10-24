"""Tests for how `aitextaroo-bridge` stops: exit codes and messages."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aitextaroo import cli
from aitextaroo.client import STREAM_STOPS, TextarooError


def _run_bridge(stopped_by: BaseException) -> None:
    """Run cli.main() with a bridge whose run() ends with the given exception."""
    bridge = MagicMock()
    bridge.run = AsyncMock(side_effect=stopped_by)
    agent = MagicMock()
    agent.name = "Claude Code"
    with (
        patch.object(cli, "Bridge", return_value=bridge),
        patch.object(cli, "create_agent", return_value=agent),
    ):
        cli.main(["--api-key", "k", "--agent", "claude", "--no-persist"])


class TestBridgeStops:
    def test_removed_key_exits_cleanly_with_a_clear_message(self, capsys) -> None:
        # Exit 0, so a service set to restart on failure leaves it stopped.
        _run_bridge(TextarooError("credential_revoked", STREAM_STOPS["credential_revoked"]))
        assert capsys.readouterr().err == (
            "Bridge stopped: This key was removed from your account. If you've saved a "
            "new one since, just start the bridge again; otherwise run aitextaroo-setup "
            "--save to add one.\n"
        )

    def test_another_stream_taking_over_exits_cleanly(self, capsys) -> None:
        # Restarting would just knock the other bridge off again.
        _run_bridge(TextarooError("evicted", STREAM_STOPS["evicted"]))
        assert capsys.readouterr().err == (
            "Bridge stopped: Another bridge or program started listening for this "
            "account's texts (with any of its keys), and only one can listen at a time. "
            "Stop the other one, then start this one again.\n"
        )

    def test_rejected_key_exits_cleanly_too(self, capsys) -> None:
        # A key removed while the bridge was off gets a 401 on the next start.
        # That never clears up by itself, so restarting every few seconds
        # would only fill the log.
        _run_bridge(TextarooError("unauthorized", "Invalid API key", 401))
        assert capsys.readouterr().err == (
            "Bridge stopped: this key isn't on your account (wrong, or removed). "
            "Run aitextaroo-setup --save to add one, then start the bridge again.\n"
        )

    def test_other_api_errors_exit_nonzero(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _run_bridge(TextarooError("http_error", "Stream failed (HTTP 500)", 500))
        assert exc_info.value.code == 1
        assert capsys.readouterr().err == "Error: http_error: Stream failed (HTTP 500)\n"

    def test_ctrl_c(self, capsys) -> None:
        _run_bridge(KeyboardInterrupt())
        assert "Bridge stopped." in capsys.readouterr().out
