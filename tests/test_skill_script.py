"""Tests for the skill's standalone script, skills/aitextaroo/scripts/textaroo.py."""

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "aitextaroo" / "scripts" / "textaroo.py"
_spec = importlib.util.spec_from_file_location("textaroo_script", SCRIPT)
textaroo = importlib.util.module_from_spec(_spec)
# No __pycache__ next to the script: the skill folder is copied as it is.
_write_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True
try:
    _spec.loader.exec_module(textaroo)
finally:
    sys.dont_write_bytecode = _write_bytecode

KEY_ID = "key_0f8c2b9e-3a41-4d6b-9c1e-7a5d2f4b8e10"


@pytest.fixture
def run(monkeypatch, capsys):
    """Run the script with argv; returns the (method, path, kwargs) of each request."""

    def _run(*argv: str, result: dict | None = None) -> list[tuple]:
        calls: list[tuple] = []

        def fake_request(method: str, path: str, **kwargs) -> dict:
            calls.append((method, path, kwargs))
            return result or {"status": "ok"}

        monkeypatch.setattr(textaroo, "request", fake_request)
        monkeypatch.setattr(sys, "argv", ["textaroo.py", "--api-key", "k", *argv])
        textaroo.main()
        return calls

    return _run


class TestConfirm:
    def test_sends_the_label(self, run) -> None:
        calls = run(
            "confirm",
            "--phone",
            "+12125551234",
            "--code",
            "123456",
            "--label",
            "  Claude  on studio-mac ",
        )
        assert calls == [
            (
                "POST",
                "/auth/confirm",
                {
                    "base_url": "https://api.aitextaroo.com",
                    "body": {
                        "phone": "+12125551234",
                        "code": "123456",
                        "label": "Claude on studio-mac",
                    },
                },
            )
        ]

    def test_default_label_names_this_computer(self, run, monkeypatch) -> None:
        monkeypatch.setattr(textaroo.socket, "gethostname", lambda: "José-studio.local")
        calls = run("confirm", "--phone", "+12125551234", "--code", "123456")
        assert calls[0][2]["body"]["label"] == "aitextaroo skill on Jose-studio"

    def test_default_label_without_a_usable_hostname(self, monkeypatch) -> None:
        monkeypatch.setattr(textaroo.socket, "gethostname", lambda: "日本")
        assert textaroo.default_label() == "aitextaroo skill"
        monkeypatch.setattr(textaroo.socket, "gethostname", lambda: "x" * 80)
        assert len(textaroo.default_label()) == 40

    @pytest.mark.parametrize("label", ["", "a/b", "x" * 41])
    def test_bad_label_never_reaches_the_api(self, run, label) -> None:
        with pytest.raises(SystemExit, match="--label must be"):
            run("confirm", "--phone", "+12125551234", "--code", "123456", "--label", label)


class TestConnections:
    def test_list(self, run) -> None:
        calls = run("connections")
        assert [(method, path) for method, path, _ in calls] == [("GET", "/account/connections")]
        assert calls[0][2]["api_key"] == "k"

    def test_disconnect_without_a_pin_never_reads_stdin(self, run, monkeypatch) -> None:
        stdin = io.StringIO("4821\n")
        monkeypatch.setattr(sys, "stdin", stdin)
        calls = run("disconnect", KEY_ID)
        assert calls[0][:2] == ("DELETE", f"/account/connections/{KEY_ID}")
        assert calls[0][2]["body"] is None
        assert stdin.read() == "4821\n"

    def test_disconnect_reads_the_pin_from_stdin(self, run, monkeypatch) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO("4821\n"))
        calls = run("disconnect", "app_Q2xhdWRlRmFtaWx5", "--pin")
        assert calls[0][:2] == ("DELETE", "/account/connections/app_Q2xhdWRlRmFtaWx5")
        assert calls[0][2]["body"] == {"pin": "4821"}

    @pytest.mark.parametrize("connection_id", ["../../webhook", "..", "key_a/b", "webhook"])
    def test_anything_but_a_connection_id_never_reaches_the_api(self, run, connection_id) -> None:
        with pytest.raises(SystemExit, match="Not a connection id"):
            run("disconnect", connection_id)


def test_request_sends_a_delete_with_its_json_body(monkeypatch) -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"status": "removed"}'
    urlopen = MagicMock(return_value=response)
    monkeypatch.setattr(textaroo.urllib.request, "urlopen", urlopen)
    result = textaroo.request(
        "DELETE",
        f"/account/connections/{KEY_ID}",
        base_url="https://test.com",
        api_key="k",
        body={"pin": "4821"},
    )
    assert result == {"status": "removed"}
    sent = urlopen.call_args.args[0]
    assert sent.get_method() == "DELETE"
    assert sent.full_url == f"https://test.com/v1/account/connections/{KEY_ID}"
    assert json.loads(sent.data) == {"pin": "4821"}
    assert sent.get_header("Authorization") == "Bearer k"
