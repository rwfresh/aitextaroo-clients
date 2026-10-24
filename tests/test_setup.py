"""Tests for what `aitextaroo-setup` prints after confirming a code, and key labels."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aitextaroo import setup

KEY = "key_abcdef1234567890"
KEY_ID = "key_0f8c2b9e-3a41-4d6b-9c1e-7a5d2f4b8e10"
RESULT = {"api_key": KEY, "assigned_number": "+15551110000", "tier": "free"}
SAVED_TO = Path("/home/user/.aitextaroo/credentials.json")


async def _confirm(
    save: bool,
    saver: MagicMock,
    label: str | None = None,
    result: dict | None = None,
    saved_before: dict | None = None,
) -> AsyncMock:
    confirm = AsyncMock(return_value=result or RESULT)
    with (
        patch.object(setup.TextarooClient, "confirm_verification", confirm),
        patch.object(setup, "save_credentials", saver),
        patch.object(setup, "load_credentials", return_value=saved_before),
    ):
        await setup._confirm("+12125551234", "123456", "https://test.com", save=save, label=label)
    return confirm


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

    @pytest.mark.asyncio
    async def test_says_a_key_was_added_and_nothing_was_signed_out(self, capsys) -> None:
        await _confirm(save=False, saver=MagicMock())
        out = " ".join(capsys.readouterr().out.split())
        assert (
            "Adding a key doesn't sign anything else out: your other keys, connected apps "
            "and forwarding keep working." in out
        )
        assert (
            "adding an 11th removes the one unused the longest, never the one that forwards "
            "your texts (the note above and a text to you say which)." in out
        )

    @pytest.mark.asyncio
    async def test_prints_the_api_note_under_setup_complete(self, capsys) -> None:
        note = (
            '"aitextaroo on studio-mac" was removed to stay at 10 keys. Key added. Your other '
            "keys and connected apps keep working. See or remove keys at aitextaroo.com/dashboard."
        )
        await _confirm(save=False, saver=MagicMock(), result={**RESULT, "note": note})
        out = " ".join(capsys.readouterr().out.split())
        assert out.index("Setup complete!") < out.index(note) < out.index("Assigned number:")

    @pytest.mark.asyncio
    async def test_names_each_key_removed_to_stay_at_10(self, capsys) -> None:
        retired = [
            {"id": "key_1", "label": "aitextaroo on studio-mac", "forwarding_stopped": None},
            {"id": "key_2", "label": "Old laptop", "forwarding_stopped": "api.x.ai"},
        ]
        await _confirm(save=False, saver=MagicMock(), result={**RESULT, "retired": retired})
        out = capsys.readouterr().out
        assert '  Removed key:     "aitextaroo on studio-mac" (to stay at 10 keys)\n' in out
        assert (
            '  Removed key:     "Old laptop" (to stay at 10 keys; forwarding to api.x.ai is off)\n'
            in out
        )

    @pytest.mark.parametrize("retired", [None, [], "junk", [1, None, {"id": "", "label": ""}]])
    @pytest.mark.asyncio
    async def test_nothing_about_removed_keys_when_none_were(self, capsys, retired) -> None:
        await _confirm(save=False, saver=MagicMock(), result={**RESULT, "retired": retired})
        assert "Removed key" not in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_label_is_sent_and_reported_with_the_key_id(self, capsys) -> None:
        confirm = await _confirm(
            save=False,
            saver=MagicMock(),
            label="Bridge on studio-mac",
            result={**RESULT, "key_id": KEY_ID},
        )
        assert confirm.await_args.kwargs["label"] == "Bridge on studio-mac"
        out = capsys.readouterr().out
        assert "Key label:       Bridge on studio-mac" in out
        block = _block(out)
        assert f"AITEXTAROO_KEY_ID={KEY_ID}" in block
        assert "AITEXTAROO_KEY_LABEL=Bridge on studio-mac" in block

    @pytest.mark.asyncio
    async def test_saving_over_another_key_says_that_one_is_still_on_the_account(
        self, capsys
    ) -> None:
        await _confirm(
            save=True,
            saver=MagicMock(return_value=SAVED_TO),
            saved_before={"api_key": "old_key_ending_3f9a"},
        )
        out = " ".join(capsys.readouterr().out.split())
        assert (
            "The key saved there before (ending in 3f9a) may still be on your account, and a "
            "bridge started before now keeps using it until it's restarted. Once nothing uses "
            "it, remove it on the dashboard or with `aitextaroo disconnect`." in out
        )
        assert "old_key" not in out  # only the part the dashboard shows as its hint

    @pytest.mark.parametrize("saved_before", [None, {"api_key": KEY}, {"other": "junk"}])
    @pytest.mark.asyncio
    async def test_no_note_without_a_different_saved_key(self, capsys, saved_before) -> None:
        await _confirm(save=True, saver=MagicMock(return_value=SAVED_TO), saved_before=saved_before)
        assert "saved there before" not in capsys.readouterr().out


def test_paragraphs_wrap_but_keep_each_command_whole(capsys) -> None:
    # Plain textwrap would end the first line with "`aitextaroo".
    setup._say("To see them, open aitextaroo.com/dashboard or run `aitextaroo connections` now.")
    assert capsys.readouterr().out == (
        "  To see them, open aitextaroo.com/dashboard or run\n"
        "  `aitextaroo connections` now.\n"
    )


class TestLabels:
    @pytest.mark.parametrize(
        ("hostname", "label"),
        [
            ("studio-mac.local", "aitextaroo on studio-mac"),
            ("José's-MacBook-Pro", "aitextaroo on Jose's-MacBook-Pro"),
            ("box_1(lab)", "aitextaroo on box_1(lab)"),
            ("a" * 60, "aitextaroo on " + "a" * 26),
            ("x" * 25 + " yz", "aitextaroo on " + "x" * 25),  # no trailing space after the cut
            ("日本語", "aitextaroo"),
            ("", "aitextaroo"),
        ],
    )
    def test_default_label(self, hostname: str, label: str) -> None:
        assert setup.default_label(hostname) == label
        assert len(label) <= setup.LABEL_MAX_LENGTH
        assert setup.clean_label(label) == label  # always one the API accepts

    def test_default_label_uses_this_computers_name(self) -> None:
        with patch.object(setup.socket, "gethostname", return_value="studio-mac.lan"):
            assert setup.default_label() == "aitextaroo on studio-mac"
        with patch.object(setup.socket, "gethostname", side_effect=OSError):
            assert setup.default_label() == "aitextaroo"

    def test_clean_label_trims_and_collapses_spaces(self) -> None:
        assert setup.clean_label("  Bridge   on\tstudio-mac  ") == "Bridge on studio-mac"
        assert setup.clean_label("Rich's laptop (work) #2: v1.0+@home") == (
            "Rich's laptop (work) #2: v1.0+@home"
        )

    @pytest.mark.parametrize(
        ("label", "reason"),
        [
            ("", "1 to 40 characters"),
            ("   ", "1 to 40 characters"),
            ("x" * 41, "1 to 40 characters"),
            ("no/slashes", "(not /)"),
            ("café 🎉", "(not é🎉)"),
        ],
    )
    def test_clean_label_rejects(self, label: str, reason: str) -> None:
        with pytest.raises(ValueError, match="--label") as exc_info:
            setup.clean_label(label)
        assert reason in str(exc_info.value)


class TestMain:
    @pytest.fixture
    def api(self):
        """(confirm_verification, request_verification) mocks, on studio-mac."""
        confirm = AsyncMock(return_value=RESULT)
        verify = AsyncMock(return_value={"status": "code_sent", "expires_in": 300})
        with (
            patch.object(setup.TextarooClient, "confirm_verification", confirm),
            patch.object(setup.TextarooClient, "request_verification", verify),
            patch.object(setup, "load_credentials", return_value=None),
            patch.object(setup.socket, "gethostname", return_value="studio-mac.local"),
        ):
            yield confirm, verify

    def test_default_label_is_sent(self, api, capsys) -> None:
        confirm, _ = api
        setup.main(["--phone", "+12125551234", "--code", "123456"])
        assert confirm.await_args.kwargs["label"] == "aitextaroo on studio-mac"

    def test_given_label_is_cleaned_and_sent(self, api, capsys) -> None:
        confirm, _ = api
        setup.main(["--phone", "+12125551234", "--code", "123456", "--label", " My  bridge "])
        assert confirm.await_args.kwargs["label"] == "My bridge"

    @pytest.mark.parametrize("code", [["--code", "123456"], []])
    def test_bad_label_fails_before_any_request(self, api, capsys, code) -> None:
        confirm, verify = api
        with pytest.raises(SystemExit) as exc_info:
            setup.main(["--phone", "+12125551234", *code, "--label", "a/b"])
        assert exc_info.value.code == 1
        assert "Error: --label can only use" in capsys.readouterr().err
        confirm.assert_not_awaited()
        verify.assert_not_awaited()
