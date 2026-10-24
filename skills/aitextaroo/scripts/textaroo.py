#!/usr/bin/env python3
"""AI Text-a-roo command-line helper (Python 3.9+, standard library only).

Text your user and read their replies through https://aitextaroo.com.

    textaroo.py signup --phone +12125551234
    textaroo.py confirm --phone +12125551234 --code 123456
    textaroo.py send "Build finished. Open a PR?"
    textaroo.py wait --timeout 90
    textaroo.py recent [--after-id ID]
    textaroo.py relay --to +12125550100 --name Mom "Happy birthday!"
    textaroo.py verify-pin <<< 4821
    textaroo.py set-pin <<< 4821
    textaroo.py account
    textaroo.py upgrade

Authenticated commands read the API key from AITEXTAROO_API_KEY (or --api-key).
`verify-pin` and `set-pin` read the PIN from stdin unless it's given as an
argument, which keeps it out of shell history and the process list.
Output is JSON on stdout; errors go to stderr with a non-zero exit code.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://api.aitextaroo.com"


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
        detail = exc.read().decode(errors="replace")
        sys.exit(f"HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        sys.exit(f"Network error: {exc.reason}")


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
    p.add_argument("--phone", required=True, help="E.164, e.g. +12125551234")

    p = sub.add_parser("confirm", help="Confirm the code; prints the API key and assigned number")
    p.add_argument("--phone", required=True)
    p.add_argument("--code", required=True)

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
    p.add_argument("pin", nargs="?", help="The PIN (default: read from stdin)")

    sub.add_parser("account", help="Plan, usage and assigned number")
    sub.add_parser("upgrade", help="Stripe checkout link for Pro")

    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    if args.command == "signup":
        result = request("POST", "/auth/verify", base_url=base, body={"phone": args.phone})
    elif args.command == "confirm":
        result = request(
            "POST", "/auth/confirm", base_url=base, body={"phone": args.phone, "code": args.code}
        )
    else:
        if not args.api_key:
            sys.exit(
                "Missing API key: set AITEXTAROO_API_KEY or pass --api-key "
                "(run signup and confirm first)."
            )
        key = args.api_key
        if args.command in ("verify-pin", "set-pin"):
            if args.pin not in (None, "-"):
                pin = args.pin
            elif sys.stdin.isatty():
                pin = getpass.getpass("PIN: ")  # hidden prompt at a terminal
            else:
                pin = sys.stdin.readline()
            pin = pin.strip()
            if not pin:
                sys.exit("No PIN given: pass it on stdin (verify-pin <<< 4821) or as an argument.")
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
            result = request("POST", "/account/pin", base_url=base, api_key=key, body={"pin": pin})
        elif args.command == "account":
            result = request("GET", "/account", base_url=base, api_key=key)
        else:  # upgrade
            result = request("POST", "/billing/checkout", base_url=base, api_key=key)

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    # Like `aitextaroo verify-pin`: a wrong PIN exits 2 so `verify-pin ... && act` stops.
    if args.command == "verify-pin" and result.get("verified") is not True:
        sys.exit(2)


if __name__ == "__main__":
    main()
