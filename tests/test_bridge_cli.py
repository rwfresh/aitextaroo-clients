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
            "Bridge stopped: This key was removed from your account; "
            "run aitextaroo-setup --save to add a new one.\n"
        )

    def test_another_stream_taking_over_exits_cleanly(self, capsys) -> None:
        # Restarting would just knock the other bridge off again.
        _run_bridge(TextarooError("evicted", STREAM_STOPS["evicted"]))
        err = capsys.readouterr().err
        assert err.startswith("Bridge stopped: Another bridge or app is receiving")
        assert "Stop the other one" in err

    def test_rejected_key_is_an_error(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _run_bridge(TextarooError("unauthorized", "Invalid API key", 401))
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert err.startswith("Error: unauthorized: Invalid API key. ")
        assert "aitextaroo-setup --save" in err

    def test_other_api_errors_exit_nonzero(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _run_bridge(TextarooError("http_error", "Stream failed (HTTP 500)", 500))
        assert exc_info.value.code == 1
        assert capsys.readouterr().err == "Error: http_error: Stream failed (HTTP 500)\n"

    def test_ctrl_c(self, capsys) -> None:
        _run_bridge(KeyboardInterrupt())
        assert "Bridge stopped." in capsys.readouterr().out
