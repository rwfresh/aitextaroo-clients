"""Echo bot: receives SMS, sends the same text back.

The simplest possible agent — proves the full round-trip works.

Usage:
    AITEXTAROO_API_KEY=your-key python examples/echo_bot.py
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

    print("Echo bot running... text your assigned number!")
    try:
        async for message in client.listen():
            print(f"Received: {message.text}")
            await client.send(f"Echo: {message.text}")
            print(f"Replied: Echo: {message.text}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
