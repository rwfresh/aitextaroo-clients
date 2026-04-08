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

from aitextaroo.client import TextarooClient, TextarooError


def main() -> None:
    """Run the setup flow."""
    args = _parse_args()

    if args.phone and args.code:
        # Non-interactive: both phone and code provided (agent use)
        asyncio.run(_confirm(args.phone, args.code, args.base_url))
    elif args.phone:
        # Semi-interactive: phone provided, need code
        asyncio.run(_verify(args.phone, args.base_url))
    else:
        # Fully interactive
        _interactive_setup(args.base_url)


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
    return parser.parse_args()


def _interactive_setup(base_url: str) -> None:
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

    asyncio.run(_confirm(phone, code, base_url))


async def _verify(phone: str, base_url: str) -> None:
    """Send verification code to the phone."""
    try:
        result = await TextarooClient.request_verification(phone=phone, base_url=base_url)
        expires = result.get("expires_in", 300)
        print(f"Verification code sent to {phone}")
        print(f"Code expires in {expires // 60} minutes.")
    except TextarooError as e:
        _exit_error(f"Verification failed: {e.message}")


async def _confirm(phone: str, code: str, base_url: str) -> None:
    """Confirm the code and display credentials."""
    try:
        result = await TextarooClient.confirm_verification(
            phone=phone, code=code, base_url=base_url,
        )
    except TextarooError as e:
        _exit_error(f"Confirmation failed: {e.message}")

    api_key = result.get("api_key", "ERROR")
    assigned = result.get("assigned_number", "unknown")
    tier = result.get("tier", "free")

    # Human-readable output
    print()
    print("=" * 40)
    print("Setup complete!")
    print("=" * 40)
    print()
    print(f"  Assigned number: {assigned}")
    print(f"  Tier:            {tier}")
    print(f"  API Key:         {api_key}")
    print()
    print("  IMPORTANT: Save this API key now. It cannot be retrieved again.")
    print()
    print("To start the bridge:")
    print()
    print(f"  aitextaroo-bridge --api-key {api_key}")
    print()

    # Machine-readable block for AI agents to parse and persist
    print("--- AGENT PERSISTENCE BLOCK ---")
    print(f"AITEXTAROO_API_KEY={api_key}")
    print(f"AITEXTAROO_ASSIGNED_NUMBER={assigned}")
    print(f"AITEXTAROO_USER_PHONE={phone}")
    print(f"AITEXTAROO_TIER={tier}")
    print(f"AITEXTAROO_BRIDGE_CMD=aitextaroo-bridge --api-key {api_key}")
    print("--- END AGENT PERSISTENCE BLOCK ---")
    print()
    print("AI agents: save the values above to your memory or config.")


def _exit_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
