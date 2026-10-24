"""Interactive setup for AI Text-a-roo.

Walks the user (or agent) through phone verification and
API key generation. Outputs everything needed to run the bridge.

Usage:
    aitextaroo-setup
    aitextaroo-setup --phone +12125551234
    aitextaroo-setup --phone +12125551234 --code 123456
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING

from aitextaroo.client import TextarooClient, TextarooError
from aitextaroo.credentials import CREDENTIALS_PATH, save_credentials

if TYPE_CHECKING:
    from pathlib import Path


def main() -> None:
    """Run the setup flow."""
    args = _parse_args()

    if args.phone and args.code:
        # Non-interactive: both phone and code provided (agent use)
        asyncio.run(_confirm(args.phone, args.code, args.base_url, save=args.save))
    elif args.phone:
        # Semi-interactive: phone provided, need code
        asyncio.run(_verify(args.phone, args.base_url))
    else:
        # Fully interactive
        _interactive_setup(args.base_url, save=args.save)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aitextaroo-setup",
        description="Set up AI Text-a-roo — verify your phone and get an API key.",
    )
    parser.add_argument(
        "--phone",
        help="Phone number in E.164 format (e.g., +12125551234)",
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
    return parser.parse_args()


def _interactive_setup(base_url: str, save: bool = False) -> None:
    """Fully interactive setup — prompts for phone and code."""
    print("AI Text-a-roo Setup")
    print("=" * 40)
    print()

    phone = input("Enter your phone number (E.164 format, e.g., +12125551234): ").strip()
    if not phone:
        _exit_error("Phone number is required.")

    asyncio.run(_verify(phone, base_url))

    print()
    code = input("Enter the 6-digit code you received: ").strip()
    if not code:
        _exit_error("Verification code is required.")

    asyncio.run(_confirm(phone, code, base_url, save=save))


async def _verify(phone: str, base_url: str) -> None:
    """Send verification code to the phone."""
    try:
        result = await TextarooClient.request_verification(phone=phone, base_url=base_url)
        expires = result.get("expires_in", 300)
        print(f"Verification code sent to {phone}")
        print(f"Code expires in {expires // 60} minutes.")
    except TextarooError as e:
        _exit_error(f"Verification failed: {e.message}")


async def _confirm(phone: str, code: str, base_url: str, save: bool = False) -> None:
    """Confirm the code, display credentials, and optionally save the key."""
    try:
        result = await TextarooClient.confirm_verification(
            phone=phone, code=code, base_url=base_url,
        )
    except TextarooError as e:
        _exit_error(f"Confirmation failed: {e.message}")

    api_key = result.get("api_key", "ERROR")
    assigned = result.get("assigned_number", "unknown")
    tier = result.get("tier", "free")

    # Save first: if it fails (say HOME isn't writable), fall back to showing
    # the key in full exactly as without --save, so it isn't lost.
    saved_to = _save(api_key, assigned) if save else None

    # Human-readable output
    print()
    print("=" * 40)
    print("Setup complete!")
    print("=" * 40)
    print()
    print(f"  Assigned number: {assigned}")
    print(f"  Tier:            {tier}")
    # Once saved, the full key doesn't need to sit in the terminal or a log.
    print(f"  API Key:         {_mask(api_key) if saved_to else api_key}")
    print()
    if saved_to:
        print(f"  Saved to {saved_to} (owner-only).")
        print("  aitextaroo and aitextaroo-bridge read it automatically.")
    else:
        print("  IMPORTANT: Save this API key now. It cannot be retrieved again.")
        print("  (Re-run with --save to store it in ~/.aitextaroo/credentials.json.)")
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


def _mask(api_key: str) -> str:
    """Show just enough of a key to recognize it: the first 6 characters."""
    return f"{api_key[:6]}…"


def _exit_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
