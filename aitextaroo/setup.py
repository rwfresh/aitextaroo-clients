"""Interactive setup for AI Text-a-roo.

Walks the user (or agent) through phone verification and
API key generation. Outputs everything needed to run the bridge.

Each run adds a named key to the account. Nothing else is signed out: the
account's other keys, connected apps and forwarding keep working. An account
holds up to 10 keys, so an 11th removes the one unused the longest (never the
one that forwards the owner's texts); the output says which.

Usage:
    aitextaroo-setup
    aitextaroo-setup --phone +14165550123
    aitextaroo-setup --phone +14165550123 --code 123456
    aitextaroo-setup --phone +14165550123 --code 123456 --label "Bridge on studio-mac"
"""

from __future__ import annotations

import argparse
import asyncio
import re
import socket
import string
import sys
import textwrap
import unicodedata
from typing import TYPE_CHECKING, NoReturn

from aitextaroo.client import TextarooClient, TextarooError
from aitextaroo.credentials import CREDENTIALS_PATH, load_credentials, save_credentials

if TYPE_CHECKING:
    from pathlib import Path

# What the API accepts as a key label: 1-40 of these, runs of spaces collapsed.
LABEL_MAX_LENGTH = 40
_LABEL_CHARS = frozenset(string.ascii_letters + string.digits + " ._()'@#:+-")


def main(argv: list[str] | None = None) -> None:
    """Run the setup flow."""
    args = _parse_args(argv)
    # Check the label before any code is requested or used up.
    try:
        label = clean_label(args.label) if args.label is not None else default_label()
    except ValueError as exc:
        _exit_error(str(exc))

    if args.phone and args.code:
        # Non-interactive: both phone and code provided (agent use)
        asyncio.run(_confirm(args.phone, args.code, args.base_url, save=args.save, label=label))
    elif args.phone:
        # Semi-interactive: phone provided, need code
        asyncio.run(_verify(args.phone, args.base_url))
    else:
        # Fully interactive
        _interactive_setup(args.base_url, save=args.save, label=label)


def default_label(hostname: str | None = None) -> str:
    """'aitextaroo on <short hostname>', cut to what a key label allows."""
    if hostname is None:
        try:
            hostname = socket.gethostname()
        except OSError:
            hostname = ""
    # NFKD splits an accented letter from its accent (é -> e + ´), so the
    # letter survives when characters a label can't use are dropped.
    short = unicodedata.normalize("NFKD", hostname.split(".")[0])
    host = " ".join("".join(c for c in short if c in _LABEL_CHARS).split())
    if not host:
        return "aitextaroo"
    return f"aitextaroo on {host}"[:LABEL_MAX_LENGTH].rstrip()


def clean_label(label: str) -> str:
    """The label as the API will store it: trimmed, runs of spaces collapsed.

    Raises:
        ValueError: If it's empty, too long, or has characters the API rejects.
    """
    cleaned = " ".join(label.split())
    if not cleaned or len(cleaned) > LABEL_MAX_LENGTH:
        raise ValueError(f"--label must be 1 to {LABEL_MAX_LENGTH} characters.")
    bad = "".join(sorted(set(cleaned) - _LABEL_CHARS))
    if bad:
        raise ValueError(
            "--label can only use letters, digits, spaces and . _ ( ) ' @ # : + - "
            f"(not {bad})."
        )
    return cleaned


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aitextaroo-setup",
        description="Set up AI Text-a-roo — verify your phone and get an API key.",
    )
    parser.add_argument(
        "--phone",
        help="Phone number in E.164 format (e.g., +14165550123)",
    )
    parser.add_argument(
        "--code",
        help="6-digit verification code (skip the verify step)",
    )
    parser.add_argument(
        "--base-url",
        default="https://api.aitextaroo.com",
        help="API base URL (default: https://api.aitextaroo.com)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help=(
            f"Save the API key to {CREDENTIALS_PATH} (owner-only) so aitextaroo "
            "and aitextaroo-bridge find it later"
        ),
    )
    parser.add_argument(
        "--label",
        help=(
            "Name for the new key, shown on the dashboard and in the text you get "
            "about it: 1-40 letters, digits, spaces or . _ ( ) ' @ # : + - "
            '(default: "aitextaroo on <this computer\'s name>")'
        ),
    )
    return parser.parse_args(argv)


def _interactive_setup(base_url: str, save: bool = False, label: str | None = None) -> None:
    """Fully interactive setup — prompts for phone and code."""
    print("AI Text-a-roo Setup")
    print("=" * 40)
    print()

    phone = input("Enter your phone number (E.164 format, e.g., +14165550123): ").strip()
    if not phone:
        _exit_error("Phone number is required.")

    asyncio.run(_verify(phone, base_url))

    print()
    code = input("Enter the 6-digit code you received: ").strip()
    if not code:
        _exit_error("Verification code is required.")

    asyncio.run(_confirm(phone, code, base_url, save=save, label=label))


async def _verify(phone: str, base_url: str) -> None:
    """Send verification code to the phone."""
    try:
        result = await TextarooClient.request_verification(phone=phone, base_url=base_url)
        expires = result.get("expires_in", 300)
        print(f"Verification code sent to {phone}")
        print(f"Code expires in {expires // 60} minutes.")
    except TextarooError as e:
        _exit_error(f"Verification failed: {e.message}")


async def _confirm(
    phone: str, code: str, base_url: str, save: bool = False, label: str | None = None
) -> None:
    """Confirm the code, display credentials, and optionally save the key."""
    try:
        result = await TextarooClient.confirm_verification(
            phone=phone, code=code, label=label, base_url=base_url,
        )
    except TextarooError as e:
        _exit_error(f"Confirmation failed: {e.message}")

    api_key = result.get("api_key", "ERROR")
    key_id = result.get("key_id")
    assigned = result.get("assigned_number", "unknown")
    tier = result.get("tier", "free")
    # The API's note says first what changed (a key removed to stay at 10, say).
    note = result.get("note")
    removed = _removed_keys(result.get("retired"))

    # A new key doesn't replace the one saved before: that one may still be
    # on the account, so say so instead of quietly dropping our only copy.
    previous = (load_credentials() or {}).get("api_key") if save else None
    # Save first: if it fails (say HOME isn't writable), fall back to showing
    # the key in full exactly as without --save, so it isn't lost.
    saved_to = _save(api_key, assigned) if save else None

    # Human-readable output
    print()
    print("=" * 40)
    print("Setup complete!")
    print("=" * 40)
    print()
    if isinstance(note, str) and note.strip():
        _say(note)
        print()
    print(f"  Assigned number: {assigned}")
    print(f"  Tier:            {tier}")
    if label:
        print(f"  Key label:       {label}")
    # Once saved, the full key doesn't need to sit in the terminal or a log.
    print(f"  API Key:         {_mask(api_key) if saved_to else api_key}")
    for line in removed:
        print(f"  Removed key:     {line}")
    print()
    if saved_to:
        print(f"  Saved to {saved_to} (owner-only).")
        print("  aitextaroo and aitextaroo-bridge read it automatically.")
        if isinstance(previous, str) and previous and previous != api_key:
            _say(
                f"The key saved there before (ending in {previous[-4:]}) may still be on "
                "your account, and a bridge started before now keeps using it until it's "
                "restarted. Once nothing uses it, remove it on the dashboard or with "
                "`aitextaroo disconnect`."
            )
    else:
        print("  IMPORTANT: Save this API key now. It cannot be retrieved again.")
        print("  (Re-run with --save to store it in ~/.aitextaroo/credentials.json.)")
    print()
    _say(
        "Adding a key doesn't sign anything else out: your other keys, connected apps "
        "and forwarding keep working. An account holds up to 10 keys; adding an 11th "
        "removes the one unused the longest, never the one that forwards your texts "
        "(the note above and a text to you say which). See or remove keys and apps at "
        "aitextaroo.com/dashboard, or run `aitextaroo connections`."
    )
    print()
    print("Next:")
    print()
    print('  aitextaroo send "Hello from your AI!"     # text your phone')
    print("  aitextaroo connect                        # add the MCP server to your agent")
    bridge_cmd = "aitextaroo-bridge" if saved_to else f"aitextaroo-bridge --api-key {api_key}"
    print(f"  {bridge_cmd}   # answer texts with a local CLI agent")
    print()
    print(f"Save {assigned} as a contact (for example, \"My AI\") and text it anytime.")
    print()

    # Machine-readable block for AI agents to parse and persist
    print("--- AGENT PERSISTENCE BLOCK ---")
    if saved_to:
        print(f"AITEXTAROO_API_KEY_SAVED_TO={saved_to}")
    else:
        print(f"AITEXTAROO_API_KEY={api_key}")
    if key_id:
        print(f"AITEXTAROO_KEY_ID={key_id}")
    if label:
        print(f"AITEXTAROO_KEY_LABEL={label}")
    print(f"AITEXTAROO_ASSIGNED_NUMBER={assigned}")
    print(f"AITEXTAROO_USER_PHONE={phone}")
    print(f"AITEXTAROO_TIER={tier}")
    print(f"AITEXTAROO_BRIDGE_CMD={bridge_cmd}")
    print("--- END AGENT PERSISTENCE BLOCK ---")
    if not saved_to:
        print()
        print("If you are an agent setting this up for a user, store the key securely")
        print("for later sessions, or re-run setup with --save so the tools find it.")


def _save(api_key: str, assigned: str) -> Path | None:
    """Save the key to the credentials file; warn and return None on failure."""
    try:
        return save_credentials(api_key, assigned)
    except OSError as exc:
        print(
            f"Warning: could not save the API key to {CREDENTIALS_PATH}: {exc}\n"
            "Store the key printed below yourself; it cannot be retrieved again.",
            file=sys.stderr,
        )
        return None


def _removed_keys(retired: object) -> list[str]:
    """Each key the API removed to stay at 10, as '"label" (why)'; [] when none.

    The API lists them as [{"id": "key_...", "label": "...",
    "forwarding_stopped": "<host>" | None}].
    """
    if not isinstance(retired, list):
        return []
    lines = []
    for key in retired:
        if not isinstance(key, dict):
            continue
        name = key.get("label") or key.get("id")
        if not isinstance(name, str) or not name:
            continue
        why = "to stay at 10 keys"
        host = key.get("forwarding_stopped")
        if isinstance(host, str) and host:
            why += f"; forwarding to {host} is off"
        lines.append(f'"{name}" ({why})')
    return lines


def _say(text: str) -> None:
    """Print a paragraph, indented like the rest of the output and wrapped to fit.

    A `command` in backticks stays on one line, ready to copy.
    """
    # textwrap only breaks at ASCII whitespace, so a no-break space holds a
    # command together until it's printed.
    held = re.sub(r"`[^`]*`", lambda command: command.group().replace(" ", "\u00a0"), text)
    wrapped = textwrap.fill(
        held,
        width=74,
        initial_indent="  ",
        subsequent_indent="  ",
        break_long_words=False,
        break_on_hyphens=False,  # keeps "aitextaroo-setup" in one piece
    )
    print(wrapped.replace("\u00a0", " "))


def _mask(api_key: str) -> str:
    """Show just enough of a key to recognize it: the first 6 characters."""
    return f"{api_key[:6]}…"


def _exit_error(message: str) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
