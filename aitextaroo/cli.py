"""CLI entry point for the AI Text-a-roo bridge.

Usage:
    aitextaroo-bridge --api-key YOUR_KEY
    aitextaroo-bridge --api-key YOUR_KEY --agent claude
    AITEXTAROO_API_KEY=YOUR_KEY aitextaroo-bridge
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from aitextaroo.agents import BUILTIN_AGENTS, create_agent, detect_agents
from aitextaroo.bridge import Bridge
from aitextaroo.client import TextarooClient

DEFAULT_SESSIONS_DIR = Path.home() / ".aitextaroo" / "sessions"


def main() -> None:
    """Parse arguments, wire dependencies, run the bridge."""
    args = _parse_args()
    _configure_logging(args.verbose)

    key = args.api_key or os.environ.get("AITEXTAROO_API_KEY", "")
    if not key:
        _exit_error("API key required. Use --api-key or set AITEXTAROO_API_KEY.")

    agent_name = _resolve_agent(args.agent)

    # Session persistence
    sessions_dir: Path | None = None
    if not args.no_persist:
        sessions_dir = Path(args.sessions_dir)

    # Wire dependencies
    client = TextarooClient(api_key=key, base_url=args.base_url)
    agent = create_agent(agent_name)
    bridge = Bridge(
        client=client,
        agent=agent,
        sessions_dir=sessions_dir,
    )

    print(f"Starting bridge with {agent.name}...")
    if sessions_dir:
        print(f"Sessions: {sessions_dir}")
    else:
        print("Sessions: in-memory only (--no-persist)")
    print("Listening for SMS messages. Ctrl+C to stop.")

    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        print("\nBridge stopped.")


def _parse_args() -> argparse.Namespace:
    """Build and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="aitextaroo-bridge",
        description="Bridge SMS messages to your AI agent. Your agent gets a phone number.",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="AI Text-a-roo API key (or set AITEXTAROO_API_KEY env var)",
    )
    parser.add_argument(
        "--agent",
        choices=["auto", *BUILTIN_AGENTS.keys()],
        default="auto",
        help="Which agent to use (default: auto-detect)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AITEXTAROO_BASE_URL", "https://api.aitextaroo.com"),
        help="API base URL (default: https://api.aitextaroo.com)",
    )
    parser.add_argument(
        "--sessions-dir",
        default=str(DEFAULT_SESSIONS_DIR),
        help=f"Session file directory (default: {DEFAULT_SESSIONS_DIR})",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Disable session persistence (in-memory only)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def _configure_logging(verbose: bool) -> None:
    """Set up logging for the bridge process."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _resolve_agent(choice: str) -> str:
    """Resolve 'auto' to a detected agent name, or validate the explicit choice."""
    if choice != "auto":
        return choice

    agents = detect_agents()
    if not agents:
        _exit_error(
            "No supported AI agent found on PATH. Install one of:\n"
            + "".join(f"  - {name}\n" for name in BUILTIN_AGENTS)
        )
    print(f"Auto-detected agent: {agents[0]}")
    return agents[0]


def _exit_error(message: str) -> None:
    """Print error to stderr and exit."""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
