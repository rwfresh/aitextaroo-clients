"""CLI entry point for the AI Text-a-roo bridge.

Usage:
    aitextaroo-bridge --api-key YOUR_KEY
    aitextaroo-bridge --api-key YOUR_KEY --agent claude
    AITEXTAROO_API_KEY=your_key aitextaroo-bridge
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from aitextaroo.agents import BUILTIN_AGENTS, create_agent, detect_agents
from aitextaroo.bridge import Bridge
from aitextaroo.client import TextarooClient


def main() -> None:
    """Parse arguments, wire dependencies, run the bridge."""
    args = _parse_args()
    _configure_logging(args.verbose)

    api_key = args.api_key
    if not api_key:
        _exit_error("API key required. Use --api-key or set AITEXTAROO_API_KEY.")

    agent_name = _resolve_agent(args.agent)

    # Wire dependencies
    client = TextarooClient(api_key=api_key, base_url=args.base_url)
    agent = create_agent(agent_name)
    bridge = Bridge(client=client, agent=agent)

    print(f"Starting bridge with {agent.name}...")
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
        default=os.environ.get("AITEXTAROO_API_KEY", ""),
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
