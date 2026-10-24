"""Tests for the `aitextaroo` command and the credentials file."""

import io
import json
import stat
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from aitextaroo import agent_cli
from aitextaroo.credentials import load_api_key, load_credentials, save_credentials
from aitextaroo.models import InboundMessage

REPLY = InboundMessage(id="m1", text="YES", received_at="2026-10-23T12:00:00Z")


class TestCredentials:
    def test_save_is_owner_only_and_round_trips(self, tmp_path) -> None:
        path = save_credentials(
            "key_123", "+15551110000", path=tmp_path / "creds" / "credentials.json"
        )
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert load_credentials(path) == {"api_key": "key_123", "assigned_number": "+15551110000"}

    def test_lookup_order(self, tmp_path, monkeypatch) -> None:
        path = save_credentials("from_file", path=tmp_path / "credentials.json")
        monkeypatch.delenv("AITEXTAROO_API_KEY", raising=False)
        assert load_api_key(path=path) == "from_file"
        monkeypatch.setenv("AITEXTAROO_API_KEY", "from_env")
        assert load_api_key(path=path) == "from_env"
        assert load_api_key("explicit", path=path) == "explicit"

    def test_missing_or_corrupt_file(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("AITEXTAROO_API_KEY", raising=False)
        assert load_api_key(path=tmp_path / "nope.json") == ""
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        assert load_api_key(path=bad) == ""

    def test_overwriting_a_loose_file_leaves_it_owner_only(self, tmp_path) -> None:
        folder = tmp_path / "creds"
        folder.mkdir(mode=0o755)
        folder.chmod(0o755)
        path = folder / "credentials.json"
        path.write_text('{"api_key": "old"}')
        path.chmod(0o644)
        # Anyone who opened the old world-readable file must never see the new key.
        with path.open() as opened_earlier:
            save_credentials("new_key", path=path)
            assert "new_key" not in opened_earlier.read()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
        assert load_credentials(path)["api_key"] == "new_key"
        assert [p.name for p in folder.iterdir()] == ["credentials.json"]  # no temp file left

    def test_symlink_is_replaced_not_followed(self, tmp_path) -> None:
        victim = tmp_path / "victim.txt"
        victim.write_text("do not touch")
        folder = tmp_path / "creds"
        folder.mkdir()
        link = folder / "credentials.json"
        link.symlink_to(victim)
        save_credentials("key_123", path=link)
        assert victim.read_text() == "do not touch"
        assert not link.is_symlink()
        assert stat.S_IMODE(link.stat().st_mode) == 0o600
        assert load_credentials(link)["api_key"] == "key_123"

    def test_failed_write_leaves_no_temp_file(self, tmp_path) -> None:
        folder = tmp_path / "creds"
        with (
            patch("aitextaroo.credentials.os.replace", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            save_credentials("key_123", path=folder / "credentials.json")
        assert list(folder.iterdir()) == []


def _run_cli(argv: list[str], capsys) -> dict:
    agent_cli.main(argv)
    return json.loads(capsys.readouterr().out)


class TestCommands:
    def _client(self) -> AsyncMock:
        client = AsyncMock()
        client.send.return_value = "msg_1"
        client.text_contact.return_value = "msg_2"
        client.close.return_value = None
        return client

    def test_send(self, capsys) -> None:
        client = self._client()
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(["--api-key", "k", "send", "Hello"], capsys)
        assert out == {"message_id": "msg_1"}
        client.send.assert_awaited_once_with("Hello")
        client.close.assert_awaited_once()

    def test_ask_returns_first_reply(self, capsys) -> None:
        client = self._client()
        client.wait_for_reply.side_effect = [None, REPLY]
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(
                ["--api-key", "k", "ask", "Deploy?", "--timeout", "30", "--tries", "3"], capsys
            )
        assert out["reply"]["text"] == "YES"
        assert client.wait_for_reply.await_count == 2
        client.send.assert_awaited_once_with("Deploy?")

    def test_ask_times_out(self, capsys) -> None:
        client = self._client()
        client.wait_for_reply.return_value = None
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(["--api-key", "k", "ask", "Deploy?", "--tries", "2"], capsys)
        assert out == {"reply": None, "timed_out": True}
        assert client.wait_for_reply.await_count == 2

    def test_relay(self, capsys) -> None:
        client = self._client()
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(
                ["--api-key", "k", "relay", "--to", "+12125550100", "--name", "Mom", "Hi Mom"],
                capsys,
            )
        assert out == {"message_id": "msg_2"}
        client.text_contact.assert_awaited_once_with("+12125550100", "Hi Mom", "Mom")

    def test_webhook_set(self, capsys) -> None:
        client = self._client()
        client.set_webhook.return_value = {"status": "registered", "has_auth_header": True}
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(
                [
                    "--api-key",
                    "k",
                    "webhook",
                    "set",
                    "https://hook.example",
                    "--auth-header",
                    "Bearer t",
                ],
                capsys,
            )
        assert out["has_auth_header"] is True
        client.set_webhook.assert_awaited_once_with(
            "https://hook.example", auth_header="Bearer t", pin=None
        )

    def test_webhook_set_reads_the_pin_from_stdin(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("4821\n"))
        client = self._client()
        client.set_webhook.return_value = {"status": "registered", "owner_notified": True}
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            _run_cli(["--api-key", "k", "webhook", "set", "https://hook.example", "--pin"], capsys)
        client.set_webhook.assert_awaited_once_with(
            "https://hook.example", auth_header=None, pin="4821"
        )

    def test_api_error_exits_nonzero(self, capsys) -> None:
        from aitextaroo.client import TextarooError

        client = self._client()
        client.send.side_effect = TextarooError("daily_limit_reached", "Limit reached", 429)
        with (
            patch.object(agent_cli, "TextarooClient", return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            agent_cli.main(["--api-key", "k", "send", "Hi"])
        assert exc_info.value.code == 1
        assert "daily_limit_reached" in capsys.readouterr().err

    def test_verify_pin_match_exits_zero(self, capsys) -> None:
        client = self._client()
        client.verify_pin.return_value = {"verified": True, "attempts_remaining": None}
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(["--api-key", "k", "verify-pin", "4821"], capsys)
        assert out["verified"] is True

    def test_wrong_pin_exits_2_after_printing_the_result(self, capsys) -> None:
        # So `aitextaroo verify-pin 1234 && do-something` stops on a wrong PIN.
        client = self._client()
        client.verify_pin.return_value = {"verified": False, "attempts_remaining": 2}
        with (
            patch.object(agent_cli, "TextarooClient", return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            agent_cli.main(["--api-key", "k", "verify-pin", "1234"])
        assert exc_info.value.code == 2
        assert json.loads(capsys.readouterr().out) == {"verified": False, "attempts_remaining": 2}

    @pytest.mark.parametrize("argv", [["verify-pin"], ["verify-pin", "-"]])
    def test_verify_pin_reads_stdin(self, argv, capsys, monkeypatch) -> None:
        # `aitextaroo verify-pin <<< 4821` keeps the PIN out of argv.
        monkeypatch.setattr("sys.stdin", io.StringIO("4821\n"))
        client = self._client()
        client.verify_pin.return_value = {"verified": True, "attempts_remaining": None}
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(["--api-key", "k", *argv], capsys)
        assert out["verified"] is True
        client.verify_pin.assert_awaited_once_with("4821")

    def test_set_pin_reads_stdin(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("  482193\n"))
        client = self._client()
        client.set_pin.return_value = {"status": "pin_set"}
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(["--api-key", "k", "set-pin"], capsys)
        assert out == {"status": "pin_set"}
        client.set_pin.assert_awaited_once_with("482193", current_pin=None)

    def test_changing_the_pin_reads_the_current_one_first(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("1111\n4821\n"))
        client = self._client()
        client.set_pin.return_value = {"status": "pin_changed"}
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(["--api-key", "k", "set-pin", "--current"], capsys)
        assert out == {"status": "pin_changed"}
        client.set_pin.assert_awaited_once_with("4821", current_pin="1111")

    def test_remove_pin_reads_the_current_pin(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("1111\n"))
        client = self._client()
        client.remove_pin.return_value = {"status": "pin_removed"}
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(["--api-key", "k", "remove-pin"], capsys)
        assert out == {"status": "pin_removed"}
        client.remove_pin.assert_awaited_once_with("1111")

    def test_pin_prompt_is_hidden_at_a_terminal(self, capsys, monkeypatch) -> None:
        tty = io.StringIO()
        tty.isatty = lambda: True  # type: ignore[method-assign]
        monkeypatch.setattr("sys.stdin", tty)
        client = self._client()
        client.verify_pin.return_value = {"verified": True, "attempts_remaining": None}
        with (
            patch.object(agent_cli, "TextarooClient", return_value=client),
            patch.object(agent_cli.getpass, "getpass", return_value="4821") as prompt,
        ):
            _run_cli(["--api-key", "k", "verify-pin"], capsys)
        prompt.assert_called_once()
        client.verify_pin.assert_awaited_once_with("4821")

    def test_missing_pin_fails_before_calling_the_api(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        client = self._client()
        with (
            patch.object(agent_cli, "TextarooClient", return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            agent_cli.main(["--api-key", "k", "verify-pin"])
        assert exc_info.value.code == 1
        assert "No PIN given" in capsys.readouterr().err
        client.verify_pin.assert_not_called()

    def test_connections(self, capsys) -> None:
        listing = {
            "keys": [{"id": "key_1", "current": True}],
            "apps": [],
            "forwarding": None,
            "max_keys": 10,
        }
        client = self._client()
        client.list_connections.return_value = listing
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(["--api-key", "k", "connections"], capsys)
        assert out == listing
        client.close.assert_awaited_once()

    def test_disconnect_without_a_pin_never_reads_stdin(self, capsys, monkeypatch) -> None:
        stdin = io.StringIO("4821\n")
        monkeypatch.setattr("sys.stdin", stdin)
        client = self._client()
        client.remove_connection.return_value = {"status": "removed", "was_current": False}
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            out = _run_cli(["--api-key", "k", "disconnect", "app_grok1234"], capsys)
        assert out["status"] == "removed"
        client.remove_connection.assert_awaited_once_with("app_grok1234", pin=None)
        assert stdin.read() == "4821\n"  # untouched

    def test_disconnect_reads_the_pin_from_stdin(self, capsys, monkeypatch) -> None:
        # `disconnect <id> --pin <<< 4821` keeps the PIN out of argv.
        monkeypatch.setattr("sys.stdin", io.StringIO("4821\n"))
        client = self._client()
        client.remove_connection.return_value = {"status": "removed", "was_current": False}
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            _run_cli(["--api-key", "k", "disconnect", "key_abc", "--pin"], capsys)
        client.remove_connection.assert_awaited_once_with("key_abc", pin="4821")

    def test_disconnect_pin_prompt_is_hidden_at_a_terminal(self, capsys, monkeypatch) -> None:
        tty = io.StringIO()
        tty.isatty = lambda: True  # type: ignore[method-assign]
        monkeypatch.setattr("sys.stdin", tty)
        client = self._client()
        client.remove_connection.return_value = {"status": "removed", "was_current": False}
        with (
            patch.object(agent_cli, "TextarooClient", return_value=client),
            patch.object(agent_cli.getpass, "getpass", return_value="4821") as prompt,
        ):
            _run_cli(["--api-key", "k", "disconnect", "key_abc", "--pin"], capsys)
        prompt.assert_called_once_with("PIN: ")
        client.remove_connection.assert_awaited_once_with("key_abc", pin="4821")

    def test_disconnect_with_an_empty_pin_fails_before_calling_the_api(
        self, capsys, monkeypatch
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
        client = self._client()
        with (
            patch.object(agent_cli, "TextarooClient", return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            agent_cli.main(["--api-key", "k", "disconnect", "key_abc", "--pin"])
        assert exc_info.value.code == 1
        assert "No PIN given" in capsys.readouterr().err
        client.remove_connection.assert_not_called()

    def test_disconnecting_this_key_says_it_no_longer_works(self, capsys) -> None:
        client = self._client()
        client.remove_connection.return_value = {"status": "removed", "was_current": True}
        with patch.object(agent_cli, "TextarooClient", return_value=client):
            agent_cli.main(["--api-key", "k", "disconnect", "key_abc"])
        captured = capsys.readouterr()
        assert json.loads(captured.out)["was_current"] is True
        assert "that was the key this command uses" in captured.err
        assert "aitextaroo-setup --save" in captured.err

    def test_disconnect_error_exits_nonzero(self, capsys) -> None:
        from aitextaroo.client import TextarooError

        client = self._client()
        client.remove_connection.side_effect = TextarooError(
            "pin_required", "This account has a security PIN.", 403
        )
        with (
            patch.object(agent_cli, "TextarooClient", return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            agent_cli.main(["--api-key", "k", "disconnect", "key_abc"])
        assert exc_info.value.code == 1
        assert "pin_required: This account has a security PIN." in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (httpx.ConnectError("[Errno 111] Connection refused"), "Connection refused"),
            (httpx.ReadTimeout(""), "ReadTimeout"),
            (OSError("Network is unreachable"), "Network is unreachable"),
        ],
    )
    def test_network_error_is_one_line_not_a_traceback(self, capsys, error, expected) -> None:
        client = self._client()
        client.send.side_effect = error
        with (
            patch.object(agent_cli, "TextarooClient", return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            agent_cli.main(["--api-key", "k", "send", "Hi"])
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert err.startswith("Error: Network error reaching https://api.aitextaroo.com")
        assert expected in err
        assert err.count("\n") == 1
        client.close.assert_awaited_once()

    def test_missing_key(self, capsys, monkeypatch) -> None:
        monkeypatch.delenv("AITEXTAROO_API_KEY", raising=False)
        with patch.object(agent_cli, "load_api_key", return_value=""), pytest.raises(SystemExit):
            agent_cli.main(["send", "Hi"])
        assert "No API key" in capsys.readouterr().err


class TestConnect:
    def test_all_clients_need_no_key(self, capsys, monkeypatch) -> None:
        monkeypatch.delenv("AITEXTAROO_API_KEY", raising=False)
        agent_cli.main(["connect"])
        out = capsys.readouterr().out
        assert agent_cli.MCP_URL in out
        for name in ("Claude Code", "Codex", "Gemini CLI", "Cursor", "Grok Bot"):
            assert name in out

    def test_single_client(self, capsys) -> None:
        agent_cli.main(["connect", "codex"])
        out = capsys.readouterr().out
        assert "codex mcp add aitextaroo" in out
        assert "Cursor" not in out

    def test_never_prints_a_real_key(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("AITEXTAROO_API_KEY", "secret_key_value")
        agent_cli.main(["connect"])
        assert "secret_key_value" not in capsys.readouterr().out
