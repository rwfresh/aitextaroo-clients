#!/usr/bin/env python3
"""AI Text-a-roo command-line helper (Python 3.9+, standard library only).

Text your user and read their replies through https://aitextaroo.com.

    textaroo.py signup --phone +14165550123
    textaroo.py confirm --phone +14165550123 --code 123456 [--label "Claude on studio-mac"]
    textaroo.py send "Build finished. Open a PR?"
    textaroo.py wait --timeout 90
    textaroo.py recent [--after-id ID]
    textaroo.py relay --to +16135550100 --name Mom "Happy birthday!"
    textaroo.py verify-pin <<< 4821
    textaroo.py set-pin <<< 4821
    printf '1111\n4821\n' | textaroo.py set-pin --current   # change it: current, then new
    textaroo.py account
    textaroo.py upgrade
    textaroo.py connections                       # keys and app sign-ins on the account
    textaroo.py disconnect <connection id> [--pin]

Authenticated commands read the API key from AITEXTAROO_API_KEY (or --api-key).
`verify-pin` and `set-pin` read the PIN from stdin unless it's given as an
argument; at a terminal they ask for it without echoing. `disconnect` needs
the PIN only if the user set one: bare `--pin` reads it the same way.
Confirming adds a key to the account; nothing else is signed out.
Output is JSON on stdout; errors go to stderr with a non-zero exit code.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import socket
import string
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://api.aitextaroo.com"

# A key label: 1-40 of these characters (the API's rule).
LABEL_CHARS = frozenset(string.ascii_letters + string.digits + " ._()'@#:+-")
# Connection ids go into the URL path, so nothing like "../" gets there.
CONNECTION_ID = re.compile(r"(?:key|app)_[A-Za-z0-9_-]{1,100}")
# Where FastAPI says a field was sent: the first part of a 422's "loc".
REQUEST_PARTS = ("body", "query", "path", "header", "cookie")


def request(
    method: str,
    path: str,
    *,
    base_url: str,
    api_key: str | None = None,
    body: dict | None = None,
    timeout: float = 30,
) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base_url}/v1{path}", data=data, method=method)  # noqa: S310
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "aitextaroo-skill/1.0")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https base URL)
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        sys.exit(describe_error(exc.code, exc.reason, exc.read()))
    except urllib.error.URLError as exc:
        sys.exit(f"Network error: {exc.reason}")


def describe_error(status: int, reason: str, raw: bytes) -> str:
    """What an API error says, like "HTTP 403: pin_incorrect: Incorrect PIN.".

    Only the code and message are kept (for a 422, the field and the
    problem), never the rest of the body: a 422 also repeats what was sent,
    such as a mistyped PIN.
    """
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = {}
    error, detail = data.get("error"), data.get("detail")
    if not isinstance(error, dict) and isinstance(detail, dict):
        error = detail.get("error")  # authentication failures nest it in "detail"
    if isinstance(error, dict) and error.get("code"):
        message = error.get("message")
        text = f"{error['code']}: {message}" if message else str(error["code"])
    elif isinstance(detail, list) and detail and isinstance(detail[0], dict):
        loc = detail[0].get("loc")
        parts = [str(part) for part in loc] if isinstance(loc, list) else []
        if parts and parts[0] in REQUEST_PARTS:
            parts = parts[1:]
        text = f"{'.'.join(parts) or 'request'}: {detail[0].get('msg') or 'not valid'}"
    elif isinstance(detail, str) and detail:
        text = detail
    else:
        text = reason or "request failed"
    return f"HTTP {status}: {text}"


def read_pin(arg: str | None, prompt: str) -> str:
    """The PIN from the argument, or the next line of stdin (a hidden prompt at a terminal)."""
    if arg not in (None, "-"):
        pin = arg
    elif sys.stdin.isatty():
        pin = getpass.getpass(prompt)
    else:
        pin = sys.stdin.readline()
    pin = pin.strip()
    if not pin:
        sys.exit("No PIN given: pass it on stdin (verify-pin <<< 4821) or as an argument.")
    return pin


def default_label() -> str:
    """'aitextaroo skill on <short hostname>', cut to what a key label allows."""
    try:
        host = socket.gethostname().split(".")[0]
    except OSError:
        host = ""
    # NFKD splits an accented letter from its accent, so the letter survives.
    host = "".join(c for c in unicodedata.normalize("NFKD", host) if c in LABEL_CHARS)
    host = " ".join(host.split())
    return f"aitextaroo skill on {host}"[:40].rstrip() if host else "aitextaroo skill"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="textaroo.py", description="Text your user through AI Text-a-roo."
    )
    parser.add_argument("--api-key", default=os.environ.get("AITEXTAROO_API_KEY"))
    parser.add_argument(
        "--base-url", default=os.environ.get("AITEXTAROO_BASE_URL", DEFAULT_BASE_URL)
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("signup", help="Text a 6-digit verification code to the user's phone")
    p.add_argument("--phone", required=True, help="E.164, e.g. +14165550123")

    p = sub.add_parser(
        "confirm", help="Confirm the code; adds a key and prints it with the assigned number"
    )
    p.add_argument("--phone", required=True)
    p.add_argument("--code", required=True)
    p.add_argument(
        "--label",
        help="Name for the key, shown to the user: 1-40 letters, digits, spaces or "
        ". _ ( ) ' @ # : + - (default: aitextaroo skill on <this computer's name>)",
    )

    p = sub.add_parser("send", help="Text the user")
    p.add_argument("text")

    p = sub.add_parser("relay", help="Text a contact on the user's behalf (Pro)")
    p.add_argument("--to", required=True, help="Contact's number, E.164")
    p.add_argument("--name", help="Contact's name, used to label their replies")
    p.add_argument("text")

    p = sub.add_parser("wait", help="Wait for the user's next text")
    p.add_argument("--timeout", type=int, default=60, help="Seconds to wait (1-120)")

    p = sub.add_parser("recent", help="Texts from the last 5 minutes")
    p.add_argument("--after-id", help="Only texts after this message id")

    p = sub.add_parser("verify-pin", help="Check a PIN the user texted")
    p.add_argument("pin", nargs="?", help="The PIN (default: read from stdin)")

    p = sub.add_parser("set-pin", help="Set or change the user's security PIN (4-8 digits)")
    p.add_argument("pin", nargs="?", help="The new PIN (default: read from stdin)")
    p.add_argument(
        "--current",
        nargs="?",
        const="-",
        help="The current PIN, needed to change one. Bare --current reads it from stdin first",
    )

    sub.add_parser("account", help="Plan, usage and assigned number")
    sub.add_parser("upgrade", help="Stripe checkout link for Pro")
    sub.add_parser("connections", help="Keys and app sign-ins on the account, and forwarding")

    p = sub.add_parser("disconnect", help="Remove a key or app sign-in (the user is texted)")
    p.add_argument("connection_id", help="The id from `connections` (key_... or app_...)")
    p.add_argument(
        "--pin",
        nargs="?",
        const="-",
        help="The user's PIN, if they set one. Bare --pin reads it from stdin or a hidden prompt",
    )

    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    if args.command == "signup":
        result = request("POST", "/auth/verify", base_url=base, body={"phone": args.phone})
    elif args.command == "confirm":
        label = " ".join((args.label if args.label is not None else default_label()).split())
        if not 1 <= len(label) <= 40 or not set(label) <= LABEL_CHARS:
            sys.exit("--label must be 1-40 letters, digits, spaces or . _ ( ) ' @ # : + -")
        body = {"phone": args.phone, "code": args.code, "label": label}
        result = request("POST", "/auth/confirm", base_url=base, body=body)
    else:
        if not args.api_key:
            sys.exit(
                "Missing API key: set AITEXTAROO_API_KEY or pass --api-key "
                "(run signup and confirm first)."
            )
        key = args.api_key
        current = None
        if args.command == "set-pin" and args.current is not None:
            current = read_pin(args.current, "Current PIN: ")  # first line of stdin
        if args.command == "disconnect" and not CONNECTION_ID.fullmatch(args.connection_id):
            sys.exit("Not a connection id (they start with key_ or app_); see `connections`.")
        pin = None
        if args.command in ("verify-pin", "set-pin") or (
            args.command == "disconnect" and args.pin is not None
        ):
            pin = read_pin(args.pin, "New PIN: " if args.command == "set-pin" else "PIN: ")
        if args.command == "send":
            result = request("POST", "/send", base_url=base, api_key=key, body={"text": args.text})
        elif args.command == "relay":
            body = {"text": args.text, "to": args.to}
            if args.name:
                body["recipient_name"] = args.name
            result = request("POST", "/send", base_url=base, api_key=key, body=body)
        elif args.command == "wait":
            timeout = max(1, min(120, args.timeout))
            result = request(
                "POST",
                "/messages/wait",
                base_url=base,
                api_key=key,
                body={"timeout_seconds": timeout},
                timeout=timeout + 15,
            )
        elif args.command == "recent":
            query = (
                f"?{urllib.parse.urlencode({'after_id': args.after_id})}" if args.after_id else ""
            )
            result = request("GET", f"/messages/recent{query}", base_url=base, api_key=key)
        elif args.command == "verify-pin":
            result = request("POST", "/verify-pin", base_url=base, api_key=key, body={"pin": pin})
        elif args.command == "set-pin":
            body = {"pin": pin, **({"current_pin": current} if current else {})}
            result = request("POST", "/account/pin", base_url=base, api_key=key, body=body)
        elif args.command == "account":
            result = request("GET", "/account", base_url=base, api_key=key)
        elif args.command == "connections":
            result = request("GET", "/account/connections", base_url=base, api_key=key)
        elif args.command == "disconnect":
            result = request(
                "DELETE",
                f"/account/connections/{args.connection_id}",
                base_url=base,
                api_key=key,
                body={"pin": pin} if pin else None,
            )
        else:  # upgrade
            result = request("POST", "/billing/checkout", base_url=base, api_key=key)

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    # Like `aitextaroo verify-pin`: a wrong PIN exits 2 so `verify-pin ... && act` stops.
    if args.command == "verify-pin" and result.get("verified") is not True:
        sys.exit(2)


if __name__ == "__main__":
    main()
