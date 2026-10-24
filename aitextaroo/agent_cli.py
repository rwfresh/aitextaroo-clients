"""`aitextaroo` — text your user from any agent that has a shell.

Usage:
    aitextaroo send "Build finished. All tests pass."
    aitextaroo ask "Deploy to production? Reply YES or NO" --timeout 120
    aitextaroo wait --timeout 60
    aitextaroo recent [--after-id ID]
    aitextaroo relay --to +12125550100 --name Mom "Happy birthday!"
    aitextaroo verify-pin <<< 4821
    aitextaroo set-pin <<< 4821
    aitextaroo account
    aitextaroo upgrade
    aitextaroo webhook set https://example.com/hook [--auth-header "Bearer ..."] [--pin]
    aitextaroo webhook remove
    aitextaroo connect [claude-code|codex|gemini|cursor|muse-code|claude|chatgpt|grok]

Results are JSON on stdout (except `connect`, which prints instructions);
errors go to stderr with exit code 1. `verify-pin` prints its result and exits
with code 2 when the PIN is wrong, so `aitextaroo verify-pin <<< 4821 && ...` only
proceeds on a match. `verify-pin` and `set-pin` read the PIN from stdin when
it isn't given as an argument; at a terminal they ask for it without echoing.
`webhook set` needs the user's PIN if they set one: pass bare `--pin` to read
it the same way. The API key comes from --api-key, AITEXTAROO_API_KEY, or
~/.aitextaroo/credentials.json (aitextaroo-setup --save).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from dataclasses import asdict
from typing import Any

import httpx

from aitextaroo.client import DEFAULT_BASE_URL, TextarooClient, TextarooError
from aitextaroo.credentials import load_api_key

MCP_URL = "https://api.aitextaroo.com/mcp"

# Exit code for `verify-pin` when the PIN doesn't match (1 means an error).
PIN_REJECTED_EXIT = 2

# How to add the remote MCP server to each client. OAuth-capable apps sign
# in with the user's phone; header-based clients read the key from the env.
CONNECT: dict[str, str] = {
    "claude-code": (
        "Claude Code (with your API key):\n"
        f"  claude mcp add --transport http --scope user aitextaroo {MCP_URL} \\\n"
        '    --header "Authorization: Bearer $AITEXTAROO_API_KEY"\n'
        "Or install the plugin (MCP server + skill):\n"
        "  /plugin marketplace add rwfresh/aitextaroo-clients\n"
        "  /plugin install aitextaroo@aitextaroo"
    ),
    "codex": (
        "Codex:\n"
        f"  codex mcp add aitextaroo --url {MCP_URL}\n"
        "  codex mcp login aitextaroo        # sign in with your phone\n"
        "Or with an API key, in ~/.codex/config.toml:\n"
        "  [mcp_servers.aitextaroo]\n"
        f'  url = "{MCP_URL}"\n'
        '  bearer_token_env_var = "AITEXTAROO_API_KEY"'
    ),
    "gemini": (
        "Gemini CLI:\n"
        "  gemini extensions install https://github.com/rwfresh/aitextaroo-clients\n"
        "Or just the MCP server:\n"
        "  gemini mcp add --transport http --scope user \\\n"
        f'    --header "Authorization: Bearer $AITEXTAROO_API_KEY" aitextaroo {MCP_URL}'
    ),
    "cursor": (
        "Cursor — add to ~/.cursor/mcp.json:\n"
        "  {\n"
        '    "mcpServers": {\n'
        '      "aitextaroo": {\n'
        f'        "url": "{MCP_URL}",\n'
        '        "headers": { "Authorization": "Bearer ${env:AITEXTAROO_API_KEY}" }\n'
        "      }\n"
        "    }\n"
        "  }"
    ),
    "muse-code": (
        "Muse Code — add under mcp_servers in ~/.config/muse/settings.json:\n"
        '  "aitextaroo": {\n'
        '    "transport": "streamable_http",\n'
        f'    "url": "{MCP_URL}",\n'
        '    "headers": { "Authorization": "Bearer <your API key>" }\n'
        "  }"
    ),
    "claude": (
        "Claude, Claude Desktop and Claude Duet:\n"
        "  Customize > Connectors > Add custom connector\n"
        f"  URL: {MCP_URL}  then Connect and sign in with your phone."
    ),
    "chatgpt": (
        "ChatGPT and Dots:\n"
        "  Plugins > + > Add custom MCP server\n"
        f"  URL: {MCP_URL}  then OAuth, sign in with your phone, Create as a plugin.\n"
        "  (On ChatGPT Pro, custom MCP servers are limited to read-only tools.)"
    ),
    "grok": (
        "Grok Bot — say in chat:\n"
        f"  Add a custom MCP server called AI Text-a-roo at {MCP_URL}\n"
        "To text it back anytime, ask Grok Bot to create a webhook routine and\n"
        "register it with the set_webhook tool, or register it yourself:\n"
        '  aitextaroo webhook set <routine URL> --auth-header "Bearer <routine key>" [--pin]\n'
        "(--pin asks for your PIN, needed if you set one. You'll get a text saying\n"
        "where your texts now go; reply UNHOOK anytime to stop forwarding.)"
    ),
}


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.command == "connect":
        _print_connect(args.client)
        return
    key = load_api_key(args.api_key)
    if not key:
        _fail(
            "No API key. Run `aitextaroo-setup --phone +1... --save`, "
            "set AITEXTAROO_API_KEY, or pass --api-key."
        )
    # webhook set only needs the PIN when --pin was given (accounts with a PIN).
    needs_pin = args.command in ("verify-pin", "set-pin") or (
        args.command == "webhook" and args.action == "set" and args.pin is not None
    )
    if needs_pin:
        args.pin = _read_pin(args.pin)
    try:
        result = asyncio.run(_run(args, key))
    except TextarooError as exc:
        _fail(f"{exc.code}: {exc.message}")
    except (httpx.HTTPError, OSError) as exc:
        # Connection refused, DNS failure, timeout... a short line, not a traceback.
        reason = str(exc) or type(exc).__name__
        _fail(f"Network error reaching {args.base_url}: {reason}")
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.command == "verify-pin" and result.get("verified") is not True:
        sys.exit(PIN_REJECTED_EXIT)


async def _run(args: argparse.Namespace, key: str) -> Any:
    client = TextarooClient(api_key=key, base_url=args.base_url)
    try:
        if args.command == "send":
            return {"message_id": await client.send(args.text)}
        if args.command == "ask":
            await client.send(args.text)
            for _ in range(max(1, args.tries)):
                reply = await client.wait_for_reply(args.timeout)
                if reply is not None:
                    return {"reply": asdict(reply)}
            return {"reply": None, "timed_out": True}
        if args.command == "wait":
            reply = await client.wait_for_reply(args.timeout)
            return {"reply": asdict(reply) if reply else None, "timed_out": reply is None}
        if args.command == "recent":
            return {"messages": [asdict(m) for m in await client.recent_messages(args.after_id)]}
        if args.command == "relay":
            return {"message_id": await client.text_contact(args.to, args.text, args.name)}
        if args.command == "verify-pin":
            return await client.verify_pin(args.pin)
        if args.command == "set-pin":
            return await client.set_pin(args.pin)
        if args.command == "account":
            return await client.account()
        if args.command == "upgrade":
            return {"checkout_url": await client.upgrade_link()}
        if args.command == "webhook":
            if args.action == "set":
                return await client.set_webhook(
                    args.url, auth_header=args.auth_header, pin=args.pin
                )
            return await client.remove_webhook()
        raise AssertionError(f"unhandled command {args.command}")
    finally:
        await client.close()


def _print_connect(client: str | None) -> None:
    if client:
        print(CONNECT[client])
        return
    print(f"AI Text-a-roo MCP server: {MCP_URL} (streamable HTTP; OAuth or Bearer API key)\n")
    print("\n\n".join(CONNECT.values()))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aitextaroo", description="Text your user through AI Text-a-roo."
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key (default: AITEXTAROO_API_KEY or ~/.aitextaroo/credentials.json)",
    )
    parser.add_argument(
        "--base-url", default=os.environ.get("AITEXTAROO_BASE_URL", DEFAULT_BASE_URL)
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("send", help="Text the user")
    p.add_argument("text")

    p = sub.add_parser("ask", help="Text the user a question and wait for the answer")
    p.add_argument("text")
    p.add_argument("--timeout", type=int, default=90, help="Seconds per wait, 1-120 (default 90)")
    p.add_argument(
        "--tries", type=int, default=2, help="How many waits before giving up (default 2)"
    )

    p = sub.add_parser("wait", help="Wait for the user's next text")
    p.add_argument("--timeout", type=int, default=60, help="Seconds to wait, 1-120 (default 60)")

    p = sub.add_parser("recent", help="Texts from the last five minutes")
    p.add_argument("--after-id", default=None, help="Only texts after this message id")

    p = sub.add_parser("relay", help="Text a contact on the user's behalf (Pro)")
    p.add_argument("--to", required=True, help="Contact's number, E.164 (e.g. +12125550100)")
    p.add_argument("--name", default=None, help="Contact's name, used to label their replies")
    p.add_argument("text")

    p = sub.add_parser("verify-pin", help="Check a PIN the user texted")
    p.add_argument("pin", nargs="?", help="The PIN (default: read from stdin)")

    p = sub.add_parser("set-pin", help="Set or change the user's security PIN (4-8 digits)")
    p.add_argument("pin", nargs="?", help="The PIN (default: read from stdin)")

    sub.add_parser("account", help="Plan, usage and the AI's phone number")
    sub.add_parser("upgrade", help="Stripe checkout link for Pro")

    p = sub.add_parser("webhook", help="Forward the user's texts to a URL")
    hook = p.add_subparsers(dest="action", required=True)
    s = hook.add_parser("set", help="Register a webhook")
    s.add_argument("url")
    s.add_argument(
        "--auth-header",
        default=None,
        help='Authorization header value sent with each delivery, e.g. "Bearer <token>"',
    )
    s.add_argument(
        "--pin",
        nargs="?",
        const="-",
        default=None,
        help="The user's PIN, if they set one. Bare --pin reads it from stdin or a hidden prompt",
    )
    hook.add_parser("remove", help="Stop webhook delivery")

    p = sub.add_parser("connect", help="Show how to add the MCP server to an agent")
    p.add_argument("client", nargs="?", choices=sorted(CONNECT), help="Which client (default: all)")

    return parser.parse_args(argv)


def _read_pin(arg: str | None) -> str:
    """The PIN from the argument, or from stdin when it's omitted or "-".

    At a terminal it's a hidden prompt; otherwise the first line of stdin.
    """
    if arg not in (None, "-"):
        pin = arg
    elif sys.stdin.isatty():
        pin = getpass.getpass("PIN: ")
    else:
        pin = sys.stdin.readline()
    pin = pin.strip()
    if not pin:
        _fail("No PIN given. Pass it on stdin (aitextaroo verify-pin <<< 4821) or as an argument.")
    return pin


def _fail(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
