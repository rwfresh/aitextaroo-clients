"""Minimal example: listen for inbound SMS and print them.

Usage:
    AITEXTAROO_API_KEY=your-key python examples/simple_listen.py
"""

import asyncio
import os

from aitextaroo import TextarooClient


async def main() -> None:
    api_key = os.environ.get("AITEXTAROO_API_KEY", "")
    if not api_key:
        print("Set AITEXTAROO_API_KEY environment variable")
        return

    client = TextarooClient(api_key=api_key)

    print("Listening for SMS messages... (Ctrl+C to stop)")
    try:
        async for message in client.listen():
            print(f"[{message.received_at}] {message.text}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
